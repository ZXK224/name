"""
# name: 移动云盘16号抢兑
移动云盘 · 16号会员日 v1.1.0 (YYB 版)

功能范围:
1. 盲盒自动抽奖  blindbox/lottery  —— 循环抽到无次数为止
2. 中奖记录查询  getUserPrizeLogPage —— 只读展示本期已抽到的奖品
3. 奖品列表查询  gift/list —— 展示可抢兑商品(prizeType==1 需钻石会员)
4. 自动抢兑      getSmsCode -> receive —— 抢兑所有普通奖品(跳过钻石会员专属)

鉴权链路(YYB Go):
  与「移动云盘商品抢兑_yyb.py」一致:
    1) POST {wx_server_url}/wxapp/getCode  body={app_id:wx4e4ed37286c816c2, ref:1}
    2) POST https://user-njs.yun.139.com/user/thirdlogin   AES 加解密换 (account, authToken)
    3) 拼成 Authorization=Basic base64("mobile:{account}:{authToken}")
    4) POST orches.yun.139.com querySpecToken → JWT → 调抽奖/记录/奖品/抢兑

环境变量:
  wx_server_url     YYB Go 服务地址 (默认 http://192.168.3.182:18001)
  move16_ref        微信 ref 列表, & 分隔 (默认 1&4&7&8&9&11, 同云盘抢兑 6 号)
  mcloudday_confirm "1"/"true" = 真实抢兑, 其它/不设 = 测试模式(仅打印)
  BARK_PUSH         Bark 推送 URL (如 https://api.day.app/xxxx/)

依赖: pip3 install requests pycryptodome

Author: xiaohai (原脚本) / 重构适配YYB Go: 2026.08.26
"""

import base64
import json
import os
import random
import re
import time

import requests

# AES 加解密（_yyb_login 用到）
try:
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import pad, unpad
    _HAS_CRYPTO = True
except ImportError:
    AES = None
    _HAS_CRYPTO = False

SCRIPT_VERSION = '1.1.0'

# ==================== YYB 鉴权配置 ====================
APPID_QD = "wx4e4ed37286c816c2"
WX_SERVER_URL = os.getenv("wx_server_url", "http://192.168.3.182:18001").rstrip("/")
MOVE16_REF = os.getenv("move16_ref", "1&4&7&8&9&11")
BARK_PUSH = os.getenv("BARK_PUSH", "")

MP_VERSION = '5.14.2'
MP_WX_OA_CLIENT_TYPE = '821'
MP_WX_OA_CPID = '443'
MP_COOL_FLAG_KEY = 'taNk805XxEM4uDWvVTMo+BVe'
MP_USER_ZONE_KEY = 'qPqDw263XgFgL3u8'
THIRDLOGIN_URL = 'https://user-njs.yun.139.com/user/thirdlogin'
MINI_PROGRAM_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.47(0x18002f2c) "
    "NetType/WIFI Language/zh_CN miniProgram/wx4e4ed37286c816c2"
)

# ==================== 16号会员日业务常量 ====================
MARKET_NAME = 'National_MCloudDay'
SOURCE_ID = '1000'
BASE_URL = 'https://caiyun.feixin.10086.cn:7071'
REFERER = (f'{BASE_URL}/portal/cloudCircle/index.html'
           f'?path=mCloudDay&sourceid={SOURCE_ID}&enableShare=1')

MAX_LOTTERY_TIMES = 30

UA = ('Mozilla/5.0 (Linux; Android 13; 23049RAD8C Build/TKQ1.221114.001; wv) '
      'AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/108.0.5359.128 '
      'Mobile Safari/537.36 MCloudApp/12.4.0 AppLanguage/zh-CN')


# ==================== YYB Go 登录链路 ====================

def _yyb_direct_session():
    s = requests.Session()
    s.trust_env = False
    return s


def _random_string(length=16):
    chars = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
    return ''.join(random.choice(chars) for _ in range(length))


def _mp_aes_encrypt(data, key):
    """小程序 verifyModal/utils.aesEncrypt：AES-CBC，随机 16 位 IV 前置，base64(IV||密文)"""
    iv = _random_string(16).encode('utf-8')
    if not isinstance(data, str):
        data = json.dumps(data, ensure_ascii=False, separators=(',', ':'))
    cipher = AES.new(key.encode('utf-8'), AES.MODE_CBC, iv)
    encrypted = cipher.encrypt(pad(data.encode('utf-8'), AES.block_size))
    return base64.b64encode(iv + encrypted).decode('utf-8')


