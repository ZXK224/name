# name: 移动云手机任务
"""
✅ 移动云手机APP
✅ 账号变量ChinaMobileCloudPhone = Token 或 手机号#Token 或 refreshToken 或 Token#refreshToken 或 手机号#Token#refreshToken 或 手机号#密码
✅ 代理变量ProxyIP = 提取IP的API [响应选txt格式][选配]
✅ refreshToken和手机号#密码两种参数支持刷新Token持久化
✅ 防休眠无法抗争移动维护时段/效率一般
✅ 定时Crontab = 0 0 0-23/2 * * * [自己看着来即可]
✅ 建议抓取密码版APP，登录以后开着抓包重启APP即可于响应抓取Token和refreshToken
✅ 建议登录密码版APP和利用网页地址生成客户端双登录，密码版APP抓包以后直接清除数据不影响网页生成客户端使用
⚠️ 无云手机不执行安装应用任务、签到因技术有限暂时未能实现
"""

import os
import re
import io
import sys
import json
import time
import uuid
import base64
import random
import string
import logging
import hashlib
import requests
from notify import send
from pathlib import Path
from datetime import datetime
from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_v1_5
from requests.exceptions import RequestException
from requests.exceptions import RequestException, Timeout
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 日志
log_stream = io.StringIO()
logging.basicConfig(level=logging.INFO,format="%(message)s",handlers=[logging.StreamHandler(sys.stdout),logging.StreamHandler(log_stream)])
log = logging.getLogger()

