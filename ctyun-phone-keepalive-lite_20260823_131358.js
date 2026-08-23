/*
天翼云手机无感保活（不顶号版本）

基于 Magisk 模块分析，只做轻量级 WebSocket 心跳，不进入桌面，不会踢掉其他客户端。

环境变量:
1. OCR_SERVER=http://127.0.0.1:5000
2. CTYUN_PHONE_ACCOUNTS=账号1#密码1&账号2#密码2

兼容变量:
1. CTYUN_ACCOUNTS=账号1#密码1&账号2#密码2

可选变量:
1. CTYUN_HEARTBEAT_INTERVAL=30000  (心跳间隔，默认30秒)
2. CTYUN_KEEPALIVE_DURATION=300000 (保活时长，默认5分钟)
3. CTYUN_DEBUG=false
4. CTYUN_STATE_FILE=自定义状态文件路径
*/

const fs = require("fs");
const path = require("path");
const crypto = require("crypto");

if (typeof fetch !== "function") {
  throw new Error("当前 Node 环境不支持 fetch，请使用 Node.js 18+ 运行。");
}

function resolveWebSocketImpl() {
  if (typeof WebSocket === "function") {
    return WebSocket;
  }

  for (const loader of [() => require("ws"), () => require("undici").WebSocket]) {
    try {
      const loaded = loader();
      const impl = loaded && (loaded.WebSocket || loaded.default || loaded);
      if (typeof impl === "function") {
        return impl;
      }
    } catch (error) {
      continue;
    }
  }

  throw new Error(
    "当前 Node 环境没有可用的 WebSocket 实现。Node.js 20 无需升级，先安装 ws 后再运行。"
  );
}

const WebSocketImpl = resolveWebSocketImpl();
const WS_READY_STATE_OPEN =
  typeof WebSocketImpl.OPEN === "number" ? WebSocketImpl.OPEN : 1;
const WS_READY_STATE_CONNECTING =
  typeof WebSocketImpl.CONNECTING === "number" ? WebSocketImpl.CONNECTING : 0;

const API_HOST = "https://desk.ctyun.cn:8810";
const DESKTOP_TOKEN_HEADER = "X-AUTH-TOKEN";

const DEFAULTS = {
  // 设备信息（模拟 Android 手机）
  appModel: 3,
  deviceType: 60,
  osType: 15,
  appVersion: "3.2.0",
  version: 103020001,
  deviceName: "Android Phone",
  deviceModel: "Android 13",
  sysVersion: "Android 13",
  userAgent:
    "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 " +
    "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
  
  // 网络配置
  requestTimeoutMs: 15000,
  networkRetryCount: 2,
  networkRetryDelayMs: 1500,
  
  // 保活配置
  heartbeatIntervalMs: 30 * 1000,  // 30秒心跳
  keepaliveDurationMs: 5 * 60 * 1000, // 保活5分钟
  maxCaptchaRetries: 5,
  
  debug: false,
};

const API_CODES = {
  NO_PERMISSIONS: 40010,
  INVALID_PASSWORD: 51010,
  AUTH_LOCKED: 51020,
  INVALID_CAPTCHA: 51030,
  EXPIRE_CAPTCHA: 51031,
  NEED_CAPTCHA: 51040,
  ERROR_CAPTCHA: 51085,
};

class ApiError extends Error {
  constructor(message, code, payload, meta = {}) {
    super(message);
    this.name = "ApiError";
    this.code = Number(code || 0);
    this.payload = payload;
    this.method = String(meta.method || "").toUpperCase();
    this.pathname = String(meta.pathname || "");
    this.auth = Boolean(meta.auth);
  }
}

function readEnv(...names) {
  for (const name of names) {
    const value = process.env[name];
    if (value !== undefined && String(value).trim() !== "") {
      return String(value).trim();
    }
  }
  return "";
}

function readIntEnv(name, fallback) {
  const raw = process.env[name];
  if (raw === undefined || String(raw).trim() === "") {
    return fallback;
  }
  const value = Number(raw);
  if (!Number.isFinite(value)) {
    throw new Error(`${name} 必须是数字。`);
  }
  return value;
}