def _mp_aes_decrypt(data, key):
    """小程序 verifyModal/utils.aesDecrypt：base64(IV||密文) -> 明文"""
    raw = base64.b64decode(data)
    iv, encrypted = raw[:16], raw[16:]
    cipher = AES.new(key.encode('utf-8'), AES.MODE_CBC, iv)
    return unpad(cipher.decrypt(encrypted), AES.block_size).decode('utf-8')


def _mp_aes_ecb_decrypt_hex(hex_data, key):
    """小程序 modules/login/util.aesECBDecryptHex：hex -> AES-ECB 解密"""
    raw = bytes.fromhex(hex_data)
    cipher = AES.new(key.encode('utf-8'), AES.MODE_ECB)
    return unpad(cipher.decrypt(raw), AES.block_size).decode('utf-8')


def _build_thirdlogin_payload(code):
    return {
        'clienttype': MP_WX_OA_CLIENT_TYPE,
        'version': MP_VERSION,
        'cpid': MP_WX_OA_CPID,
        'dycpwd': code,
        'pintype': '4',
        'loginMode': '0',
        'extInfo': {
            'ifOpenAccount': '0',
            'wcOfficeAccountSec': base64.b64encode(f'code={code}'.encode('utf-8')).decode('utf-8'),
        },
    }


def _build_thirdlogin_headers():
    return {
        'Content-Type': 'application/json; charset=UTF-8',
        'User-Agent': MINI_PROGRAM_UA,
        'Referer': f'https://servicewechat.com/{APPID_QD}/page-frame.html',
        'Accept': '*/*',
        'Accept-Language': 'zh-CN,zh;q=0.9',
        'x-huawei-channelSrc': '10236800',
        'x-inner-ntwk': '2',
        'x-NetType': '',
        'x-DeviceInfo': f'||8|{MP_VERSION}|iPhone|iPhone|{_random_string(32)}||ios|||||',
        'mcloud-channel': '1000101',
        'mcloud-client': '10801',
        'mcloud-version': MP_VERSION,
        'mcloud-network': '',
        'mcloud-skey': '',
        'x-yun-client-info': '||8||||||||||||',
        'INNER-HCY-ROUTER-HTTPS': '1',
        'x-yun-tid': _random_string(32),
        'hcy-cool-flag': '1',
    }


def _build_authorization(account, raw_token):
    return f"Basic {base64.b64encode(f'mobile:{account}:{raw_token}'.encode()).decode()}"


def _yyb_get_code(ref):
    """通过 YYB Go 的 /wxapp/getCode 接口获取微信 code"""
    if not WX_SERVER_URL:
        print("❌ [授权] 未配置 wx_server_url 环境变量")
        return None
    try:
        resp = _yyb_direct_session().post(
            f"{WX_SERVER_URL}/wxapp/getCode",
            json={"app_id": APPID_QD, "ref": ref},
            timeout=30,
        )
        data = resp.json()
        if data.get("code") != 0 or not data.get("data"):
            print(f"❌ [授权] ref={ref} code 获取失败: {data}")
            return None
        inner = data.get("data", {})
        code_value = None
        if isinstance(inner, dict):
            result = inner.get("result", {})
            if isinstance(result, dict):
                code_value = result.get("code")
            if not code_value:
                code_value = inner.get("code")
        if not code_value:
            print(f"❌ [授权] ref={ref} 响应中未找到 code")
            return None
        return str(code_value)
    except Exception as exc:
        print(f"❌ [授权] ref={ref} 异常: {exc}")
        return None


