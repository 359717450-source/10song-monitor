#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
10Song Contact Page Monitor
SPA 页面，必须用 Playwright 渲染
"""

import os, json, hashlib, re, asyncio, requests
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


def parse_submissions(html):
    """
    多策略解析提交记录。
    每条卡片结构：h4(姓名) + p.line-clamp-3(留言) + span.text-[#FF6B35](预算)
    """
    messages = []

    # 策略1: 精确 class 名匹配
    names   = re.findall(r'<h4 class="font-bold text-gray-900">([^<]+)</h4>', html)
    msgs    = re.findall(r'line-clamp-3">"([^"]*)"</p>', html)
    budgets = re.findall(
        r'<span class="text-sm font-semibold text-$$#FF6B35$$">([^<]+)</span>', html
    )

    log(f"  策略1: names={len(names)} msgs={len(msgs)} budgets={len(budgets)}")

    if names and msgs and budgets:
        seen = set()
        for i in range(min(len(names), len(msgs), len(budgets))):
            n, b, m = names[i].strip(), budgets[i].strip(), msgs[i].strip()
            key = f"{n}|{b}|{m}"
            if key not in seen and n:
                seen.add(key)
                messages.append({"name": n, "budget": b, "message": m})
        if messages:
            return messages

    # 策略2: 宽松匹配（类名可能顺序不同）
    names   = re.findall(r'<h4[^>]*class="[^"]*\bfont-bold\b[^"]*\btext-gray-900\b[^"]*"[^>]*>([^<]+)</h4>', html)
    if not names:
        names = re.findall(r'<h4[^>]*class="[^"]*\btext-gray-900\b[^"]*\bfont-bold\b[^"]*"[^>]*>([^<]+)</h4>', html)
    msgs    = re.findall(r'<p[^>]*class="[^"]*\bline-clamp-3\b[^"]*"[^>]*>"([^"]*)"</p>', html)
    budgets = re.findall(r'<span[^>]*class="[^"]*\btext-$$#FF6B35$$\b[^"]*"[^>]*>([^<]+)</span>', html)

    log(f"  策略2: names={len(names)} msgs={len(msgs)} budgets={len(budgets)}")

    if names and msgs and budgets:
        seen = set()
        for i in range(min(len(names), len(msgs), len(budgets))):
            n, b, m = names[i].strip(), budgets[i].strip(), msgs[i].strip()
            key = f"{n}|{b}|{m}"
            if key not in seen and n:
                seen.add(key)
                messages.append({"name": n, "budget": b, "message": m})
        if messages:
            return messages

    # 策略3: 按「提交信息记录」区块过滤后，提取所有 h4 + line-clamp + FF6B35
    section = html
    if "提交信息记录" in html:
        idx = html.index("提交信息记录")
        section = html[idx:idx + 30000]  # 只在提交记录区块内搜索

    names   = re.findall(r'<h4[^>]*>([^<]{2,10})</h4>', section)
    # 过滤：只保留包含 * 或看起来像中文名的（排除「联系电话」等标签）
    names   = [n for n in names if ('*' in n or re.match(r'^[\u4e00-\u9fa5]{2,4}$', n))]

    msgs    = re.findall(r'line-clamp[^>]*>"([^"]*)"</p>', section)
    budgets = re.findall(r'#[A-F0-9]{6}[^>]*>([\d-]+)</span>', section)

    log(f"  策略3: names={names} msgs={len(msgs)} budgets={budgets}")

    if names and msgs and budgets:
        seen = set()
        for i in range(min(len(names), len(msgs), len(budgets))):
            n, b, m = names[i].strip(), budgets[i].strip(), msgs[i].strip()
            key = f"{n}|{b}|{m}"
            if key not in seen and n:
                seen.add(key)
                messages.append({"name": n, "budget": b, "message": m})

    return messages


async def fetch_with_browser():
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            args=["--no-sandbox", "--disable-setuid-sandbox"]
        )
        page = await browser.new_page()
        log("打开页面...")
        await page.goto(CONTACT_URL, wait_until="domcontentloaded", timeout=30000)
        try:
            await page.wait_for_selector("h4.font-bold", timeout=15000)
            log("页面内容已渲染")
        except:
            log("⚠️ 等待超时，尝试直接获取内容")
        await page.wait_for_timeout(3000)
        html = await page.content()

        # 调试：保存前 8000 字符的关键区域
        if "提交信息记录" in html:
            idx = html.index("提交信息记录")
            debug_html = html[idx:idx+5000]
        else:
            debug_html = html[:5000]
        log(f"HTML 片段（前200字符）: {debug_html[:200]}")

        await browser.close()
        return html


def main():
    log("开始监控...")
    try:
        html = asyncio.run(fetch_with_browser())
    except Exception as e:
        log(f"❌ 浏览器渲染失败: {e}")
        return

    messages = parse_submissions(html)

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
        if compute_hash(m["name"], m.get("budget",""), m.get("message",""))
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