function readBoolEnv(name, fallback) {
  const raw = process.env[name];
  if (raw === undefined || String(raw).trim() === "") {
    return fallback;
  }

  const value = String(raw).trim().toLowerCase();
  if (["1", "true", "yes", "on"].includes(value)) {
    return true;
  }
  if (["0", "false", "no", "off"].includes(value)) {
    return false;
  }
  throw new Error(`${name} 必须是 true/false。`);
}

function normalizeAccountKey(username) {
  return String(username || "").trim().toLowerCase();
}

function sha256(text) {
  return crypto.createHash("sha256").update(String(text)).digest("hex");
}

function md5Upper(text) {
  return crypto.createHash("md5").update(String(text)).digest("hex").toUpperCase();
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function nowText() {
  const date = new Date();
  const pad = (value) => String(value).padStart(2, "0");
  return (
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ` +
    `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
  );
}

function divider(char = "=") {
  console.log(char.repeat(68));
}

function section(title) {
  console.log("");
  divider();
  console.log(title);
  divider();
}

function line(label, message) {
  console.log(`${label} ${message}`);
}

function maskAccount(account) {
  const value = String(account || "").trim();
  if (/^\d{11}$/.test(value)) {
    return `${value.slice(0, 3)}****${value.slice(-4)}`;
  }
  if (value.includes("@")) {
    const [name, domain] = value.split("@");
    if (name.length <= 2) {
      return `${name[0] || "*"}***@${domain}`;
    }
    return `${name.slice(0, 2)}***@${domain}`;
  }
  if (value.length <= 4) {
    return `${value[0] || "*"}***`;
  }
  return `${value.slice(0, 2)}***${value.slice(-2)}`;
}

function shorten(text, maxLength = 120) {
  const value = String(text || "").replace(/\s+/g, " ").trim();
  if (value.length <= maxLength) {
    return value;
  }
  return `${value.slice(0, maxLength - 3)}...`;
}

function buildErrorMessage(error) {
  if (error instanceof ApiError) {
    return error.message;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return String(error);
}

function readJsonSafe(filePath, fallback) {
  try {
    return JSON.parse(fs.readFileSync(filePath, "utf8"));
  } catch (error) {
    return fallback;
  }
}

function writeJson(filePath, data) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, JSON.stringify(data, null, 2), "utf8");
}

function loadState(filePath) {
  const state = readJsonSafe(filePath, { version: 1, accounts: {} });
  return {
    version: 1,
    accounts: state && typeof state.accounts === "object" && state.accounts ? state.accounts : {},
  };
}

function getCachedDeviceCode(state, username) {
  const key = normalizeAccountKey(username);
  return String(state?.accounts?.[key]?.deviceCode || "").trim();
}

function setCachedDeviceCode(state, username, deviceCode) {
  const key = normalizeAccountKey(username);
  if (!state.accounts || typeof state.accounts !== "object") {
    state.accounts = {};
  }
  state.accounts[key] = {
    ...(state.accounts[key] || {}),
    deviceCode: String(deviceCode),
    updatedAt: new Date().toISOString(),
  };
}

function getCachedAuth(state, username) {
  const key = normalizeAccountKey(username);
  const auth = state?.accounts?.[key]?.auth;
  if (!auth || typeof auth !== "object") {
    return null;
  }
  if (!auth.tenantId || !auth.userId || !auth.secretKey) {
    return null;
  }
  return {
    tenantId: auth.tenantId,
    userId: auth.userId,
    secretKey: auth.secretKey,
    userAccount: auth.userAccount || "",
    userName: auth.userName || "",
    bondedDevice: auth.bondedDevice,
    timestamp: auth.timestamp || "",
  };
}

