#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
移动云电脑保活工具 - 配置测试脚本

用于测试青龙面板的环境变量配置是否正确
"""

import os
import sys
from pathlib import Path


def test_env_config():
    """测试环境变量配置"""
    print("=" * 60)
    print("移动云电脑保活工具 - 配置测试")
    print("=" * 60)
    print()
    
    errors = []
    warnings = []
    
    # 测试必填变量
    print("【1】检查必填变量...")
    username = os.environ.get("CMCC_USERNAME")
    password = os.environ.get("CMCC_PASSWORD")
    
    if not username:
        errors.append("❌ CMCC_USERNAME 未设置")
    else:
        print(f"✅ CMCC_USERNAME: {username}")
    
    if not password:
        errors.append("❌ CMCC_PASSWORD 未设置")
    else:
        print(f"✅ CMCC_PASSWORD: {'*' * len(password)}")
    
    print()
    
    # 测试可选变量
    print("【2】检查可选变量...")
    
    is_sub = os.environ.get("CMCC_IS_SUB_ACCOUNT", "false")
    print(f"✅ CMCC_IS_SUB_ACCOUNT: {is_sub}")
    
    user_service_id = os.environ.get("CMCC_USER_SERVICE_ID")
    if user_service_id:
        print(f"✅ CMCC_USER_SERVICE_ID: {user_service_id}")
    else:
        print(f"ℹ️  CMCC_USER_SERVICE_ID: 未设置（将自动选择第一个）")
    
    interval = os.environ.get("CMCC_KEEPALIVE_INTERVAL", "300")
    print(f"✅ CMCC_KEEPALIVE_INTERVAL: {interval} 秒")
    
    rounds = os.environ.get("CMCC_KEEPALIVE_ROUNDS", "1")
    print(f"✅ CMCC_KEEPALIVE_ROUNDS: {rounds}")
    
    protocol = os.environ.get("CMCC_PROTOCOL", "ZTE")
    print(f"✅ CMCC_PROTOCOL: {protocol}")
    
    retry = os.environ.get("CMCC_RETRY_TIMES", "3")
    print(f"✅ CMCC_RETRY_TIMES: {retry}")
    
    print()
    
    # 测试多账号配置
    print("【3】检查多账号配置...")
    usernames = [u.strip() for u in username.split("&")] if username else []
    passwords = [p.strip() for p in password.split("&")] if password else []
    sub_accounts = [s.strip() for s in is_sub.split("&")] if is_sub else ["false"]
    
    print(f"账号数量: {len(usernames)}")
    print(f"密码数量: {len(passwords)}")
    print(f"子账号标记数量: {len(sub_accounts)}")
    
    if len(usernames) != len(passwords):
        errors.append(f"❌ 账号数量 ({len(usernames)}) 与密码数量 ({len(passwords)}) 不匹配")
    else:
        print(f"✅ 账号和密码数量匹配")
    
    if len(usernames) > 1 and len(sub_accounts) == 1:
        warnings.append("⚠️  多账号但只配置了一个子账号标记，将全部使用第一个标记")
    
    print()
    
    # 测试项目文件
    print("【4】检查项目文件...")
    script_dir = Path(__file__).parent
    
    required_files = [
        "cmcc_cloud_alive/__init__.py",
        "cmcc_cloud_alive/auth.py",
        "cmcc_cloud_alive/cloud.py",
        "cmcc_cloud_alive/desktop_keepalive.py",
    ]
    
    for file in required_files:
        file_path = script_dir / file
        if file_path.exists():
            print(f"✅ {file}")
        else:
            errors.append(f"❌ 缺少文件: {file}")
    
    print()
    
    # 测试 Python 导入
    print("【5】测试模块导入...")
    try:
        sys.path.insert(0, str(script_dir))
        from cmcc_cloud_alive import auth, cloud, desktop_keepalive
        print("✅ 核心模块导入成功")
    except ImportError as e:
        errors.append(f"❌ 模块导入失败: {e}")
    
    print()
    
    # 测试状态目录
    print("【6】检查状态目录...")
    state_dir = Path.home() / ".cmcc-cloud-alive"
    if state_dir.exists():
        print(f"✅ 状态目录存在: {state_dir}")
    else:
        try:
            state_dir.mkdir(parents=True, exist_ok=True)
            print(f"✅ 状态目录已创建: {state_dir}")
        except Exception as e:
            errors.append(f"❌ 无法创建状态目录: {e}")
    
    print()
    
    # 汇总结果
    print("=" * 60)
    print("测试结果汇总")
    print("=" * 60)
    
    if errors:
        print(f"\n❌ 发现 {len(errors)} 个错误:")
        for error in errors:
            print(f"  {error}")
    
    if warnings:
        print(f"\n⚠️  发现 {len(warnings)} 个警告:")
        for warning in warnings:
            print(f"  {warning}")
    
    if not errors and not warnings:
        print("\n✅ 所有检查通过！配置正确。")
        print("\n可以添加定时任务了：")
        print("  命令: python3 qinglong_keepalive_enhanced.py")
        print("  定时规则: */10 * * * *")
    
    if errors:
        print("\n请修复上述错误后重试。")
        return False
    
    return True


if __name__ == "__main__":
    success = test_env_config()
    sys.exit(0 if success else 1)
