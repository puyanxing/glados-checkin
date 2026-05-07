#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2026 GLaDOS 自动签到 (积分增强 + 自动兑换)

功能：
- 全自动签到
- 精准获取当前积分 (Points)
- 自动积分兑换策略 (支持 100/200/500 档位)
- PushPlus / Telegram 微信推送
- 智能多域名切换
"""

import requests
import json
import os
import sys
import time
from datetime import datetime

# 修复 Windows Unicode 输出问题
if sys.platform.startswith('win'):
    sys.stdout.reconfigure(encoding='utf-8')

# ================= 配置 =================

# 域名优先级
DOMAINS = [
    "https://glados.cloud",
    "https://railgun.info",
    "https://glados.rocks",
    "https://glados.network",
]

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Content-Type': 'application/json;charset=UTF-8',
    'Accept': 'application/json, text/plain, */*',
}

# ================= 工具函数 =================

def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}")

def extract_cookie(raw: str):
    """提取 Cookie，支持多种格式"""
    if not raw: return None
    raw = raw.strip()
    if 'koa:sess=' in raw or 'koa:sess.sig=' in raw:
        return raw
    if raw.startswith('{'):
        try:
            return 'koa.sess=' + json.loads(raw).get('token')
        except: pass
    if raw.count('.') == 2 and '=' not in raw and len(raw) > 50:
        return 'koa:sess=' + raw
    return raw

def get_cookies():
    raw = os.environ.get("GLADOS_COOKIE", "")
    if not raw:
        log("❌ 未配置 GLADOS_COOKIE")
        return []
    sep = '\n' if '\n' in raw else '&'
    return [extract_cookie(c) for c in raw.split(sep) if c.strip()]

# ================= 核心逻辑 =================

class GLaDOS:
    def __init__(self, cookie):
        self.cookie = cookie
        self.domain = DOMAINS[0]
        self.email = "?"
        self.left_days = "?"
        self.points = "0"
        self.points_change = "?"
        self.exchange_info = ""
        
    def req(self, method, path, data=None):
        """带自动域名切换的请求"""
        for d in DOMAINS:
            try:
                url = f"{d}{path}"
                h = HEADERS.copy()
                h['Cookie'] = self.cookie
                h['Origin'] = d
                h['Referer'] = f"{d}/console/checkin"
                
                if method == 'GET':
                    resp = requests.get(url, headers=h, timeout=10)
                else:
                    resp = requests.post(url, headers=h, json=data, timeout=10)
                
                if resp.status_code == 200:
                    self.domain = d
                    return resp.json()
            except Exception as e:
                log(f"⚠️ {d} 请求失败: {e}")
                continue
        return None

    def get_status(self):
        """获取状态：天数、邮箱"""
        res = self.req('GET', '/api/user/status')
        if res and 'data' in res:
            d = res['data']
            self.email = d.get('email', 'Unknown')
            self.left_days = str(d.get('leftDays', '?')).split('.')[0]
            return True
        return False

    def get_points(self):
        """获取积分及兑换计划"""
        res = self.req('GET', '/api/user/points')
        if res and 'points' in res:
            self.points = str(res.get('points', '0')).split('.')[0]
            history = res.get('history', [])
            if history:
                last = history[0]
                change = str(last.get('change', '0')).split('.')[0]
                if not change.startswith('-'): change = '+' + change
                self.points_change = change
            
            plans = res.get('plans', {})
            pts = int(self.points)
            exchange_lines = []
            for plan_id, plan_data in plans.items():
                need = plan_data['points']
                days = plan_data['days']
                status = "✅ 可兑换" if pts >= need else f"❌ 差 {need-pts} 分"
                exchange_lines.append(f"{status} ({need}分→{days}天)")
            self.exchange_info = "<br>".join(exchange_lines)
            return True
        return False

    def checkin(self):
        """执行签到"""
        return self.req('POST', '/api/user/checkin', {'token': 'glados.cloud'})

    def exchange(self, plan):
        """执行积分兑换"""
        return self.req('POST', '/api/user/exchange', {'planType': plan})

# ================= 推送函数 =================

def pushplus(token, title, content):
    if not token: return
    try:
        url = "http://www.pushplus.plus/send"
        requests.get(url, params={'token': token, 'title': title, 'content': content, 'template': 'html'}, timeout=5)
        log("✅ PushPlus 推送成功")
    except:
        log("❌ PushPlus 推送失败")

def telegram_push(token, chat_id, title, content):
    if not token or not chat_id: return
    try:
        import re
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        text = f"<b>{title}</b>\n\n{content}".replace("<br>", "\n")
        text = re.sub(r"<(?!\/?(b|i|u|s|a|code|pre)\b)[^>]+>", "", text)
        data = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
        requests.post(url, json=data, timeout=5)
        log("✅ Telegram 推送成功")
    except Exception as e:
        log(f"❌ Telegram 推送失败: {e}")

# ================= 主程序 =================

def main():
    log("🚀 GLaDOS Checkin (Enhanced Edition) Starting...")
    cookies = get_cookies()
    if not cookies: sys.exit(1)
    
    # 获取兑换配置
    target_plan = os.environ.get("GLADOS_EXCHANGE_PLAN", "plan500")
    plan_requirements = {"plan100": 100, "plan200": 200, "plan500": 500}
    need_pts = plan_requirements.get(target_plan, 500)
    
    results = []
    success_cnt = 0
    
    for i, cookie in enumerate(cookies, 1):
        g = GLaDOS(cookie)
        
        # 1. 签到
        res = g.checkin()
        msg = res.get('message', 'Failure') if res else "Network Error"
        
        # 2. 刷新数据
        g.get_status()
        g.get_points()
        
        # 3. 自动兑换判断
        exchange_msg = "未触发"
        try:
            current_pts = int(g.points)
            if current_pts >= need_pts:
                log(f"💰 {g.email} 积分充足 ({current_pts}/{need_pts})，执行兑换...")
                ex_res = g.exchange(target_plan)
                exchange_msg = ex_res.get('message', '提交失败')
                # 兑换后再次刷新
                g.get_status()
                g.get_points()
            else:
                exchange_msg = f"积分不足 ({current_pts}/{need_pts})"
        except Exception as e:
            exchange_msg = f"错误: {e}"

        log(f"用户: {g.email} | 积分: {g.points} | 兑换: {exchange_msg} | 结果: {msg}")
        if "Checkin" in msg: success_cnt += 1
        
        # 4. HTML 模板更新
        results.append(f"""