function setCachedAuth(state, username, auth) {
  const key = normalizeAccountKey(username);
  if (!state.accounts || typeof state.accounts !== "object") {
    state.accounts = {};
  }
  state.accounts[key] = {
    ...(state.accounts[key] || {}),
    auth: {
      tenantId: auth.tenantId,
      userId: auth.userId,
      secretKey: auth.secretKey,
      userAccount: auth.userAccount || "",
      userName: auth.userName || "",
      bondedDevice: auth.bondedDevice,
      timestamp: auth.timestamp || "",
      updatedAt: new Date().toISOString(),
    },
  };
}

function clearCachedAuth(state, username) {
  const key = normalizeAccountKey(username);
  if (!state.accounts || !state.accounts[key]) {
    return;
  }
  delete state.accounts[key].auth;
  state.accounts[key].updatedAt = new Date().toISOString();
}

function parseAccounts(raw) {
  return raw
    .split("&")
    .map((item) => item.trim())
    .filter(Boolean)
    .map((item, index) => {
      const splitIndex = item.indexOf("#");
      if (splitIndex <= 0 || splitIndex === item.length - 1) {
        throw new Error(`第 ${index + 1} 组账号格式不正确，应为 账号#密码。`);
      }
      const username = item.slice(0, splitIndex).trim();
      const password = item.slice(splitIndex + 1).trim();
      if (!username || !password) {
        throw new Error(`第 ${index + 1} 组账号格式不正确，应为 账号#密码。`);
      }
      return { username, password };
    });
}

function buildDeviceCode(username) {
  const digest = crypto
    .createHash("md5")
    .update(`ctyun_phone_keepalive_lite:${String(username).toLowerCase()}`)
    .digest("hex");
  return `android_phone_${digest}`;
}

function isCaptchaCode(code) {
  return [
    API_CODES.NEED_CAPTCHA,
    API_CODES.INVALID_CAPTCHA,
    API_CODES.EXPIRE_CAPTCHA,
    API_CODES.ERROR_CAPTCHA,
  ].includes(Number(code));
}

function buildQueryString(params) {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params || {})) {
    if (value !== undefined && value !== null && value !== "") {
      search.set(key, String(value));
    }
  }
  return search;
}

function buildFormBody(params) {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params || {})) {
    if (value !== undefined && value !== null) {
      search.set(key, String(value));
    }
  }
  return search;
}

class CtyunPhoneKeepAliveLite {
  constructor(account, config) {
    this.account = account;
    this.config = config;
    this.maskedAccount = maskAccount(account.username);
    this.deviceCode = "";
    this.requestIdCounter = 0;
    this.auth = null;
    this.desktops = [];
    this.abortControllers = new Set();
    this.wsConnections = new Set();
  }

  async run() {
    const summary = {
      ok: false,
      maskedAccount: this.maskedAccount,
      total: 0,
      success: 0,
      failed: 0,
      error: null,
    };

    try {
      this.deviceCode = this.#resolveDeviceCode();
      line("[设备]", this.deviceCode);

      this.auth = await this.#ensureAuth();
      line("[登录]", "认证完成");
      line("[租户]", this.auth.tenantId);
      line("[用户]", this.auth.userId);

      this.desktops = await this.#getDesktopList();
      if (this.desktops.length === 0) {
        throw new Error("没有可用的云手机实例");
      }

      line("[桌面]", `共 ${this.desktops.length} 台`);
      for (const desktop of this.desktops) {
        line("  -", `${desktop.desktopName} (${desktop.desktopId}) - ${desktop.state}`);
      }

      summary.total = this.desktops.length;

      // 对每台桌面进行轻量级保活
      for (const desktop of this.desktops) {
        try {
          await this.#keepaliveDesktop(desktop);
          summary.success += 1;
          line("[保活]", `${desktop.desktopName} 成功`);
        } catch (error) {
          summary.failed += 1;
          line("[保活]", `${desktop.desktopName} 失败: ${shorten(buildErrorMessage(error), 100)}`);
        }
      }

      summary.ok = summary.failed === 0 && summary.success > 0;
    } catch (error) {
      summary.error = error;
      line("[错误]", shorten(buildErrorMessage(error), 150));
    } finally {
      await this.#cleanup();
    }

    return summary;
  }

