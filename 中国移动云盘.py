#!/usr/bin/env python3
"""
中国移动云盘 v1.0 - 客户端
功能: 签到 + 签到翻倍 + 云盘任务(知识库/宝宝爱秀/AI相机/高价值福利等)
      + 领取云朵 + 公众号任务 + 额外任务
      + 139邮箱任务 + 备份云朵 + 通知云朵 + 抽奖

环境变量(必填):
  ydypCK                  凭证, 格式: Authorization值#手机号 (多账号@或换行分隔)
  MCLOUD_AUTH_KEY         授权码(联系作者获取,默认已内置授权码)

cron: 0 8,16,20 * * *
"""

import os, sys, json, urllib.request, urllib.error

# ============ 服务端地址(勿修改) ============
SERVER_URL = os.environ.get("MCLOUD_SERVER", "https://task.zzcx.qzz.io")

# ============ 从环境变量读取配置 ============
# 授权码: 联系作者获取,用于验证身份(必填)
AUTH_KEY = os.environ.get("MCLOUD_AUTH_KEY", "hello158")
# 凭证: 格式 Authorization值#手机号, 多账号@或换行分隔(必填)
ACCOUNTS = os.environ.get("ydypCK", "")

# ============ 青龙通知(可选) ============
try:
    from notify import send as send_ql_notify
except ImportError:
    send_ql_notify = None

def main():
    if not AUTH_KEY:
        print("❌ 未设置授权码,请添加环境变量 MCLOUD_AUTH_KEY")
        sys.exit(1)
    if not ACCOUNTS:
        print("❌ 未设置凭证,请添加环境变量 ydypCK")
        sys.exit(1)

    # 构建请求
    payload = json.dumps({
        "script": "mcloud",
        "auth_key": AUTH_KEY,
        "accounts": ACCOUNTS,
    }).encode("utf-8")

    url = f"{SERVER_URL.rstrip('/')}/run"
    req = urllib.request.Request(url, data=payload)
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "Mozilla/5.0 (compatible; McloudClient/1.0)")
    req.add_header("Accept", "*/*")

    print("🔗 连接服务器...")
    all_lines = []
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            # 检查是否SSE流
            ct = resp.headers.get("Content-Type", "")
            if "event-stream" not in ct:
                body = resp.read().decode("utf-8")
                try:
                    err = json.loads(body)
                    print(f"❌ {err.get('error', body)}")
                except Exception:
                    print(f"❌ {body}")
                sys.exit(1)

            print("✅ 已连接\n")
            for raw in resp:
                line = raw.decode("utf-8", errors="replace").rstrip("\n\r")
                if line.startswith("data:"):
                    content = line[5:]
                    if content == "[DONE]":
                        break
                    print(content)
                    all_lines.append(content)

    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        try:
            err = json.loads(body)
            print(f"❌ {err.get('error', body)}")
        except Exception:
            print(f"❌ HTTP {e.code}: {body[:200]}")
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"❌ 无法连接服务器: {e.reason}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ 连接异常: {e}")
        sys.exit(1)

    # 青龙通知推送
    if send_ql_notify and all_lines:
        # 提取最后的汇总部分
        summary_start = -1
        for i, line in enumerate(all_lines):
            if "📊" in line or "任务汇总" in line:
                summary_start = i
                break
        if summary_start >= 0:
            summary = "\n".join(all_lines[summary_start:])
        else:
            summary = "\n".join(all_lines[-20:])
        try:
            send_ql_notify("中国移动云盘任务", summary)
            print("\n📨 青龙通知已发送")
        except Exception as e:
            print(f"\n⚠️ 通知发送失败: {e}")


if __name__ == "__main__":
    main()