def _yyb_login(code):
    """微信 code 换移动云盘 (account, authorization)"""
    if not _HAS_CRYPTO:
        print("❌ [登录] 缺 pycryptodome 依赖(请 pip3 install pycryptodome)")
        return None, None
    try:
        payload = _build_thirdlogin_payload(code)
        encrypted = _mp_aes_encrypt(payload, MP_COOL_FLAG_KEY)
        resp = _yyb_direct_session().post(
            THIRDLOGIN_URL,
            headers=_build_thirdlogin_headers(),
            data=encrypted,
            timeout=30,
        )
        try:
            resp_json = resp.json()
        except Exception:
            resp_json = None
        if not isinstance(resp_json, dict):
            try:
                resp_json = json.loads(_mp_aes_decrypt(resp.text, MP_COOL_FLAG_KEY))
            except Exception:
                resp_json = {"raw": resp.text[:800]}
        code_str = str(resp_json.get("code", ""))
        success = bool(resp_json.get("success", False)) or code_str in ("0", "00", "000", "0000")
        if not success or not resp_json.get("data"):
            print(f"❌ [登录] code 换 token 失败: {resp_json}")
            return None, None
        plain = _mp_aes_ecb_decrypt_hex(resp_json["data"], MP_USER_ZONE_KEY)
        login_info = json.loads(plain)
        account = str(login_info.get("account") or "").strip()
        if not account and login_info.get("encryptAccount"):
            try:
                account = base64.b64decode(str(login_info["encryptAccount"])).decode("utf-8")
            except Exception:
                account = ""
        auth_token = str(login_info.get("authToken") or "").strip()
        if not account or not auth_token:
            print(f"❌ [登录] 响应缺少账号或 authToken: {login_info}")
            return None, None
        authorization = _build_authorization(account, auth_token)
        print(f"✅ [登录] 成功: {account[:3]}****{account[-4]} authorization 已生成")
        return account, authorization
    except Exception as exc:
        print(f"❌ [登录] 异常: {exc}")
        return None, None


# ==================== 鉴权链路（移动云盘 → 16号会员日 JWT）====================

def query_spec_token(session, authorization, account, source_id='001005'):
    url = 'https://orches.yun.139.com/orchestration/auth-rebuild/token/v1.0/querySpecToken'
    headers = {
        'Authorization': authorization,
        'User-Agent': UA,
        'Content-Type': 'application/json',
        'Accept': '*/*',
        'Host': 'orches.yun.139.com',
    }
    payload = {'account': account, 'toSourceId': source_id}
    try:
        resp = session.post(url, headers=headers, json=payload, timeout=15)
        data = resp.json()
    except Exception as e:
        print(f'  获取specToken异常: {e}')
        return None
    if data.get('success'):
        return data['data']['token']
    print(f"  获取specToken失败: {data.get('message', '未知错误')}")
    return None


def fetch_jwt_token(session, authorization, account):
    sso_token = query_spec_token(session, authorization, account)
    if not sso_token:
        return None
    jwt_url = f'{BASE_URL}/portal/auth/tyrzLogin.action?ssoToken={sso_token}'
    jwt_headers = {
        'User-Agent': UA,
        'Accept': '*/*',
        'Host': 'caiyun.feixin.10086.cn:7071',
    }
    try:
        resp = session.post(jwt_url, headers=jwt_headers, timeout=15)
        data = resp.json()
    except Exception as e:
        print(f'  JWT获取异常: {e}')
        return None
    if data.get('code') != 0:
        print(f"  JWT获取失败: {data.get('msg', '未知错误')}")
        return None
    return data['result']['token']


# ==================== 业务请求封装 ====================

def build_headers(jwt_token, post=False):
    headers = {
        'Host': 'caiyun.feixin.10086.cn:7071',
        'User-Agent': UA,
        'Accept-Encoding': 'gzip, deflate',
        'jwttoken': jwt_token,
        'x-requested-with': 'com.chinamobile.mcloud',
        'sec-fetch-site': 'same-origin',
        'sec-fetch-mode': 'cors',
        'sec-fetch-dest': 'empty',
        'referer': REFERER,
        'accept-language': 'zh,zh-CN;q=0.9,en-US;q=0.8,en;q=0.7',
    }
    if post:
        headers['content-type'] = 'application/json;charset=UTF-8'
        headers['origin'] = BASE_URL
        headers['showloading'] = 'true'
    return headers


def market_request(session, url, jwt_token, method='GET', params=None, payload=None):
    """统一发起会员日请求并返回解析后的 JSON(失败返回 None)"""
    try:
        if method == 'POST':
            resp = session.post(url, headers=build_headers(jwt_token, post=True),
                                data=json.dumps(payload or {}), timeout=20)
        else:
            resp = session.get(url, headers=build_headers(jwt_token),
                               params=params, timeout=20)
        return resp.json()
    except Exception as e:
        print(f'  请求异常 {url}: {e}')
        return None


def is_success(data):
    """通用成功判断: 兼容 code/status/success 多种字段"""
    if not isinstance(data, dict):
        return False
    if data.get('success') is True:
        return True
    for key in ('code', 'status'):
        if key in data:
            return str(data[key]) in ('0', '200')
    return False