  #resolveDeviceCode() {
    const cached = getCachedDeviceCode(this.config.state, this.account.username);
    if (cached) {
      return cached;
    }
    const deviceCode = buildDeviceCode(this.account.username);
    setCachedDeviceCode(this.config.state, this.account.username, deviceCode);
    writeJson(this.config.stateFile, this.config.state);
    return deviceCode;
  }

  async #ensureAuth() {
    const cached = getCachedAuth(this.config.state, this.account.username);
    if (cached) {
      try {
        await this.#getDesktopList(cached);
        return cached;
      } catch (error) {
        if (error instanceof ApiError && error.auth) {
          clearCachedAuth(this.config.state, this.account.username);
          writeJson(this.config.stateFile, this.config.state);
        } else {
          throw error;
        }
      }
    }

    return await this.#login();
  }

  async #login() {
    let captchaCode = "";
    let lastError = null;

    for (let attempt = 1; attempt <= this.config.maxCaptchaRetries; attempt += 1) {
      try {
        // 获取 challenge 数据
        const challenge = await this.#getChallengeData();
        const challengeId = String(challenge?.challengeId ?? challenge?.id ?? "").trim();
        const challengeCode = String(
          challenge?.challengeCode ?? challenge?.code ?? challenge?.challenge ?? ""
        ).trim();

        if (!captchaCode) {
          captchaCode = await this.#recognizeCaptcha();
        }

        // 密码加密：与现有脚本一致
        const plainSha256 = sha256(this.account.password);
        const payload = {
          userAccount: this.account.username,
          password: challengeCode
            ? sha256(`${this.account.password}${challengeCode}`)
            : plainSha256,
          sha256Password: challengeCode
            ? sha256(`${plainSha256}${challengeCode}`)
            : plainSha256,
          challengeId,
          deviceCode: this.deviceCode,
          deviceName: this.config.deviceName,
          deviceType: String(this.config.deviceType),
          deviceModel: this.config.deviceModel,
          appVersion: this.config.appVersion,
          sysVersion: this.config.sysVersion,
          clientVersion: String(this.config.version),
        };

        if (captchaCode) {
          payload.captchaCode = captchaCode;
        }

        // 转换为 form-urlencoded 格式
        const formBody = new URLSearchParams();
        for (const [key, value] of Object.entries(payload)) {
          if (value !== undefined && value !== null) {
            formBody.set(key, String(value));
          }
        }

        const result = await this.#request({
          method: "POST",
          pathname: "/api/auth/client/login",
          body: formBody.toString(),
          contentType: "application/x-www-form-urlencoded",
          auth: false,
        });

        const auth = {
          tenantId: String(result.tenantId || ""),
          userId: String(result.userId || ""),
          secretKey: String(result.secretKey || ""),
          userAccount: String(result.userAccount || this.account.username),
          userName: String(result.userName || ""),
          bondedDevice: Boolean(result.bondedDevice),
          timestamp: String(result.timestamp || ""),
        };

        if (!auth.tenantId || !auth.userId || !auth.secretKey) {
          throw new Error("登录结果缺少必要的认证信息");
        }

        setCachedAuth(this.config.state, this.account.username, auth);
        writeJson(this.config.stateFile, this.config.state);

        if (!auth.bondedDevice) {
          await this.#bindDevice(auth);
          auth.bondedDevice = true;
          setCachedAuth(this.config.state, this.account.username, auth);
          writeJson(this.config.stateFile, this.config.state);
        }

        return auth;
      } catch (error) {
        lastError = error;

        if (error instanceof ApiError) {
          if (error.code === API_CODES.INVALID_PASSWORD || error.code === API_CODES.NO_PERMISSIONS) {
            throw error;
          }

          if (isCaptchaCode(error.code)) {
            captchaCode = "";
            if (error.code === API_CODES.EXPIRE_CAPTCHA || error.code === API_CODES.NEED_CAPTCHA) {
              challengeId = "";
            }
            line("[验证码]", `第 ${attempt} 次识别失败，重试中`);
            await sleep(500);
            continue;
          }

          if (error.code === API_CODES.AUTH_LOCKED) {
            throw new Error("账号已被锁定，请稍后再试");
          }
        }

        throw error;
      }
    }

    throw lastError || new Error("登录失败");
  }

  async #getChallengeData() {
    try {
      return await this.#request({
        method: "POST",
        pathname: "/api/auth/client/genChallengeData",
        auth: false,
      });
    } catch (error) {
      return null;
    }
  }

  async #recognizeCaptcha() {
    const imageBuffer = await this.#getCaptchaImage();
    return await this.#ocrCaptcha(imageBuffer);
  }

  async #getCaptchaImage() {
    const userInfo = encodeURIComponent(this.account.username);
    const result = await this.#request({
      method: "GET",
      pathname: `/api/auth/client/captcha?height=36&width=85&userInfo=${userInfo}`,
      auth: false,
      responseType: "arrayBuffer",
    });
    return Buffer.from(result);
  }

  async #ocrCaptcha(imageBuffer) {
    const url = `${this.config.ocrServer.replace(/\/+$/, "")}/classification`;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.config.requestTimeoutMs);

    let response;
    try {
      response = await fetch(url, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          image: imageBuffer.toString("base64"),
        }),
        signal: controller.signal,
      });
    } finally {
      clearTimeout(timer);
    }

    const raw = await response.text();
    let data = null;
    try {
      data = JSON.parse(raw);
    } catch (error) {
      data = raw;
    }

    if (typeof data === "string") {
      const result = data.replace(/\s+/g, "").trim();
      if (!result) {
        throw new Error("OCR 接口返回为空。");
      }
      return result;
    }

    const result = String(
      data.result ?? data.data ?? data.text ?? data.codeResult ?? ""
    )
      .replace(/\s+/g, "")
      .trim();

    if (!response.ok) {
      throw new Error(`OCR 接口 HTTP ${response.status}: ${raw.substring(0, 200)}`);
    }
    if (!result) {
      throw new Error(`OCR 识别结果为空: ${raw.substring(0, 200)}`);
    }

    return result;
  }

  async #bindDevice(auth) {
    const verificationCode = "103020001";
    const params = {
      verificationCode,
      deviceName: this.config.deviceName,
      deviceCode: this.deviceCode,
      deviceModel: this.config.deviceModel,
      sysVersion: this.config.sysVersion,
      appVersion: this.config.appVersion,
      hostName: "pc.ctyun.cn",
      deviceInfo: "Win32",
    };

    await this.#request({
      method: "POST",
      pathname: `/api/cdserv/client/device/binding?${buildQueryString(params)}`,
      auth: true,
      authContext: auth,
    });
  }

  async #getDesktopList(authContext = null) {
    const result = await this.#request({
      method: "GET",
      pathname: "/api/desktop/client/list",
      auth: true,
      authContext,
    });

    if (this.config.debug) {
      line("[调试]", `桌面列表原始数据: ${JSON.stringify(result, null, 2).substring(0, 500)}`);
    }

    const desktops = Array.isArray(result?.desktopList) ? result.desktopList : [];
    return desktops
      .filter((item) => item && item.desktopId)
      .map((item) => ({
        desktopId: String(item.desktopId),
        desktopName: String(item.desktopName || item.desktopId),
        state: String(item.state || "UNKNOWN"),
        serviceTicket: String(item.serviceTicket || ""),
        clinkLvsOutHost: String(item.clinkLvsOutHost || ""),
        clinkLvsOutPort: String(item.clinkLvsOutPort || item.clinkLvsPort || "9011"),
      }));
  }

  async #keepaliveDesktop(desktop) {
    const startTime = Date.now();
    const duration = this.config.keepaliveDurationMs;
    const interval = this.config.heartbeatIntervalMs;

    line("[心跳]", `开始保活 ${desktop.desktopName}，时长 ${duration / 1000} 秒`);

    // 建立 MAIN 通道 WebSocket 连接
    const wsUrl = await this.#getWebSocketUrl(desktop, "MAIN");
    const ws = await this.#connectWebSocket(wsUrl);

    try {
      while (Date.now() - startTime < duration) {
        // 发送心跳
        await this.#sendHeartbeat(ws);
        await sleep(interval);
      }
    } finally {
      ws.close();
      this.wsConnections.delete(ws);
    }

    line("[心跳]", `保活完成 ${desktop.desktopName}`);
  }

  async #getWebSocketUrl(desktop, channel) {
    // 使用默认的 clink WebSocket 地址
    // 格式: wss://deskmsgz.ctyun.cn:9011/clinkProxy/{desktopId}
    const host = "deskmsgz.ctyun.cn";
    const port = "9011";
    const url = `wss://${host}:${port}/clinkProxy/${desktop.desktopId}`;
    
    if (this.config.debug) {
      line("[调试]", `WebSocket URL: ${url}`);
    }
    
    return url;
  }

  async #connectWebSocket(url) {
    return new Promise((resolve, reject) => {
      // 尝试不同的 WebSocket 连接方式
      let ws;
      try {
        // Node.js ws 库支持 headers
        ws = new WebSocketImpl(url, "binary", {
          headers: {
            "User-Agent": this.config.userAgent,
            "Origin": "https://pc.ctyun.cn",
            "CTG-TENANTID": this.auth.tenantId,
            "CTG-USERID": this.auth.userId,
          },
        });
      } catch (e) {
        // 浏览器 WebSocket 不支持 headers
        ws = new WebSocketImpl(url, "binary");
      }

      if ("binaryType" in ws) {
        ws.binaryType = "arraybuffer";
      }

      const timeout = setTimeout(() => {
        try { ws.close(); } catch {}
        reject(new Error("WebSocket 连接超时"));
      }, this.config.requestTimeoutMs);

      ws.onopen = () => {
        clearTimeout(timeout);
        this.wsConnections.add(ws);
        resolve(ws);
      };

      ws.onerror = (error) => {
        clearTimeout(timeout);
        const errMsg = error.message || error.type || "unknown";
        reject(new Error(`WebSocket 连接失败: ${errMsg}`));
      };

      ws.onclose = (event) => {
        this.wsConnections.delete(ws);
      };
    });
  }

  async #sendHeartbeat(ws) {
    if (ws.readyState !== WS_READY_STATE_OPEN) {
      throw new Error("WebSocket 未连接");
    }

    // 发送 PING 消息（type=4）
    const pingMessage = this.#buildClinkMessage(4, Buffer.alloc(0));
    ws.send(pingMessage);

    if (this.config.debug) {
      line("[心跳]", "发送 PING");
    }
  }

  #buildClinkMessage(type, payload) {
    // 简化的 clink 消息格式
    // type(1) + version(1) + reserved(2) + payloadLength(4) + payload
    const header = Buffer.alloc(8);
    header.writeUInt8(type, 0);
    header.writeUInt8(1, 1); // version
    header.writeUInt16BE(0, 2); // reserved
    header.writeUInt32BE(payload.length, 4);
    
    return Buffer.concat([header, payload]);
  }

  async #request(options) {
    const {
      method,
      pathname,
      body,
      contentType,
      auth,
      authContext,
      responseType = "json",
    } = options;

    const url = `${API_HOST}${pathname}`;
    const timestamp = Date.now();
    const requestId = this.#nextRequestId();

    const headers = {
      "User-Agent": this.config.userAgent,
      "Accept": "application/json, text/plain, */*",
      "Referer": "https://pc.ctyun.cn/",
      "Origin": "https://pc.ctyun.cn",
      "CTG-REQUESTID": requestId,
      "CTG-TIMESTAMP": String(timestamp),
      "CTG-DEVICETYPE": String(this.config.deviceType),
      "CTG-DEVICECODE": this.deviceCode,
      "CTG-VERSION": String(this.config.version),
      "CTG-APPVERSION": this.config.appVersion,
    };

    if (contentType) {
      headers["Content-Type"] = contentType;
    }

    if (auth) {
      const authData = authContext || this.auth;
      if (!authData) {
        throw new Error("缺少认证信息");
      }

      headers["CTG-TENANTID"] = authData.tenantId;
      headers["CTG-USERID"] = authData.userId;
      headers["CTG-USERACCOUNT"] = authData.userAccount || "";
      headers["CTG-USERNAME"] = authData.userName || "";

      const signature = this.#computeSignature({
        deviceType: this.config.deviceType,
        requestId,
        tenantId: authData.tenantId,
        timestamp,
        userId: authData.userId,
        version: this.config.version,
        secretKey: authData.secretKey,
      });

      headers["CTG-SIGNATURESTR"] = signature;
    }

    let lastError = null;
    for (let attempt = 0; attempt <= this.config.networkRetryCount; attempt += 1) {
      const controller = this.#createAbortSignal(this.config.requestTimeoutMs);

      try {
        const response = await fetch(url, {
          method,
          headers,
          body,
          signal: controller,
        });

        // 二进制响应直接返回
        if (responseType === "arrayBuffer") {
          if (!response.ok) {
            const raw = await response.text();
            throw new Error(`HTTP ${response.status}: ${raw.substring(0, 200)}`);
          }
          return Buffer.from(await response.arrayBuffer());
        }

        const text = await response.text();

        if (!response.ok) {
          throw new Error(`HTTP ${response.status}: ${text}`);
        }

        const payload = text ? JSON.parse(text) : {};
        const code = Number(payload.code ?? response.status);
        const msg = String(payload.msg || payload.message || "").trim();
        const success = payload.success ?? (response.ok && (code === 0 || code === 200));

        if (!success) {
          throw new ApiError(msg || `请求失败: ${code}`, code, payload, {
            method,
            pathname,
            auth,
          });
        }

        return payload.data !== undefined ? payload.data : payload;
      } catch (error) {
        lastError = error;

        if (error instanceof ApiError) {
          throw error;
        }

        if (attempt < this.config.networkRetryCount) {
          await sleep(this.config.networkRetryDelayMs);
          continue;
        }

        throw error;
      }
    }

    throw lastError || new Error("请求失败");
  }

  #computeSignature(params) {
    const { deviceType, requestId, tenantId, timestamp, userId, version, secretKey } = params;
    const raw = `${deviceType}${requestId}${tenantId}${timestamp}${userId}${version}${secretKey}`;
    return md5Upper(raw);
  }

  #nextRequestId() {
    this.requestIdCounter += 1;
    const timestamp = Date.now();
    const random = Math.floor(Math.random() * 100000);
    return `${timestamp}${this.requestIdCounter.toString().padStart(4, "0")}${random}`;
  }

  #createAbortSignal(timeoutMs) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), timeoutMs);
    this.abortControllers.add(controller);
    return controller.signal;
  }

  async #cleanup() {
    for (const controller of this.abortControllers) {
      controller.abort();
    }
    this.abortControllers.clear();

    for (const ws of this.wsConnections) {
      try {
        ws.close();
      } catch {}
    }
    this.wsConnections.clear();
  }
}

