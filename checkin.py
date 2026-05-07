#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2026 GLaDOS 自动签到 (排版修复版)
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
        res = self.req('GET', '/api/user/status')
        if res and 'data' in res:
            d = res['data']
            self.email = d.get('email', 'Unknown')
            self.left_days = str(d.get('leftDays', '?')).split('.')[0]
            return True
        return False

    def get_points(self):
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
            
            # 排序确保 100 -> 200 -> 500 顺序
            sorted_plans = sorted(plans.items(), key=lambda x: x[1]['points'])
            
            for plan_id, plan_data in sorted_plans:
                need = plan_data['points']
                days = plan_data['days']
                if pts >= need:
                    status = "✅"
                    desc = "(可兑换)"
                else:
                    status = "❌"
                    desc = f"(差{need-pts}分)"
                # 修复对齐：直接以符号开头，不加行首空格
                exchange_lines.append(f"{status} {need}分→{days}天 {desc}")
            
            self.exchange_info = "<br>".join(exchange_lines)
            return True
        return False

    def checkin(self):
        return self.req('POST', '/api/user/checkin', {'token': 'glados.cloud'})

    def exchange(self, plan):
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
        # 修复顶部空白：确保 title 和 content 之间紧凑连接
        text = f"<b>{title}</b>\n\n{content}".replace("<br>", "\n")
        # 清理多余的 HTML 标签和行首空格
        text = re.sub(r"<(?!\/?(b|i|u|s|a|code|pre)\b)[^>]+>", "", text)
        # 移除每一行行首的空格缩进，确保左对齐
        text = "\n".join([line.strip() for line in text.split("\n")])
        
        data = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
        requests.post(url, json=data, timeout=5)
        log("✅ Telegram 推送成功")
    except Exception as e:
        log(f"❌ Telegram 推送失败: {e}")

# ================= 主程序 =================

def main():
    log("🚀 GLaDOS Checkin Starting...")
    cookies = get_cookies()
    if not cookies: sys.exit(1)
    
    target_plan = os.environ.get("GLADOS_EXCHANGE_PLAN", "plan500")
    plan_requirements = {"plan100": 100, "plan200": 200, "plan500": 500}
    need_pts = plan_requirements.get(target_plan, 500)
    
    results = []
    success_cnt = 0
    
    for i, cookie in enumerate(cookies, 1):
        g = GLaDOS(cookie)
        res = g.checkin()
        msg = res.get('message', 'Failure') if res else "Network Error"
        
        g.get_status()
        g.get_points()
        
        exchange_msg = "未触发"
        try:
            current_pts = int(g.points)
            if current_pts >= need_pts:
                ex_res = g.exchange(target_plan)
                exchange_msg = ex_res.get('message', '提交失败')
                g.get_status()
                g.get_points()
            else:
                exchange_msg = f"积分不足 ({current_pts}/{need_pts})"
        except Exception as e:
            exchange_msg = f"错误: {e}"

        log(f"用户: {g.email} | 积分: {g.points} | 兑换: {exchange_msg}")
        if "Checkin" in msg: success_cnt += 1
        
        # HTML 模板去除冗余空格
        results.append(f"""<div style="border:1px solid #ddd; padding:10px; margin-bottom:10px;">
👤 {g.email}<br>
当前积分: {g.points} ({g.points_change})<br>
剩余天数: {g.left_days} 天<br>
签到结果: {msg}<br>
自动兑换: {exchange_msg}<br>
<br>
🎁 兑换进度:<br>
{g.exchange_info}
</div>""")

    ptoken = os.environ.get("PUSHPLUS_TOKEN")
    tg_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    tg_chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    
    if ptoken or (tg_token and tg_chat_id):
        # 确保标题前没有任何字符
        title = f"GLaDOS签到: 成功{success_cnt}/{len(cookies)}"
        # 移除 content 拼接时的前导换行
        content = "".join(results).strip() + f"<br>策略: {target_plan} | 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        if ptoken: pushplus(ptoken, title, content)
        if tg_token and tg_chat_id: telegram_push(tg_token, tg_chat_id, title, content)

if __name__ == '__main__':
    main()