def extract_prize_name(data):
    result = data.get('result') or data.get('data') or {}
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        return (result.get('prizeName') or result.get('giftName')
                or result.get('name') or result.get('desc') or '')
    return ''


def extract_message(data):
    for key in ('msg', 'message', 'respMsg', 'errMsg', 'desc'):
        if isinstance(data, dict) and data.get(key):
            return str(data[key])
    return ''


# ==================== 抽奖 / 中奖记录 / 奖品列表 ====================

def do_lottery(session, jwt_token, logs):
    """盲盒抽奖: 循环抽到无次数为止。"""
    url = f'{BASE_URL}/ycloud/mcloudday/blindbox/lottery'
    logs.append('\n🎁 盲盒抽奖')
    win_count = 0
    prize_counter = {}
    for i in range(1, MAX_LOTTERY_TIMES + 1):
        data = market_request(session, url, jwt_token, method='POST', payload={'client': '1'})
        if data is None:
            logs.append(f'-第{i}次: 接口无响应, 停止')
            break
        if i == 1:
            print(f'  [首次抽奖原始响应] {json.dumps(data, ensure_ascii=False)}')
        if is_success(data):
            prize_name = extract_prize_name(data)
            prize_counter[prize_name] = prize_counter.get(prize_name, 0) + 1
            win_count += 1
            time.sleep(random.uniform(1.0, 2.0))
            continue
        msg = extract_message(data) or '无更多次数'
        logs.append(f'-停止原因: {msg}')
        break
    for name, count in prize_counter.items():
        logs.append(f'-{name or "未知奖品"} x{count}')
    logs.append(f'-累计抽奖 {win_count} 次')


def query_prize_log(session, jwt_token, logs):
    """中奖记录(只读)"""
    url = f'{BASE_URL}/market/prizeApi/checkPrize/getUserPrizeLogPage'
    params = {'marketName': MARKET_NAME, 'currPage': '1', 'pageSize': '1000'}
    data = market_request(session, url, jwt_token, method='GET', params=params)
    logs.append('\n📜 中奖记录')
    if not data or not is_success(data):
        logs.append(f'-查询失败: {extract_message(data) if data else "接口无响应"}')
        return
    result = data.get('result') or data.get('data') or {}
    records = []
    if isinstance(result, dict):
        records = result.get('list') or result.get('records') or result.get('items') or []
    elif isinstance(result, list):
        records = result
    if not records:
        logs.append('-暂无中奖记录')
        return
    for idx, rec in enumerate(records, start=1):
        if not isinstance(rec, dict):
            continue
        name = rec.get('prizeName') or rec.get('giftName') or rec.get('name') or '未知奖品'
        t = rec.get('createTime') or rec.get('time') or rec.get('drawTime') or ''
        logs.append(f'-{idx}. {name} {t}'.rstrip())


def fetch_gift_list(session, jwt_token):
    """取奖品列表原始数据(纯数据, 不打印); 失败返回 (None, 错误信息)。"""
    url = f'{BASE_URL}/ycloud/mcloudday/gift/list'
    data = market_request(session, url, jwt_token, method='GET')
    if not data or not is_success(data):
        return None, (extract_message(data) if data else '接口无响应')
    container = data.get('result') or data.get('data') or {}
    if not isinstance(container, dict):
        container = {}
    national = container.get('nationalPrizeList') or container.get('prizeList') or []
    prov = container.get('provPrizeList') or []
    return [g for g in (national + prov) if isinstance(g, dict)], ''


def gift_fields(g):
    """返回 (名称, prizeId, 是否需钻石会员, 是否有库存, 省份)。"""
    name = g.get('prizeName') or g.get('giftName') or g.get('name') or '未知'
    pid = g.get('prizeId') or g.get('id') or ''
    need_vip = str(g.get('prizeType', '')) == '1'
    has_stock = bool(g.get('hasStock'))
    prov = g.get('prov') or ''
    return name, pid, need_vip, has_stock, prov


def redeemable(g):
    """普通奖品(prizeType!=1) 且 有库存(hasStock)"""
    _, pid, need_vip, has_stock, _ = gift_fields(g)
    return bool(pid) and not need_vip and has_stock