function buildConfig() {
  const accountsRaw = readEnv("CTYUN_PHONE_ACCOUNTS", "CTYUN_ACCOUNTS");
  if (!accountsRaw) {
    throw new Error("请设置环境变量 CTYUN_PHONE_ACCOUNTS 或 CTYUN_ACCOUNTS");
  }

  const ocrServer = readEnv("OCR_SERVER");
  if (!ocrServer) {
    throw new Error("请设置 OCR_SERVER，指向 ddddocr 服务地址。");
  }

  const stateFile = path.resolve(
    readEnv("CTYUN_STATE_FILE") || path.join(__dirname, "ctyun_state_lite.json")
  );

  return {
    ocrServer,
    accounts: parseAccounts(accountsRaw),
    stateFile,
    state: loadState(stateFile),
    appModel: DEFAULTS.appModel,
    deviceType: DEFAULTS.deviceType,
    osType: DEFAULTS.osType,
    appVersion: DEFAULTS.appVersion,
    version: DEFAULTS.version,
    deviceName: DEFAULTS.deviceName,
    deviceModel: DEFAULTS.deviceModel,
    sysVersion: DEFAULTS.sysVersion,
    userAgent: DEFAULTS.userAgent,
    requestTimeoutMs: readIntEnv("CTYUN_REQUEST_TIMEOUT_MS", DEFAULTS.requestTimeoutMs),
    networkRetryCount: readIntEnv("CTYUN_NETWORK_RETRY_COUNT", DEFAULTS.networkRetryCount),
    networkRetryDelayMs: readIntEnv(
      "CTYUN_NETWORK_RETRY_DELAY_MS",
      DEFAULTS.networkRetryDelayMs
    ),
    heartbeatIntervalMs: readIntEnv(
      "CTYUN_HEARTBEAT_INTERVAL",
      DEFAULTS.heartbeatIntervalMs
    ),
    keepaliveDurationMs: readIntEnv(
      "CTYUN_KEEPALIVE_DURATION",
      DEFAULTS.keepaliveDurationMs
    ),
    maxCaptchaRetries: readIntEnv(
      "CTYUN_MAX_CAPTCHA_RETRIES",
      DEFAULTS.maxCaptchaRetries
    ),
    debug: readBoolEnv("CTYUN_DEBUG", DEFAULTS.debug),
  };
}

