#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
移动云电脑保活工具 - 青龙面板版本（修正版）

使用 simple-keepalive 命令走完整协议链路（ZTE/SCG），而非已被否决的 HTTP 心跳。

环境变量配置（在青龙面板的"环境变量"中添加）：
    CMCC_USERNAME: 账号（必填，多个账号用 & 分隔）
    CMCC_PASSWORD: 密码（必填，多个账号用 & 分隔）
    CMCC_IS_SUB_ACCOUNT: 是否为子账号（可选，默认 false，多个用 & 分隔）
    CMCC_USER_SERVICE_ID: 指定云桌面ID（可选，不填则自动选择第一个）
    CMCC_KEEPALIVE_INTERVAL: 保活间隔分钟数（可选，默认 5）
    CMCC_PROTOCOL: 保活协议（可选，ZTE 或 SCG，默认 ZTE）
    CMCC_TRAFFIC_SECONDS: 单轮流量秒数（可选，默认 60）
    CMCC_RETRY_TIMES: 失败重试次数（可选，默认 3）
"""

import os
import sys
import json
import time
import subprocess
import traceback
from pathlib import Path
from datetime import datetime, timezone, timedelta


# 项目根目录
SCRIPT_DIR = Path(__file__).parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))


class Logger:
    """日志管理器"""
    
    def __init__(self):
        self.logs = []
    
    def log(self, message, level="INFO"):
        now = datetime.now(timezone(timedelta(hours=8)))
        timestamp = now.strftime("%Y-%m-%d %H:%M:%S")
        log_line = f"[{timestamp}] [{level}] {message}"
        print(log_line, flush=True)
        self.logs.append(log_line)
    
    def info(self, message):
        self.log(message, "INFO")
    
    def success(self, message):
        self.log(message, "SUCCESS")
    
    def error(self, message):
        self.log(message, "ERROR")
    
    def warning(self, message):
        self.log(message, "WARNING")
    
    def get_logs(self):
        return "\n".join(self.logs)


logger = Logger()


def get_env_array(key, default=None):
    """获取环境变量数组（支持 & 分隔的多账号）"""
    value = os.environ.get(key)
    if not value:
        return [default] if default else []
    return [v.strip() for v in value.split("&") if v.strip()]


def send_notification(title, content):
    """发送青龙面板通知"""
    try:
        from notify import send
        send(title, content)
        logger.info(f"通知已发送: {title}")
    except ImportError:
        pass
    except Exception as e:
        logger.warning(f"发送通知失败: {e}")


def process_account(index, username, password, is_sub_account, config):
    """处理单个账号"""
    logger.info(f"\n{'='*50}")
    logger.info(f"处理账号 {index + 1}: {username}")
    logger.info(f"{'='*50}")
    
    # 导入核心模块
    try:
        from cmcc_cloud_alive import auth, cloud, core, token
    except ImportError as e:
        logger.error(f"无法导入核心模块: {e}")
        return False
    
    # 设置状态文件路径
    state_dir = Path.home() / ".cmcc-cloud-alive"
    state_dir.mkdir(parents=True, exist_ok=True)
    state_path = str(state_dir / f"qinglong_{username}.json")
    
    logger.info(f"状态文件: {state_path}")
    
    # 登录
    logger.info("正在登录...")
    retry_times = config.get("retry_times", 3)
    
    for attempt in range(retry_times):
        try:
            if is_sub_account:
                auth.sub_password_login(username, password, state_path=state_path, save_password=True)
            else:
                auth.password_login(username, password, state_path=state_path, save_password=True)
            logger.success("登录成功")
            break
        except Exception as e:
            logger.error(f"登录失败 (尝试 {attempt + 1}/{retry_times}): {e}")
            if attempt < retry_times - 1:
                logger.info("等待 5 秒后重试...")
                time.sleep(5)
            else:
                logger.error("登录失败，已达到最大重试次数")
                return False
    
    # 获取云桌面列表
    logger.info("正在获取云桌面列表...")
    try:
        desktops = cloud.list_desktops(state_path=state_path)
        if not desktops:
            logger.error("未找到云桌面")
            return False
        
        logger.info(f"找到 {len(desktops)} 个云桌面:")
        for i, desktop in enumerate(desktops):
            name = desktop.get("vmName", "未命名")
            status = desktop.get("vmStatusShow", desktop.get("vmStatus", "未知"))
            usid = desktop.get("userServiceId", "")
            logger.info(f"  {i+1}. {name} (状态: {status}, ID: {usid})")
        
        # 选择云桌面
        user_service_id = config.get("user_service_id")
        if user_service_id:
            target = None
            for desktop in desktops:
                if desktop.get("userServiceId") == user_service_id:
                    target = desktop
                    break
            if not target:
                logger.error(f"未找到指定的云桌面 (ID: {user_service_id})")
                return False
            logger.info(f"使用指定云桌面: {target.get('vmName', '未命名')}")
        else:
            target = desktops[0]
            user_service_id = target.get("userServiceId")
            logger.info(f"自动选择第一个云桌面: {target.get('vmName', '未命名')}")
        
    except Exception as e:
        logger.error(f"获取云桌面列表失败: {e}")
        return False
    
    # 使用 simple-keepalive 命令执行保活（走完整协议链路）
    protocol = config.get("protocol", "ZTE").upper()
    interval_minutes = config.get("interval_minutes", 5)
    traffic_seconds = config.get("traffic_seconds", 60)
    
    logger.info(f"开始保活: protocol={protocol} interval={interval_minutes}分钟")
    
    python_exe = sys.executable
    cmd = [
        python_exe, "-m", "cmcc_cloud_alive",
        "--state", state_path,
        "simple-keepalive",
        "--user-service-id", str(user_service_id),
        "--protocol", protocol,
        "--interval-minutes", str(interval_minutes),
        "--traffic-seconds", str(traffic_seconds),
        "--mode", "2",
    ]
    
    logger.info(f"执行命令: {' '.join(cmd)}")
    
    try:
        result = subprocess.run(
            cmd,
            cwd=str(SCRIPT_DIR),
            capture_output=False,
            timeout=interval_minutes * 60 + 120,  # 超时保护
        )
        
        if result.returncode == 0:
            logger.success("保活执行完成")
            return True
        else:
            logger.error(f"保活退出码: {result.returncode}")
            return False
            
    except subprocess.TimeoutExpired:
        logger.warning("保活超时，但可能仍在运行中（正常现象）")
        return True
    except Exception as e:
        logger.error(f"保活执行异常: {e}")
        logger.error(traceback.format_exc())
        return False


def main():
    """主函数"""
    logger.info("=" * 60)
    logger.info("移动云电脑保活工具 - 青龙面板版（修正版）")
    logger.info("=" * 60)
    
    # 读取环境变量
    usernames = get_env_array("CMCC_USERNAME")
    passwords = get_env_array("CMCC_PASSWORD")
    sub_accounts = get_env_array("CMCC_IS_SUB_ACCOUNT", "false")
    
    if not usernames or not passwords:
        logger.error("错误: 环境变量 CMCC_USERNAME 和 CMCC_PASSWORD 未设置")
        logger.error("请在青龙面板的环境变量中添加这两个变量")
        sys.exit(1)
    
    if len(usernames) != len(passwords):
        logger.error(f"错误: 账号数量 ({len(usernames)}) 与密码数量 ({len(passwords)}) 不匹配")
        sys.exit(1)
    
    # 读取配置
    config = {
        "user_service_id": os.environ.get("CMCC_USER_SERVICE_ID"),
        "interval_minutes": int(os.environ.get("CMCC_KEEPALIVE_INTERVAL", "5")),
        "traffic_seconds": int(os.environ.get("CMCC_TRAFFIC_SECONDS", "60")),
        "protocol": os.environ.get("CMCC_PROTOCOL", "ZTE").upper(),
        "retry_times": int(os.environ.get("CMCC_RETRY_TIMES", "3")),
    }
    
    logger.info(f"\n配置信息:")
    logger.info(f"  账号数量: {len(usernames)}")
    logger.info(f"  保活间隔: {config['interval_minutes']} 分钟")
    logger.info(f"  单轮流量: {config['traffic_seconds']} 秒")
    logger.info(f"  保活协议: {config['protocol']}")
    logger.info(f"  重试次数: {config['retry_times']}")
    if config['user_service_id']:
        logger.info(f"  指定云桌面: {config['user_service_id']}")
    
    # 处理每个账号
    success_count = 0
    fail_count = 0
    
    for i, (username, password) in enumerate(zip(usernames, passwords)):
        is_sub_account = sub_accounts[i].lower() in ("true", "1", "yes", "on") if i < len(sub_accounts) else False
        
        try:
            success = process_account(i, username, password, is_sub_account, config)
            if success:
                success_count += 1
            else:
                fail_count += 1
        except Exception as e:
            logger.error(f"处理账号 {username} 时发生异常: {e}")
            logger.error(traceback.format_exc())
            fail_count += 1
    
    # 汇总结果
    logger.info(f"\n{'='*60}")
    logger.info("执行完成")
    logger.info(f"{'='*60}")
    logger.info(f"成功: {success_count} 个账号")
    logger.info(f"失败: {fail_count} 个账号")
    
    # 发送通知
    title = "移动云电脑保活完成"
    content = f"成功: {success_count} 个账号\n失败: {fail_count} 个账号"
    send_notification(title, content)
    
    if fail_count > 0:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
