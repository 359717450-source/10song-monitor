#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
10Song Contact Page Monitor
SPA 页面，必须用 Playwright 渲染
"""

import os
import json
import hashlib
import re
import asyncio
import requests
from datetime import datetime

SENDKEY       = os.environ.get("SENDKEY", "")
BASELINE_FILE = os.environ.get("BASELINE_FILE", "baseline.json")
CONTACT_URL   = "https://10song.com/contact"

def log(msg):
    print(f"[{datetime.now()}] {msg}")

def compute_hash(name, budget, message):
    return hashlib.md5(f"{name}|{budget}|{message}".encode()).hexdigest()

def load_baseline():
    if os.path.exists(BASELINE_FILE):
        try:
            with open(BASELINE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                hashes = data.get("hashes", [])
                log(f"加载基线: {len(hashes)} 条历史留言")
                return set(hashes)
        except:
            pass
    log("基线不存在，首次运行")
    return set()

def save_baseline(hashes):
    data = {"updated_at": datetime.now().isoformat(), "hashes": list(hashes)}
    with open(BASELINE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def send_notify(messages):
    if not SENDKEY:
        log("⚠️ SENDKEY 未设置")
        return False
    text = f"🚨 10Song 发现 {len(messages)} 条新客户留言！"
    desp = "# 新客户留言\n\n"
    for m in messages:
        name = m.get("name","（未知）")
        budget = m.get("budget","")
        msg = m.get("message","")[:80]
        desp += f"## {name} | {budget}\n> {msg}\n\n---\n"
    try:
        resp = requests.post(
            f"https://sctapi.ftqq.com/{SENDKEY}.send",
            data={"text": text, "desp": desp}, timeout=15
        )
        if resp.json().get("code") == 0:
            log("微信推送: 成功 ✅")
            return True
        log(f"推送失败: {resp.json()}")
        return False
    except Exception as e:
        log(f"推送异常: {e}")
        return False

def parse_from_html(html):
    """从渲染后的 HTML 提取留言"""
    # 姓名：<h4 class="font-bold text-gray-900">王*生</h4>
    names = re.findall(r'<h4 class="font-bold text-gray-900">([^<]+)</h4>', html)
    # 留言：<p class="...line-clamp-3">"内容"</p>
    msgs  = re.findall(r'line-clamp-3">"([^"]*)"</p>', html)
    # 预算：<span class="text-sm font-semibold text-[#FF6B35]">5000-10000</span>
    budgets = re.findall(
        r'<span class="text-sm font-semibold text-$$#FF6B35$$">([^<]+)</span>', html
    )

    messages = []
    seen = set()
    for i in range(min(len(names), len(msgs), len(budgets))):
        name, budget, msg = names[i].strip(), budgets[i].strip(), msgs[i].strip()
        key = f"{name}|{budget}|{msg}"
        if key not in seen and name:
            seen.add(key)
            messages.append({"name": name, "budget": budget, "message": msg})
    return messages

async def fetch_with_browser():
    """用 Playwright 渲染页面并提取数据"""
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            args=["--no-sandbox", "--disable-setuid-sandbox"]
        )
        page = await browser.new_page()

        # 关键修复：用 domcontentloaded 替代 networkidle，避免超时
        log("打开页面...")
        await page.goto(CONTACT_URL, wait_until="domcontentloaded", timeout=30000)

        # 等待留言卡片渲染出来
        try:
            await page.wait_for_selector("h4.font-bold", timeout=15000)
            log("页面内容已渲染")
        except:
            log("⚠️ 等待超时，尝试直接获取内容")

        # 再等 3 秒确保动态数据加载完成
        await page.wait_for_timeout(3000)

        html = await page.content()
        await browser.close()
        return html

def main():
    log("开始监控...")

    try:
        html = asyncio.run(fetch_with_browser())
    except Exception as e:
        log(f"❌ 浏览器渲染失败: {e}")
        return

    messages = parse_from_html(html)

    if not messages:
        log("未解析到留言，本次跳过")
        return

    log(f"解析到 {len(messages)} 条客户留言: {[m['name'] for m in messages]}")

    current_hashes = {
        compute_hash(m["name"], m.get("budget",""), m.get("message",""))
        for m in messages
    }
    baseline_hashes = load_baseline()

    new_messages = [
        m for m in messages
        if compute_hash(m["name"], m.get("budget",""), m.get("message,""))
        not in baseline_hashes
    ]

    if not new_messages:
        log("No new messages detected. ✅")
        save_baseline(current_hashes)
        return

    log(f"🚨 发现 {len(new_messages)} 条新客户！")
    for m in new_messages:
        print(f"  - {m['name']} | {m.get('budget','')} | {m.get('message','')[:60]}...")

    ok = send_notify(new_messages)
    if ok:
        save_baseline(current_hashes)
        log(f"基线已更新，共 {len(current_hashes)} 条")
    else:
        log("推送失败，不更新基线")

if __name__ == "__main__":
    main()