async function main() {
  const startedAt = nowText();
  const config = buildConfig();

  section("天翼云手机无感保活（不顶号版本）");
  line("[开始]", startedAt);
  line("[账号]", `共 ${config.accounts.length} 个账号`);
  line("[心跳间隔]", `${config.heartbeatIntervalMs / 1000} 秒`);
  line("[保活时长]", `${config.keepaliveDurationMs / 1000} 秒`);

  const summaries = [];

  for (let index = 0; index < config.accounts.length; index += 1) {
    const account = config.accounts[index];
    const masked = maskAccount(account.username);

    section(`账号 ${index + 1}/${config.accounts.length}  ${masked}`);

    try {
      const runner = new CtyunPhoneKeepAliveLite(account, config);
      const summary = await runner.run();
      summaries.push(summary);
    } catch (error) {
      line("[小结]", `${masked} 执行失败: ${shorten(buildErrorMessage(error), 150)}`);
      summaries.push({
        ok: false,
        maskedAccount: masked,
        total: 0,
        success: 0,
        failed: 0,
        error,
      });
    }
  }

  const totalAccounts = summaries.length;
  const okAccounts = summaries.filter((item) => item.ok).length;
  const totalDevices = summaries.reduce((sum, item) => sum + (item.total || 0), 0);
  const successDevices = summaries.reduce((sum, item) => sum + (item.success || 0), 0);
  const failedDevices = summaries.reduce((sum, item) => sum + (item.failed || 0), 0);

  section("执行汇总");
  line("[结束]", nowText());
  line("[账号]", `成功 ${okAccounts} 个，失败 ${totalAccounts - okAccounts} 个，共 ${totalAccounts} 个`);
  line("[设备]", `成功 ${successDevices} 台，失败 ${failedDevices} 台，共 ${totalDevices} 台`);

  const failedAccounts = summaries.filter((item) => !item.ok);
  if (failedAccounts.length > 0) {
    line("[异常]", "以下账号未全部成功:");
    for (const item of failedAccounts) {
      const reason = item.error ? shorten(buildErrorMessage(item.error), 120) : "存在失败设备";
      line("  -", `${item.maskedAccount} -> ${reason}`);
    }
    process.exitCode = 1;
    return;
  }

  line("[结果]", "全部账号保活完成（无感模式，不顶号）");
}

main().catch((error) => {
  section("执行失败");
  line("[时间]", nowText());
  line("[原因]", buildErrorMessage(error));
  process.exit(1);
});