def redeem_tag(g):
    """生成可抢兑状态标签(全部展示但标注)"""
    _, pid, need_vip, has_stock, _ = gift_fields(g)
    if not pid:
        return '缺ID'
    if need_vip and not has_stock:
        return '钻石·无货'
    if need_vip:
        return '钻石会员'
    if not has_stock:
        return '普通·无货'
    return '可抢'


def log_gift_list(gifts, logs):
    """展示全部奖品(可抢/不可抢都列出, 标注状态), 末尾汇总可抽数量"""
    logs.append('\n🛒 奖品列表(全部展示, 标注状态)')
    if gifts is None:
        logs.append('-查询失败')
        return
    if not gifts:
        logs.append('-暂无奖品')
        return
    redeem_count = 0
    for g in gifts:
        if not isinstance(g, dict):
            continue
        name, pid, _, _, prov = gift_fields(g)
        tag = redeem_tag(g)
        if redeemable(g):
            redeem_count += 1
        prov_str = f'[{prov}]' if prov else ''
        logs.append(f'-[{tag}]{prov_str} {name} (prizeId={pid})')
    logs.append(f'-共 {len(gifts)} 个奖品, 其中可抢 {redeem_count} 个')


def redeem_gifts(session, jwt_token, gifts, logs, confirm):
    """抢兑所有普通奖品(prizeType != 1)。"""
    logs.append('\n🎯 抢兑' + ('(测试模式, 未提交)' if not confirm else '(真实提交)'))
    if not gifts:
        logs.append('-无奖品可抢兑')
        return
    targets = [g for g in gifts if isinstance(g, dict) and redeemable(g)]
    if not targets:
        logs.append('-无可抢兑奖品(当前均为钻石专属/无库存/缺prizeId)')
        return
    if not confirm:
        for g in targets:
            name, pid, *_ = gift_fields(g)
            logs.append(f'-将抢兑: {name} (prizeId={pid})')
        logs.append(f'-待抢兑 {len(targets)} 个(测试模式未提交)')
        return
    ok_count, fail_count = 0, 0
    for g in targets:
        name, pid, *_ = gift_fields(g)
        success = redeem_one_gift(session, jwt_token, pid, name, logs)
        if success:
            ok_count += 1
        else:
            fail_count += 1
        time.sleep(random.uniform(1.5, 3.0))
    logs.append(f'-抢兑完成: 成功 {ok_count}, 失败 {fail_count}')


def get_sms_code(session, jwt_token, prize_id):
    """获取抢兑验证码(md5); 返回验证码字符串或 None"""
    url = f'{BASE_URL}/ycloud/mcloudday/gift/getSmsCode'
    data = market_request(session, url, jwt_token, method='POST', payload={'prizeId': prize_id})
    if not data:
        return None, '接口无响应'
    if not is_success(data):
        return None, extract_message(data) or '获取验证码失败'
    result = data.get('result') or data.get('data')
    if isinstance(result, str) and result:
        return result, ''
    if isinstance(result, dict):
        code = result.get('smsCode') or result.get('code') or result.get('msgCode')
        if code:
            return str(code), ''
    for key in ('smsCode', 'msgCode'):
        if data.get(key):
            return str(data[key]), ''
    return None, f'验证码字段未识别: {json.dumps(data, ensure_ascii=False)}'


def redeem_one_gift(session, jwt_token, prize_id, name, logs):
    """单个奖品抢兑: getSmsCode -> receive。返回是否成功。"""
    sms_code, err = get_sms_code(session, jwt_token, prize_id)
    if not sms_code:
        logs.append(f'-{name}: 取验证码失败({err})')
        return False
    time.sleep(random.uniform(0.8, 1.5))
    url = f'{BASE_URL}/ycloud/mcloudday/gift/receive'
    data = market_request(session, url, jwt_token, method='POST',
                          payload={'prizeId': prize_id, 'smsCode': sms_code})
    if not data:
        logs.append(f'-{name}: 抢兑接口无响应')
        return False
    if is_success(data):
        logs.append(f'-{name}: ✅抢兑成功')
        return True
    logs.append(f'-{name}: 抢兑失败({extract_message(data) or "未知"})')
    return False


# ==================== Bark 推送 ====================