class ChinaMobileCloudPhoneAPI:
    def __init__(self, phone=None, token=None, refresh_token=None, password=None):
        self.phone = phone
        self.token = token
        self.verified_token = None
        self.refresh_token = refresh_token
        self.password = password
        self.proxy_api = os.getenv('ProxyIP_YD')
        self.proxy = None
        self.session = requests.Session()

    @classmethod
    def from_env(cls):
        accounts = []
        env_value = os.getenv("ChinaMobileCloudPhone", "").strip()
        
        for line in env_value.splitlines():
            line = line.strip()
            if not line:
                continue

            parts = [p.strip() for p in line.split('#') if p.strip()]
            phone, token, refresh_token, password = None, None, None, None
            phone_candidates = [p for p in parts if len(p) == 11 and p.isdigit()]
            if phone_candidates:
                phone = phone_candidates[0]
                parts = [p for p in parts if p != phone]
            def is_ey_token(s):
                return s.startswith('ey') and len(s) > 20
            if not phone:
                if len(parts) == 1:
                    if is_ey_token(parts[0]):
                        token = parts[0]
                    else:
                        refresh_token = parts[0]
                elif len(parts) == 2:
                    token, refresh_token = parts[0], parts[1]
            else:
                for field in parts:
                    if is_ey_token(field):
                        if not token:
                            token = field
                        else:
                            refresh_token = field
                    else:
                        password = field

            accounts.append(cls(phone, token, refresh_token, password))
        
        return accounts

    def load_or_create_account_cache(self):
        cache_path = Path(__file__).parent / "ChinaMobileCloudPhone.json"
        if cache_path.exists():
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    all_data = json.load(f)
                if self.phone and self.phone in all_data:
                    self.token = all_data[self.phone].get("token")
                    self.refresh_token = all_data[self.phone].get("refresh_token")
                    return True
            except Exception as e:
                log.warning(f"⚠️ 读取缓存失败：{e}")
        else:
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump({}, f, indent=2)
        return False

    def save_account_to_cache(self):
        cache_path = Path(__file__).parent / "ChinaMobileCloudPhone.json"
        try:
            if cache_path.exists():
                with open(cache_path, "r", encoding="utf-8") as f:
                    all_data = json.load(f)
            else:
                all_data = {}
            all_data[self.phone] = {
                "token": self.token,
                "refresh_token": self.refresh_token,
                "update_time": datetime.now().isoformat()
            }
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(all_data, f, indent=2, ensure_ascii=False)
            log.info(f"💾 已更新账号数据")
        except Exception as e:
            log.error(f"❌ 缓存保存失败: {e}")

    # 请求头封装
    def get_headers(self, Type=None, verified_token=False):
        appid = "12345681"
        timestamp = str(int(time.time() * 1000))
        token_to_use = self.verified_token if verified_token else self.token
        common_headers = {
            'appid': appid,
            'timestamp': timestamp,
            'token': token_to_use
        }
        if Type == "G":
            requestid = self.generate_request_id(timestamp, False)
            sign_data = f"{requestid}{appid}"
            sign = self.generate_sign(sign_data)
            headers = {
                'Content-Type': 'application/json; charset=UTF-8',
                'Accept': 'application/json, text/plain, */*',
                'User-Agent': 'PC',
                'requestid': requestid,
                'sign': sign,
                'x-kpcc-clientid': 'X3qUAu6hA1yO6CegzcMSrQJknuZ7aEs1',
                'x-channelsrc': '02047',
                'platform': 'h5',
                **common_headers
            }
        elif Type == "S":
            requestid = self.generate_request_id(timestamp, True)
            sign_data = f"{requestid}{appid}{token_to_use}e10adc3949ba59abbe56e057f20f883e{timestamp}"
            sign = self.generate_sign(sign_data)
            headers = {
                "sec-ch-ua": '"Android WebView";v="117", "Not;A=Brand";v="8", "Chromium";v="117"',
                "x-origin": "https://cpactiv.buy.139.com/#/redEnvelopeParty/home?channelSrc=red-cloudphone-001",
                "x-channelsrc": "red-cloudphone-001",
                "sec-ch-ua-mobile": "?1",
                "requestid": requestid,
                "user-agent": "Mozilla/5.0 (Linux; Android 13; 23013RK75C Build/TKQ1.220905.001; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/117.0.0.0 Mobile Safari/537.36",
                "content-type": "application/json;charset=UTF-8",
                "accept": "application/json, text/plain, */*",
                "x-deviceinfo": "4g|h5|1.0.0|v1.0.0||Mozilla/5.0 (Linux; Android 13; 23013RK75C Build/TKQ1.220905.001; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/117.0.0.0 Mobile Safari/537.36|1744289338354WL7dVzQzWJ|||412X915|zh||",
                "sign": sign,
                "sec-ch-ua-platform": '"Android"',
                "origin": "https://cpactiv.buy.139.com",
                "x-requested-with": "com.chinamobile.hycloudphone",
                "sec-fetch-site": "same-origin",
                "sec-fetch-mode": "cors",
                "sec-fetch-dest": "empty",
                "referer": "https://cpactiv.buy.139.com/",
                "accept-encoding": "gzip, deflate, br",
                "accept-language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
                "cookie": "8d2279a5e2f18b7c_gdp_user_key=; gdp_user_id=gioenc-8461e7gg%2C5bd0%2C540d%2C9217%2C116d69g65a5e; 8d2279a5e2f18b7c_gdp_cs1=gioenc-bb2CD8OASvaxr2y.8M7JfP<<; 8d2279a5e2f18b7c_gdp_gio_id=gioenc-bb2CD8OASvaxr2y.8M7JfP<<; 8d2279a5e2f18b7c_gdp_session_id=74ef66af-6a3d-45f1-b6ef-43b2385b2d70; 8d2279a5e2f18b7c_gdp_session_id_74ef66af-6a3d-45f1-b6ef-43b2385b2d70=true; 8d2279a5e2f18b7c_gdp_sequence_ids={%22globalKey%22:10%2C%22VISIT%22:4%2C%22PAGE%22:3%2C%22CUSTOM%22:5}",
                **common_headers
            }
        return headers

    # 请求封装
    def send_res(self, url, data=None, headers=None, max_retries=3, timeout=30, show_res=False, **kwargs):
        for attempt in range(max_retries):
            try:
                if self.proxy_api and not hasattr(self, 'proxy_disabled'):
                    if not self.proxy or attempt > 0:
                        self.proxy = self.fetch_proxyip()
                        if self.proxy:
                            print(f"✅ 代理IP：{self.proxy}")
                            self.session.proxies.update({
                                "http": f"http://{self.proxy}",
                                "https": f"http://{self.proxy}"
                            })
                res = self.session.post(url, data=data, headers=headers, timeout=timeout, **kwargs, verify=False)
                if show_res:
                    print(f"响应: {res.text}")
                
                return res.json()
            
            except RequestException as e:
                if "NameResolutionError" in str(e) or "Failed to resolve" in str(e):
                    log.info(f"⚠️ 请求异常-进行重试")
            
            if attempt < max_retries - 1:
                time.sleep(2)

            if self.proxy:
                self.session.proxies.clear()
                self.proxy = None
    
    # 代理IP提取
    def fetch_proxyip(self, max_retries=3):
        if hasattr(self, 'proxy_disabled') and self.proxy_disabled:
            return None
        for attempt in range(max_retries):
            try:
                resp = requests.get(self.proxy_api, timeout=15)
                text = resp.text.strip()
                try:
                    json_resp = resp.json()
                    if json_resp.get('code') == -1:
                        self.proxy_disabled = True
                        message = json_resp.get('message', '未知错误')
                        log.error(f"❌ 代理提取失败：{message}")
                        return None
                    
                    proxy_ip = json_resp.get('data', {}).get('proxy') or json_resp.get('data', {}).get('ip')
                    if proxy_ip and re.match(r'^\d+\.\d+\.\d+\.\d+:\d+$', proxy_ip):
                        return proxy_ip
                
                except ValueError:
                    if re.match(r'^\d+\.\d+\.\d+\.\d+:\d+$', text):
                        return text
            
            except Exception as e:
                log.error(f"⚠️ 提取代理IP失败,进行第{attempt + 1}次重试")
                time.sleep(3)
            
        log.error("❌ 多次尝试后仍未获取到有效代理IP")
        return None
    
    # RequestID生成
    def generate_request_id(self, timestamp, is_config_2=False):
        dt_str = time.strftime('%Y%m%d%H%M%S', time.localtime(int(timestamp) / 1000))
        if is_config_2:
            rand_str = ''.join(random.choices(string.ascii_letters, k=8))
            return f"{dt_str}{timestamp}{rand_str}"
        else:
            rand_str = ''.join(random.choices('abcdefghijklmnopqrstuvwxyz0123456789', k=6))
            return dt_str + timestamp + rand_str
    
    # MD5签名
    def generate_sign(self, data):
        return hashlib.md5(data.encode('utf-8')).hexdigest()
    
    # 加密
    def _rsa_encrypt(self, plaintext):
        public_key_str = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAvtQpvb5Z5qihpeEugZWe
