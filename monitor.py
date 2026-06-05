#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
10Song Contact Page Monitor
监视 10song.com/contact 页面的客户留言，有新留言时通过 Server酱 推送微信通知
使用 Playwright 渲染 SPA 页面
"""

import os
import json
import hashlib
import asyncio
import requests
from datetime import datetime

# ── 配置 ─────────────────────────────────────────────────────
SENDKEY      = os.environ.get("SENDKEY", "")
BASELINE_FILE = os.environ.get("BASELINE_FILE", "baseline.json")
CONTACT_URL  = "https://10song.com/contact"
TIMEOUT      = 30
# ───────────────────────────────────────────────────────────────

def log(msg):
    print(f"[{datetime.now()}] {msg}")


def compute_hash(name, budget, message):
    key = f"{name}|{budget}|{message}"
    return hashlib.md5(key.encode("utf-8")).hexdigest()


def load_baseline():
    if os.path.exists(BASELINE_FILE):
        try:
            with open(BASELINE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return set(data.get("hashes", []))
        except Exception:
            pass
    return set()


def save_baseline(hashes):
    data = {"updated_at": datetime.now().isoformat(), "hashes": list(hashes)}
    with open(BASELINE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def send_notify(messages):
    if not SENDKEY:
        log("⚠️ SENDKEY 未设置，跳过推送")
        return False
    text = f"🚨 10Song 发现 {len(messages)} 条新客户留言！"
    desp = "# 新客户留言\n\n"
    for m in messages:
        name   = m.get("name", "（未知）")
        budget = m.get("budget", "")
        msg    = m.get("message", "")[:80]
        desp += f"## {name} | {budget}\n> {msg}\n\n---\n"
    url = f"https://sctapi.ftqq.com/{SENDKEY}.send"
    try:
        resp = requests.post(url, data={"text": text, "desp": desp}, timeout=TIMEOUT)
        result = resp.json()
        if result.get("code") == 0:
            log("微信推送: 成功 ✅")
            return True
        else:
            log(f"微信推送失败: {result}")
            return False
    except Exception as e:
        log(f"微信推送异常: {e}")
        return False


def parse_page_with_playwright():
    """用 Playwright 渲染 SPA 页面并解析留言"""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        log("❌ Playwright 未安装")
        return []

    messages = []

    async def _run():
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                args=["--no-sandbox", "--disable-setuid-sandbox"]
            )
            page = await browser.new_page()
            log(f"打开页面: {CONTACT_URL}")
            await page.goto(CONTACT_URL, wait_until="networkidle", timeout=TIMEOUT * 1000)
            # 等待 SPA 渲染完成
            await page.wait_for_timeout(3000)

            # 尝试从页面中提取留言数据
            # 方法1: 从匿名客户提交记录区提取
            log("开始解析页面留言...")

            # 提取所有留言块 —— 根据实际页面结构调整选择器
            # 尝试多种可能的选择器
            selectors_to_try = [
                ".contact-message", ".message-item", ".submission-item",
                "[class*='message']", "[class*='contact']", "[class*='submit']",
                "td", "tr", ".ant-table-cell"
            ]

            found = False
            for sel in selectors_to_try:
                items = await page.query_selector_all(sel)
                if items and len(items) > 0:
                    log(f"  找到选择器 {sel}: {len(items)} 个元素")
                    for item in items[:20]:  # 最多取前20条
                        text = await item.inner_text()
                        if text and len(text.strip()) > 5:
                            # 尝试提取姓名、预算、消息
                            lines = [l.strip() for l in text.split("\n") if l.strip()]
                            if len(lines) >= 1:
                                messages.append({
                                    "name":    lines[0][:20],
                                    "budget":  lines[1] if len(lines) > 1 else "",
                                    "message": lines[2] if len(lines) > 2 else text[:100]
                                })
                                found = True
                    if found:
                        break

            # 方法2: 从页面 HTML 中正则提取
            if not messages:
                html = await page.content()
                import re
                # 匹配匿名提交记录中的姓名模式（脱敏：王*生、邱* 等）
                name_pattern = r"([\u4e00-\u9fa5]\*[\u4e00-\u9fa5])"
                names = re.findall(name_pattern, html)
                if names:
                    log(f"  正则提取到姓名: {names[:10]}")
                    for n in names[:20]:
                        messages.append({"name": n, "budget": "", "message": ""})

            # 方法3: 执行 JS 直接读页面数据
            if not messages:
                try:
                    js_data = await page.evaluate("""
                        () => {
                            // 尝试读 React/Vue 渲染后的 DOM 文本
                            const texts = [];
                            document.querySelectorAll('*').forEach(el => {
                                const t = el.innerText || el.textContent;
                                if (t && t.length > 3 && t.length < 100 && /[\u4e00-\u9fa5]/.test(t)) {
                                    texts.push(t.trim());
                                }
                            });
                            return texts.slice(0, 50);
                        }
                    """)
                    if js_data:
                        log(f"  JS提取到 {len(js_data)} 段文本")
                        for t in js_data[:20]:
                            if any(c in t for c in ['*', '¥', '预算', '拍摄']):
                                messages.append({"name": t[:20], "budget": "", "message": t[:100]})
                except Exception as e:
                    log(f"  JS提取失败: {e}")

            await browser.close()
            log(f"解析完成，共 {len(messages)} 条留言")
            return messages

    return asyncio.get_event_loop().run_until_complete(_run())


def main():
    log("开始监控...")
    messages = parse_page_with_playwright()

    if not messages:
        log("未解析到留言（可能是页面结构变化），本次跳过")
        return

    log(f"解析到 {len(messages)} 条客户留言: {[m['name'] for m in messages]}")
    current_hashes = {compute_hash(m["name"], m.get("budget",""), m.get("message","")) for m in messages}
    baseline_hashes = load_baseline()

    new_messages = [m for m in messages if compute_hash(m["name"], m.get("budget",""), m.get("message","")) not in baseline_hashes]

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
        log("推送失败，不更新基线，下次重试")


if __name__ == "__main__":
    main()