def send_bark(title, body, group="移动云盘"):
    """直接 POST {server}/push，避开 notify.py.bark 走 GET 的空响应/431 问题。"""
    if not BARK_PUSH:
        print("[Bark] 未配置 BARK_PUSH，跳过推送")
        return False
    if not BARK_PUSH.startswith(("http://", "https://")):
        print(f"[Bark] BARK_PUSH 格式异常: {BARK_PUSH[:60]}")
        return False
    try:
        last = BARK_PUSH.rstrip("/").rsplit("/", 1)
        server = last[0]
        device_key = last[1] if len(last) == 2 else ""
    except Exception as e:
        print(f"[Bark] 解析 BARK_PUSH 失败: {e}")
        return False
    # Bark URL 形如 https://api.day.app/AwFVvu.../  → server=https://api.day.app, key=AwFVvu...
    url = f"{server}/push"
    payload = {
        "title": str(title)[:80],
        "body": str(body)[:1800],
        "group": group,
        "level": "active",
        "isArchive": 1,  # 强制归档，避免点开通知后消息消失
    }
    if device_key:
        payload["device_key"] = device_key
    try:
        resp = requests.post(url, json=payload, timeout=10)
        ok = resp.status_code == 200
        print(f"[Bark] http={resp.status_code} body={resp.text[:120]}")
        return ok
    except Exception as e:
        print(f"[Bark] 推送异常: {e}")
        return False


# ==================== 单账号编排 ====================

def run_account(index, ref, confirm):
    """单账号: YYB 取 code → 登录 → JWT → 抽奖/记录/奖品/抢兑"""
    logs = []
    print(f'\n======== ▷ 第 {index} 个账号 [ref={ref}] ◁ ========')

    code = _yyb_get_code(ref)
    if not code:
        print(f'  ⛔ ref={ref} code 获取失败, 跳过')
        return f'ref={ref}', None

    account, authorization = _yyb_login(code)
    if not account or not authorization:
        print(f'  ⛔ ref={ref} 登录失败, 跳过')
        return f'ref={ref}', None

    masked = account[:3] + '****' + account[-4:] if len(account) >= 11 else account
    logs.append(f'账号: {masked}')

    session = requests.Session()
    jwt_token = fetch_jwt_token(session, authorization, account)
    if not jwt_token:
        print(f'  ⛔ {masked} JWT 鉴权失败, 跳过')
        return masked, None

    do_lottery(session, jwt_token, logs)
    query_prize_log(session, jwt_token, logs)

    gifts, err = fetch_gift_list(session, jwt_token)
    if gifts is None:
        logs.append(f'\n🛒 可抢兑奖品列表\n-查询失败: {err}')
    else:
        log_gift_list(gifts, logs)
        redeem_gifts(session, jwt_token, gifts, logs, confirm)

    log_text = '\n'.join(logs)
    print(log_text)
    return masked, log_text


# ==================== 入口 ====================

if __name__ == '__main__':
    print(f'移动云盘·16号会员日 v{SCRIPT_VERSION} (YYB 版)')
    print(f'YYB 服务: {WX_SERVER_URL or "(未配置!)"}')
    print(f'账号列表: {MOVE16_REF or "(未配置!)"}')

    confirm = str(os.getenv('mcloudday_confirm', '')).strip() in ('1', 'true', 'True')
    print(f'抢兑模式: {"真实提交" if confirm else "测试模式(仅打印, 设 mcloudday_confirm=1 启用真实抢兑)"}')

    refs = re.split(r'[&]', MOVE16_REF or '')
    refs = [r.strip() for r in refs if r.strip()]
    if not refs:
        print('⛔️ move16_ref 为空, 请设置环境变量(默认 1&4&7&8&9&11)')
        raise SystemExit(0)
    print(f'共 {len(refs)} 个账号')

    all_logs = ''
    err_accounts = ''
    for i, ref in enumerate(refs, start=1):
        masked, log_text = run_account(i, ref, confirm)
        if log_text:
            all_logs += f'{log_text}\n\n'
        elif masked:
            err_accounts += f'{masked}\n'
        time.sleep(random.uniform(1, 3))

    msg = ''
    if err_accounts:
        msg += f'失效账号:\n{err_accounts}\n'
    msg += f'任务详情:\n{all_logs}'

    print('\n================ 运行总结 ================')
    if err_accounts:
        print(f'❌ 失效账号:\n{err_accounts}')

    title = '移动云盘·16号会员日'
    if BARK_PUSH:
        send_bark(title, msg, group='移动云盘')
    else:
        # 兜底：走青龙 notify
        try:
            from notify import send as _notify_send
            _notify_send(title, msg)
        except Exception:
            print('[通知] BARK_PUSH 未配, notify 模块也未注入, 仅打印')