<div style="border:2px solid #333; padding:15px; margin-bottom:15px; border-radius:10px; background:#fff;">
    <h3 style="margin:0 0 15px 0; color:#333; border-bottom:2px solid #333; padding-bottom:8px;">👤 {g.email}</h3>
    <p style="margin:8px 0; color:#000; font-size:16px;"><b>当前积分:</b> <span style="color:#e74c3c; font-size:22px; font-weight:bold;">{g.points}</span> <span style="color:#27ae60; font-weight:bold;">({g.points_change})</span></p>
    <p style="margin:8px 0; color:#000; font-size:16px;"><b>剩余天数:</b> <span style="font-weight:bold;">{g.left_days} 天</span></p>
    <p style="margin:8px 0; color:#000; font-size:16px;"><b>签到结果:</b> {msg}</p>
    <p style="margin:8px 0; color:#000; font-size:16px;"><b>自动兑换:</b> <span style="color:#2980b9; font-weight:bold;">{exchange_msg}</span></p>
    <div style="margin-top:15px; padding:12px; background:#f0f0f0; border-radius:8px; border:1px solid #ccc;">
        <p style="margin:0 0 8px 0; color:#333; font-weight:bold; font-size:15px;">🎁 兑换进度:</p>
        <p style="margin:0; color:#000; font-size:14px; line-height:1.8;">{g.exchange_info}</p>
    </div>
</div>
""")

    # 推送逻辑
    ptoken = os.environ.get("PUSHPLUS_TOKEN")
    tg_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    tg_chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    
    if ptoken or (tg_token and tg_chat_id):
        title = f"GLaDOS签到: 成功{success_cnt}/{len(cookies)}"
        content = "".join(results) + f"<br><small>策略: {target_plan} | 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</small>"
        if ptoken: pushplus(ptoken, title, content)
        if tg_token and tg_chat_id: telegram_push(tg_token, tg_chat_id, title, content)

if __name__ == '__main__':
    main()
