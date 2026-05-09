#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GLaDOS / Railgun 自动签到
适配 railgun.info
"""

import requests
import json
import os
import sys
from datetime import datetime

# 修复 Windows Unicode 输出问题
if sys.platform.startswith('win'):
    sys.stdout.reconfigure(encoding='utf-8')

# ================= 配置 =================

DOMAINS = [
    "https://railgun.info",
    "https://glados.cloud",
    "https://glados.rocks",
    "https://glados.network",
]

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Content-Type': 'application/json;charset=UTF-8',
    'Accept': 'application/json, text/plain, */*',
    'X-Requested-With': 'XMLHttpRequest',
}

DEBUG = os.environ.get("GLADOS_DEBUG", "1") == "1"

# ================= 工具函数 =================

def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}")


def mask_cookie(cookie: str):
    if not cookie:
        return ""
    if len(cookie) <= 20:
        return "***"
    return cookie[:12] + "..." + cookie[-8:]


def extract_cookie(raw: str):
    """
    支持以下格式：
    1. koa:sess=xxx; koa:sess.sig=yyy
    2. 单独 token
    3. JSON: {"token": "..."}
    """
    if not raw:
        return None

    raw = raw.strip()

    # 如果 GitHub Secrets 里误加了外层引号，自动去掉
    if (raw.startswith('"') and raw.endswith('"')) or (raw.startswith("'") and raw.endswith("'")):
        raw = raw[1:-1].strip()

    # 完整 Cookie
    if 'koa:sess=' in raw or 'koa:sess.sig=' in raw:
        return raw

    # JSON 格式
    if raw.startswith('{'):
        try:
            token = json.loads(raw).get('token')
            if token:
                return 'koa:sess=' + token
        except Exception:
            pass

    # 仅 token
    if raw.count('.') == 2 and '=' not in raw and len(raw) > 50:
        return 'koa:sess=' + raw

    return raw


def get_cookies():
    raw = os.environ.get("GLADOS_COOKIE", "")

    if not raw:
        log("❌ 未配置 GLADOS_COOKIE")
        return []

    log(f"读取到 GLADOS_COOKIE，长度: {len(raw)}，开头: {raw[:20]}")

    # 多账号请用换行分隔，不要用 & 分隔，避免 Cookie 被误拆
    cookies = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        cookie = extract_cookie(line)
        if cookie:
            cookies.append(cookie)

    # 如果没有换行，splitlines 仍然会返回一整行，所以这里正常
    log(f"共读取到 {len(cookies)} 个账号 Cookie")

    for i, c in enumerate(cookies, 1):
        log(f"账号 {i} Cookie: {mask_cookie(c)}")

    return cookies


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
        self.status_ok = False

    def req(self, method, path, data=None):
        for d in DOMAINS:
            try:
                url = f"{d}{path}"

                h = HEADERS.copy()
                h['Cookie'] = self.cookie
                h['Origin'] = d
                h['Referer'] = f"{d}/console/checkin"

                if method.upper() == 'GET':
                    resp = requests.get(url, headers=h, timeout=15)
                else:
                    resp = requests.post(url, headers=h, json=data, timeout=15)

                if resp.status_code == 200:
                    self.domain = d
                    try:
                        js = resp.json()
                        if DEBUG:
                            log(f"✅ {method.upper()} {d}{path} 返回: {str(js)[:500]}")
                        return js
                    except Exception:
                        log(f"⚠️ {method.upper()} {d}{path} 返回不是 JSON: {resp.text[:500]}")
                else:
                    log(f"⚠️ {method.upper()} {d}{path} 状态码: {resp.status_code}, 返回: {resp.text[:500]}")

            except Exception as e:
                log(f"⚠️ {method.upper()} {d}{path} 请求失败: {e}")
                continue

        return None

    def get_status(self):
        res = self.req('GET', '/api/user/status')

        if not res:
            log("❌ 获取用户状态失败：无返回")
            return False

        if 'data' not in res:
            log(f"❌ 获取用户状态失败，返回内容: {str(res)[:500]}")
            return False

        d = res.get('data') or {}

        self.email = d.get('email', 'Unknown')
        self.left_days = str(d.get('leftDays', '?')).split('.')[0]
        self.status_ok = True

        return True

    def get_points(self):
        res = self.req('GET', '/api/user/points')

        if not res:
            log("❌ 获取积分失败：无返回")
            return False

        if 'points' not in res:
            log(f"❌ 获取积分失败，返回内容: {str(res)[:500]}")
            return False

        self.points = str(res.get('points', '0')).split('.')[0]

        history = res.get('history', [])
        if history:
            last = history[0]
            change = str(last.get('change', '0')).split('.')[0]
            if not change.startswith('-'):
                change = '+' + change
            self.points_change = change

        plans = res.get('plans', {})
        pts = int(self.points) if str(self.points).isdigit() else 0

        exchange_lines = []

        try:
            sorted_plans = sorted(plans.items(), key=lambda x: x[1].get('points', 0))

            for plan_id, plan_data in sorted_plans:
                need = int(plan_data.get('points', 0))
                days = plan_data.get('days', '?')
                status = "✅" if pts >= need else "❌"
                desc = "(可兑换)" if pts >= need else f"(差{need - pts}分)"
                exchange_lines.append(f"{status} {need}分→{days}天 {desc}")

            self.exchange_info = "\n".join(exchange_lines) if exchange_lines else "暂无兑换选项"

        except Exception as e:
            self.exchange_info = f"兑换选项解析失败: {e}"

        return True

    def checkin(self):
        return self.req('POST', '/api/user/checkin', {'token': 'railgun.info'})

    def exchange(self, plan):
        return self.req('POST', '/api/user/exchange', {'planType': plan})


# ================= 推送函数 =================

def telegram_push(token, chat_id, title, content):
    if not token or not chat_id:
        return

    try:
        import re

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        text = f"<b>{title}</b>\n\n{content}"

        # 只保留 <b> 标签，避免 Telegram HTML 解析失败
        text = re.sub(r"<(?!\/?(b)\b)[^>]+>", "", text)

        data = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }

        resp = requests.post(url, json=data, timeout=10)

        if resp.status_code == 200:
            log("✅ Telegram 推送成功")
        else:
            log(f"❌ Telegram 推送失败: {resp.status_code}, {resp.text[:300]}")

    except Exception as e:
        log(f"❌ Telegram 推送失败: {e}")


# ================= 主程序 =================

def main():
    log("🚀 Railgun / GLaDOS Checkin Starting...")

    cookies = get_cookies()

    if not cookies:
        sys.exit(1)

    target_plan = os.environ.get("GLADOS_EXCHANGE_PLAN", "plan500")

    plan_requirements = {
        "plan100": 100,
        "plan200": 200,
        "plan500": 500,
    }

    need_pts = plan_requirements.get(target_plan, 500)

    results = []
    success_cnt = 0

    for idx, cookie in enumerate(cookies, 1):
        log(f"========== 开始处理账号 {idx} ==========")

        g = GLaDOS(cookie)

        # 先获取状态，如果这里失败，说明 Cookie 登录态有问题
        status_ok = g.get_status()

        # 获取积分
        points_ok = g.get_points()

        # 执行签到
        checkin_res = g.checkin()

        raw_msg = checkin_res.get('message', 'Failure') if checkin_res else "Network Error"

        # 判断今日是否已经签到成功
        if "Checkin" in raw_msg or "observation logged" in raw_msg:
            success_cnt += 1
            msg = "Today's observation logged. Return tomorrow for more points."
        else:
            msg = raw_msg

        # 签到后重新获取状态和积分
        g.get_status()
        g.get_points()

        # 自动兑换
        current_pts = int(g.points) if str(g.points).isdigit() else 0
        exchange_msg = f"积分不足 ({current_pts}/{need_pts})"

        if current_pts >= need_pts:
            ex_res = g.exchange(target_plan)
            exchange_msg = ex_res.get('message', '提交失败') if ex_res else "兑换请求失败"

            # 兑换后刷新信息
            g.get_status()
            g.get_points()

        if not status_ok:
            status_note = "⚠️ 无法获取邮箱和剩余天数，请检查 railgun.info Cookie 是否有效"
        else:
            status_note = "正常"

        user_result = (
            f"👤 {g.email}\n\n"
            f"状态: {status_note}\n\n"
            f"当前积分: {g.points} ({g.points_change})\n\n"
            f"剩余天数: {g.left_days} 天\n\n"
            f"签到结果: {msg}\n\n"
            f"自动兑换: {exchange_msg}\n\n"
            f"🎁 兑换选项:\n\n"
            f"{g.exchange_info}"
        )

        results.append(user_result)

    tg_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    tg_chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    title = f"GLaDOS签到: 成功{success_cnt}/{len(cookies)}"
    cur_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    content = "\n\n".join(results) + f"\n\n策略: {target_plan} | 时间: {cur_time}"

    log("========== 运行结果 ==========")
    log(title)
    print(content)

    if tg_token and tg_chat_id:
        telegram_push(tg_token, tg_chat_id, title, content)


if __name__ == '__main__':
    main()
    
    for cookie in cookies:
        g = GLaDOS(cookie)
        checkin_res = g.checkin()
        g.get_status()
        g.get_points()
        
        # --- 核心判定逻辑修改 ---
        raw_msg = checkin_res.get('message', 'Failure') if checkin_res else "Network Error"
        
        # 只要 message 包含 "Checkin" (首次成功) 或 "observation logged" (今日已签到)
        # 都代表今日已经签到成功了，标题显示 1/1
        if "Checkin" in raw_msg or "observation logged" in raw_msg:
            success_cnt += 1
            msg = "Today's observation logged. Return tomorrow for more points."
        else:
            msg = raw_msg

        current_pts = int(g.points)
        exchange_msg = f"积分不足 ({current_pts}/{need_pts})"
        if current_pts >= need_pts:
            ex_res = g.exchange(target_plan)
            exchange_msg = ex_res.get('message', '提交失败')
            g.get_status()
            g.get_points()

        # 保持要求的全空行排版
        user_result = (
            f"👤 {g.email}\n\n"
            f"当前积分: {g.points} ({g.points_change})\n\n"
            f"剩余天数: {g.left_days} 天\n\n"
            f"签到结果: {msg}\n\n"
            f"自动兑换: {exchange_msg}\n\n"
            f"🎁 兑换选项:\n\n"
            f"{g.exchange_info}"
        )
        results.append(user_result)

    tg_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    tg_chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    
    if tg_token and tg_chat_id:
        # 此时 success_cnt 代表今天已经完成签到的账号数量
        title = f"GLaDOS签到: 成功{success_cnt}/{len(cookies)}"
        cur_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        content = "\n\n".join(results) + f"\n\n策略: {target_plan} | 时间: {cur_time}"
        telegram_push(tg_token, tg_chat_id, title, content)

if __name__ == '__main__':
    main()