8zggWhM4n9w4miKWkYQXN1V69O3OPWo9IegaQf7rtK8PeI9jItQQU/o8Tb7wgPCX
0hWHnDIsTr3mndshmgqL907i4LkLiYzB33NWUG46LAFe/yfxexLtDk1r3M+Tnuyn
ZmqXfloTovqR1IW5YZghmTjdpAkDp4094U5TRBy+Iuvw3x4la9cLEYc1ysKhzJAj
Cj7xWHXNS8rngiy727UtopyUXR8PZjBX/hiwgKZWD3hNnAvxMuRpF8LP9dugvSKs
FE3vV7mdd6wVcgMgyiOFX3NFXpJRbKCVl6EDfQmT1YbddowV6MzN0bKSASDpnFvZ
dwIDAQAB
-----END PUBLIC KEY-----"""
        
        try:
            public_key = RSA.import_key(public_key_str)
            cipher = PKCS1_v1_5.new(public_key)
            
            chunk_size = 128
            encrypted_chunks = []
            
            for i in range(0, len(plaintext), chunk_size):
                chunk = plaintext[i:i+chunk_size]
                encrypted_chunk = cipher.encrypt(chunk.encode())
                encrypted_chunks.append(encrypted_chunk)

            encrypted = b''.join(encrypted_chunks)
            return base64.b64encode(encrypted).decode()
            
        except Exception as e:
            log.error(f"RSA加密失败: {str(e)}")
            raise
    
    # 密码登录
    def password_login(self):
        encrypted_mobile = self._rsa_encrypt(self.phone)
        encrypted_password = self._rsa_encrypt(self.password)
        request_id = str(uuid.uuid4())
        secret_key = "e15a3bab3a70a4fe4ae17d4369f92a45"
        sign_data = f"{request_id}12345681{secret_key}"
        sign = hashlib.md5(sign_data.encode()).hexdigest()
        headers = {
            "Connection": "Keep-Alive",
            "Accept-Encoding": "gzip",
            "User-Agent": "okhttp/4.2.2",
            "x-Source": "Xiaomi",
            "requestId": request_id,
            "appId": "12345681",
            "sign": sign,
            "x-NetType": "WiFi",
            "x-DeviceInfo": "1|192.168.2.219|Android|Carry You Home|1.0.0|Redmi|23013RK75C|d260fc1c-bbd3-4ea0-98ab-0b06d00730fb|02:00:00:00:00:00|Android13 33|1440x3024|zh-rCN|0|0",
            "x-channelSrc": "",
            "platform": "app",
            "Content-Type": "application/json; charset=UTF-8"
        }
        url = "https://cpability.buy.139.com/cloudphone/mobile/login"
        data = {
            "mobile": encrypted_mobile,
            "password": encrypted_password
        }
        res = self.send_res(url, json=data, headers=headers, show_res=False)
        if res["data"] is None:
            errMsg = res["header"]["errMsg"]
            log.error(f"❌ {errMsg}")
        else:
            self.token = res["data"]["accessToken"]
            self.refresh_token = res["data"].get("refreshToken")
            self.save_account_to_cache()
            return self.token

    # 刷新Token
    def refresh_token_action(self):
        filename = "ChinaMobileCloudPhone.json"
        accounts = {}
        if os.path.exists(filename):
            with open(filename, "r", encoding="utf-8") as f:
                try:
                    accounts = json.load(f)
                except json.JSONDecodeError:
                    log.info("⚠️ 账号缓存文件格式错误，将重新创建")
        
        else:
            with open(filename, "w", encoding="utf-8") as f:
                json.dump({}, f, ensure_ascii=False, indent=2)
        
        if self.phone in accounts:
            stored_info = accounts[self.phone]
            if stored_info.get("refresh_token"):
                self.refresh_token = stored_info["refresh_token"]

        request_id = str(uuid.uuid4())
        appid = "12345681"
        secret_key = "e15a3bab3a70a4fe4ae17d4369f92a45"
        sign_data = request_id + appid + secret_key
        sign = hashlib.md5(sign_data.encode()).hexdigest()
        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "User-Agent": "okhttp/4.12.0",
            "Host": "cloudphoneh5.buy.139.com",
            "requestid": request_id,
            "appid": appid,
            "timestamp": str(int(time.time() * 1000)),
            "x-source": "Xiaomi",
            "sign": sign,
            "x-nettype": "wifi",
            "x-deviceinfo": "wifi||Android|5.6.1.20250226||Redmi|23013RK75C|e56af417-5178-480e-8f1f-972276fa4ed0||Android13 33|1440x3024|zh-rCN|||qijianban|03001||",
            "x-channelsrc": "03001",
            "platform": "APP"
        }
        url = "https://cpability.buy.139.com/cloudphone/user/tokenRefreshV2"
        data = {
            "refreshToken": self.refresh_token
        }
        res = self.send_res(url, json=data, headers=headers, show_res=False)
        if res.get("data") and res["data"].get("token"):
            self.token = res["data"]["token"]
            self.refresh_token = res["data"].get("refreshToken", self.refresh_token)
            self.save_account_to_cache()
            log.info("🔁 RefreshToken 刷新成功")
            return True
        else:
            if self.password and self.phone:
                try:
                    login_result = self.password_login()
                    if login_result:
                        log.info("🔁 RefreshToken 刷新成功")
                        return True

                except Exception as e:
                    log.error(f"❌ 密码格式重登异常: {str(e)}")

            return False

    # 检查免费云手机领取资格
    def check_receive_qualification(self):
        filename = "ChinaMobileCloudPhone.json"
        if os.path.exists(filename):
            try:
                with open(filename, "r", encoding="utf-8") as f:
                    accounts = json.load(f)
                if self.phone in accounts:
                    info = accounts[self.phone]
                    self.token = info.get("token", self.token)
                    self.refresh_token = info.get("refresh_token", self.refresh_token)
            except Exception as e:
                log.error(f"❌ 加载账号信息失败: {e}")

        try:
            url = "https://cloud.139.com/ulhw/cloudphone/order/free/checkQualification"
            headers = self.get_headers(Type="G")
            headers["token"] = self.token
            data = {}
            res = self.send_res(url, json=data, headers=headers, show_res=False)
            err_msg = res["header"]["errMsg"]
            if "用户登录token已失效" in err_msg and self.token:
                log.info("🔐 Token失效，处理Token刷新")
                self.refresh_token = self.refresh_token or self.token

                if self.refresh_token_action():
                    return self.check_receive_qualification()

                elif self.phone and self.password:
                    log.info("🔁 刷新失败，尝试重新登录")
                    if self.password_login():
                        return self.check_receive_qualification()
                    else:
                        log.info("❌ 密码登录失败，无法继续")
                        return
                else:
                    log.info("❌ RefreshToken已失效")
                    return
            
            if "data" not in res:
                log.info(f"❌ {err_msg}")
                return

            if res["data"]["checkResult"] == False:
                return True

            else:
                url = "https://cloud.139.com/ulhw/cloudphone/order/free/instance"
                headers = self.get_headers(Type="G")
                data = {
                    "platform": 2,
                    "version": "2.0"
                }
                try:
                    res = self.send_res(url, json=data, headers=headers, show_res=False)
                    if res and res.get("header", {}).get("status") == "200":
                        log.info("✅ 领取成功-云手机专业体验版")

                except Exception as e:
                    log.error(f"❌ 免费云手机领取异常: {str(e)}")

        except Exception as e:
            log.error(f"❌ 检查免费云手机领取资格异常: {str(e)}")      

    # 获取Tmp_Token
    def get_tmp_token(self):
        url = "https://cloud.139.com/ulhw/cloudphone/user/login/sso/getUmcTmpToken"
        headers = self.get_headers(Type="G")
        data={}
        try:
            res = self.send_res(url, json=data, headers=headers, show_res=False)
            if res and res.get("header", {}).get("status") == "200":
                self.tmp_token = res.get("data", {}).get("tmpToken")
                self.get_token_validate()

        except Exception as e:
            log.error(f"❌ 获取Tmp_Token异常: {str(e)}")

    # 获取Validate_Token
    def get_token_validate(self):
        url = 'https://cpactiv.buy.139.com/cloudphone-market/user/tokenValidate'
        headers = self.get_headers(Type="S")
        data = {
            "version": "1.0",
            "pintype": 13,
            "token": self.tmp_token
        }
        try:
            res = self.send_res(url, json=data, headers=headers, show_res=False)
            if res and res.get("header", {}).get("status") == "200":
                self.verified_token = res.get("data", {}).get("token")
                return self.verified_token

        except Exception as e:
            log.error(f"❌ 获取Validate_Token异常: {str(e)}")

    # 查询云手机设备
    def get_cloud_phone_device(self, install_task=False):
        self.get_tmp_token()
        url = "https://cpactiv.buy.139.com/cloudphone-market/app/activity/getBookRecord"
        headers = self.get_headers(Type="S", verified_token=True)
        data = {
            "hwToken": self.token,
            "pageNum": 1,
            "pageSize": 10
        }
        try:
            res = self.send_res(url, json=data, headers=headers, show_res=False)
            phone_list = res["data"]["data"]["phoneInstanceList"]
            if not phone_list:
                self.phone_list = []
            else:
                self.phone_list = phone_list
            
            if not install_task:
                for phone in self.phone_list:
                    self.phone_id = phone.get("phoneId")
                    self.phone_name = phone.get("phoneName")
                    log.info(f"✅  {self.phone_name}")
                    self.enter_cloud_phone()

            return self.phone_list

        except Exception as e:
            log.error(f"❌ 查询云手机设备异常: {str(e)}")

    # 云手机设备防休眠
    def enter_cloud_phone(self):
        url = "https://cpability.buy.139.com/cloudphone/user/instance/auth"
        headers = self.get_headers(Type="G")
        data = {
            "phoneId": self.phone_id
        }
        try:
            res = self.send_res(url, json=data, headers=headers, show_res=False)
            if res and res.get("header", {}).get("status") == "200":
                log.info(f"✅ 防休眠 - 离线唤醒在线串流")

        except Exception as e:
            log.error(f"❌ 云手机设备防休眠异常: {str(e)}")

    # 红包派对任务查询
    def red_party(self):
        today = datetime.today().strftime('%Y-%m-%d')
        url = "https://cpactiv.buy.139.com/cloudphone-market/redpacket/configTaskLoginList"
        headers = self.get_headers(Type="S", verified_token=True)
        data={}
        try:
            res = self.send_res(url, json=data, headers=headers, show_res=False)
            if "configTaskSignList" in res['data']:
                for task in res['data']['configTaskSignList']:
                    date = task['date']
                    sign_amount = float(task['signAmount']) / 100
                    status = task['status']
                    is_today = task['isToday']
                    if date == today:
                        if is_today == 1 and status == 1:
                            log.info(f"✅ 已完成-签到")
                        else:
                            log.info(f"⚠️ 未完成-签到")

            if "configTaskNoviceList" in res['data']:
                for task in res['data']['configTaskNoviceList']:
                    task_id = task['id']
                    task_code = task['taskCode']
                    task_name = task['taskName']
                    user_status = task['userStatus']
                    prize_amount = float(task['prizeAmount']) / 100
                    if user_status == 0:
                        log.info(f"⚠️ 未完成-{task_name}")
                        if task_id == "3":
                            self.task_id = task_id
                            self.task_name = task_name
                            self.prize_amount = prize_amount
                            self.receive_30GB_traffic()

                        if task_id in ("4", "5"):
                            self.task_id = task_id
                            self.task_code = task_code
                            self.task_name = task_name
                            self.prize_amount = prize_amount
                            self.browse_task()                       
            
            if "configTaskMonthlyList" in res['data']:
                for task in res['data']['configTaskMonthlyList']:
                    task_id = task['id']
                    task_code = task['taskCode']
                    task_name = task['taskName']
                    task_explain = task['taskExplain']
                    prize_amount = float(task['prizeAmount']) / 100
                    user_status = task['userStatus']
                    userCompleteNum = task['userCompleteNum']
                    user_can_complete_num = task['userCanCompleteNum']
                    usercan = user_can_complete_num - userCompleteNum
                    if user_status == 0:
                        log.info(f"⚠️ 未完成-{task_name}")
                        if task_id == "7":
                            self.task_id = task_id
                            self.task_code = task_code
                            self.task_name = task_name
                            self.prize_amount = prize_amount
                            self.browse_task()

                        elif task_id == "8":
                            pass
                            #self.task_id = task_id
                            #self.usercan = usercan
                            #self.install_app_task()

                        elif task_id == "9":
                            self.task_id = task_id
                            self.red_packet_quiz()

                    else:
                        log.info(f"✅ 已完成-{task_name}")
            
            total_sign_times = res['data'].get("totalSignTimes", 0)
            log.info(f"🔢 本月累计签到次数: {total_sign_times}")

        except Exception as e:
            log.error(f"❌ 红包派对任务查询异常: {str(e)}")

    # 领取30GB定向流量
    def receive_30GB_traffic(self):
        url = "https://cpactiv.buy.139.com/cloudphone-market/redpacket/userCompleteTask"
        headers = self.get_headers(Type="S", verified_token=True)
        data = {
            "taskId": self.task_id
        }
        try:
            res = self.send_res(url, json=data, headers=headers, show_res=False)
            if res and res.get("data", {}).get("status") == 1:
                log.info(f"✅ 已处理-{self.task_name} {self.prize_amount}元")

        except Exception as e:
            log.error(f"❌ 领取任务异常: {str(e)}")

    # 浏览任务
    def browse_task(self):
        url = "https://cpactiv.buy.139.com/cloudphone-market/redpacket/userCompleteTask"
        headers = self.get_headers(Type="S", verified_token=True)
        headers["x-origin"] = "https://cpactiv.buy.139.com/#/redEnvelopeParty/home?channelSrc=red-cloudphone-002"
        data = {
            "taskId": self.task_id
        }
        try:
            res = self.send_res(url, json=data, headers=headers, show_res=False)
            if self.task_id == "3":
                if res.get("data", {}).get("status") == 1:
                    log.info(f"✅ 已处理-{self.task_name} {self.prize_amount}元")

            elif self.task_id in ("4", "5", "7"):
                url = "https://cpactiv.buy.139.com/cloudphone-market/redpacket/userBrowse"
                if self.task_id == 4 or self.task_id == 5:
                    origin = "https://cpactiv.buy.139.com/#/redEnvelopeParty/tutorial?task=1"
                else:
                    origin = "https://cpactiv.buy.139.com/#/activityCenter?task=1"
                    headers["x-channelsrc"] = "red-cloudphone-002"
                headers = self.get_headers(Type="S", verified_token=True)
                headers["x-origin"] = origin
                data = {
                    "taskCode": self.task_code
                }
                try:
                    res = self.send_res(url, json=data, headers=headers, show_res=False)
                    if res.get("data", {}).get("status") == 1:
                        log.info(f"✅ 已处理-{self.task_name} {self.prize_amount}元")
                    
                except Exception as e:
                    log.error(f"❌ {self.task_name}异常: {str(e)}")
                
        except Exception as e:
            log.error(f"❌ {self.task_name}异常: {str(e)}")

    # 安装应用
    def install_app_task(self):
        self.get_cloud_phone_device(install_task=True)
        if self.phone_list:
            selected_phone = random.choice(self.phone_list)
            self.phone_id = selected_phone.get("phoneId")
            self.phone_name = selected_phone.get("phoneName")
            if self.usercan > 0:
                log.info(f"⚠️ 任务需求{self.usercan}个应用")

                app_list = self.get_app_list()

                if app_list:
                    for i in range(self.usercan):
                        app = random.choice(app_list)
                        log.info(f"✅ 安装 {app.get('apkName')} 到 {self.phone_name}")
                        if not self.install_app(app):
                            log.info(f"❌ 第 {i+1} 个应用安装失败")
                            continue
                        
                        if not self.check_install_progress(app):
                            log.info(f"❌ 第 {i+1} 个应用安装未完成")
                            continue
                             
                        self.submit_task_completion(app)

                        log.info(f"✅ 第{i+1}个应用安装完成")

    # 查询安装应用列表
    def get_app_list(self):
        url = "https://cpactiv.buy.139.com/cloudphone-market/redpacket/configAppList"
        headers = self.get_headers(Type="S", verified_token=True)
        data={}
        try:
            res = self.send_res(url, json=data, headers=headers, show_res=False)
            err_msg = res["header"]["errMsg"]
            if res and res.get("data"):
                app_list = res["data"].get("list", [])
                if app_list:
                    return app_list
            else:
                log.info(f"❌ 查询安装应用列表-{err_msg}")
                return []

        except Exception as e:
            log.error(f"❌ 查询安装应用列表异常: {str(e)}")

    # 提交安装应用
    def install_app(self, app_info):
        url = "https://cpactiv.buy.139.com/cloudphone-market/app/activity/apkInstall"
        headers = self.get_headers(Type="S", verified_token=True)
        data = {
            "instanceId": self.phone_id,
            "appId": app_info.get("packageId") or app_info.get("id"),
            "hwToken": self.token
        }
        try:
            res = self.send_res(url, json=data, headers=headers, show_res=False)
            if res and res.get("header", {}).get("status") == "200":
                self.taskid = res.get("data", {}).get("data", {}).get("taskId")
                return True

        except Exception as e:
            log.error(f"❌ 提交安装应用异常: {str(e)}")
            return False

    # 检查安装进度
    def check_install_progress(self, app_info, max_checks = 120):
        try:
            for check_attempt in range(1, max_checks + 1):
                url = "https://cpactiv.buy.139.com/cloudphone-market/app/activity/appInstallTaskStatus"
                headers = self.get_headers(Type="S", verified_token=True)
                data = {
                    "taskId": self.taskid,
                    "hwToken": self.token
                }
                res = self.send_res(url, json=data, headers=headers, show_res=False)
                task_status = res.get("data", {}).get("data", {}).get("taskStatus")
                if task_status == 2:
                    return True
                else:
                    time.sleep(1)
            
            log.info("⚠️ 安装未完成")
            return False

        except Exception as e:
            log.error(f"❌ 检查安装进度异常: {str(e)}")      
        
    # 提交安装任务完成
    def submit_task_completion(self, app_info):
        url = "https://cpactiv.buy.139.com/cloudphone-market/redpacket/userInstallApp"
        headers = self.get_headers(Type="S", verified_token=True)
        headers["x-origin"] = "https://cpactiv.buy.139.com/#/redEnvelopeParty/home?channelSrc=red-cloudphone-002"
        headers["x-channelsrc"] = "red-cloudphone-002"
        data = {
            "taskId": self.task_id,
            "appId": app_info.get("apk_id")
        }
        try:
            res = self.send_res(url, json=data, headers=headers, show_res=False)
            if res.get("data", {}).get("status") == 1:
                log.info(f"✅ 执行安装成功")

        except Exception as e:
            log.error(f"❌ 提交安装任务完成异常: {str(e)}")

    # 趣味答题挑战
    def red_packet_quiz(self):
        url = "https://cpactiv.buy.139.com/cloudphone-market/redpacket/configTopicList"
        headers = self.get_headers(Type="S", verified_token=True)
        headers["x-origin"] = "https://cpactiv.buy.139.com/#/redEnvelopeParty/home?channelSrc=red-cloudphone-002"
        data = {}
        try:
            res = self.send_res(url, json=data, headers=headers, show_res=False)
            question = res["data"]["list"][0]
            self.topic_id = question["id"]
            content = question["topicContent"]
            options = json.loads(question["topicOption"])
            log.info(f"📘题目: {content}")
            for idx, opt in enumerate(options):
                log.info(f"  {chr(65 + idx)}. {opt}")
            try:
                with open("ChinaMobileCloudPhoneDT.json", "r", encoding="utf-8") as f:
                    answer_map = json.load(f)
            except Exception as e:
                log.error(f"❌ 读取题库失败: {e}")
                return
            
            matched_keyword = None
            expected_answer_keyword = None
            if content in answer_map:
                matched_keyword = content
                expected_answer_keyword = answer_map[content]
            else:
                for keyword in answer_map:
                    if keyword in content:
                        matched_keyword = keyword
                        expected_answer_keyword = answer_map[keyword]
                        break
            
            if not matched_keyword:
                log.info("❌ 本地题库中未找到匹配关键词，跳过")
                return
            
            expected_answer_keyword = answer_map[matched_keyword]
            log.info(f"🎯 匹配→ 答案关键词: {expected_answer_keyword}")
            self.answer_index = next((i for i, opt in enumerate(options) if expected_answer_keyword in opt), None)
            if self.answer_index is None:
                log.info("❌ 答案关键词未在选项中找到，跳过")
                return
            else:
                self.submit_answer()

        except Exception as e:
            log.error(f"❌ 趣味答题挑战题目获取异常: {str(e)}")

    # 趣味答题挑战提交答案
    def submit_answer(self):
        answer_letter = chr(65 + self.answer_index)
        url = "https://cpactiv.buy.139.com/cloudphone-market/redpacket/userTopicAnswer"
        headers = self.get_headers(Type="S", verified_token=True)
        data = {
            "taskId": self.task_id,
            "topicId": self.topic_id,
            "answer": answer_letter
        }
        try:
            res = self.send_res(url, json=data, headers=headers, show_res=False)
            if res and res.get("header", {}).get("status") == "200":
                log.info("✅ 答题成功")

        except Exception as e:
            log.error(f"❌ 趣味答题挑战提交答案异常: {str(e)}")

    # 红包派对账户信息
    def red_packet_account_info(self):
        url = "https://cpactiv.buy.139.com/cloudphone-market/redpacket/userAccountInfo"
        headers = self.get_headers(Type="S", verified_token=True)
        data = {}
        try:
            res = self.send_res(url, json=data, headers=headers, show_res=False)
            if not res or "data" not in res or "info" not in res["data"]:
                log.error("❌获取失败-红包账户信息")
                return
            
            info = res["data"]["info"]
            total = int(info.get("totalAmount", 0)) / 100
            can = int(info.get("canAmount", 0)) / 100
            log.info(f"✅ 累计红包：{total:.2f} 元")
            log.info(f"✅ 当前余额：{can:.2f} 元")
        
        except Exception as e:
            log.error(f"❌ 红包派对账户信息查询异常: {str(e)}")          

    def execute_actions(self):
        try:
            if self.password and self.phone:
                if self.load_or_create_account_cache():
                    self.check_receive_qualification()
                elif self.password_login():
                    self.check_receive_qualification()
            elif self.token:
                self.check_receive_qualification()
            elif self.refresh_token:
                if self.refresh_token_action():
                    self.check_receive_qualification()
            else:
                log.error("❌ 无法识别账号类型，缺少必要凭证")

            self.get_tmp_token()

            if self.verified_token:
                self.get_cloud_phone_device()
                self.red_party()
                self.red_packet_account_info()
            
        except Exception as e:
            log.error(f"❌ 账号操作异常: {str(e)}")
            raise

if __name__ == "__main__":
    apis = ChinaMobileCloudPhoneAPI.from_env()
    log.info(f"\n📊 检测到{len(apis)}个账号")

    for idx, api in enumerate(apis, 1):
        log.info(f"\n{'='*14} 第{idx}个账号 {'='*14}")
        log.info(f"✅ {api.phone[:3] + '****' + api.phone[-4:] if api.phone else '这里有一只羊'}")
        api.execute_actions()

    push_content = (log_stream.getvalue().strip() + "\n\n" + "📢：脚本不要外传，仅限群内自用，否则不再分享")
    if push_content:
        sys.stdout = io.StringIO()
        send("中国移动云手机", push_content)
