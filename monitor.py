#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
10song.com 联系页面客户留言监控
- 使用 Playwright 渲染 SPA 页面
- 对比基线检测新客户
- 通过 Server酱 推送微信通知
"""

import json
import os
import re
import requests
from datetime import datetime

SENDKEY = os.environ.get("SENDKEY", "SCT353652TslTsOQBCzCHq8YgWX6Vxd0a3")
CONTACT_URL = "https://www.10song.com/contact"
BASELINE_FILE = os.environ.get("BASELINE_FILE", "baseline.json")

INITIAL_BASELINE = [
    {"name": "周*欧", "budget": "3000-5000", "message": "可以拍护肤品白底图吗？需要精修，可能要拍40张，总共10个产品，也就是每个产品拍四张不同角度图，麻烦尽快联系我吧"},
    {"name": "刘*生", "budget": "10000-30000", "message": "最近我需要拍化妆品，高端效果，有5套，包含详情页制作，请问预算够吗？"},
    {"name": "孙*生", "budget": "5000-10000", "message": "我需要拍鞋子，120件，这周可以拍吗？"},
    {"name": "耿*士", "budget": "3000-5000", "message": "我是服装卖家，每个月需要拍50多套衣服，就在上海，希望尽快联系我哦"},
    {"name": "李*生", "budget": "5000-10000", "message": "我有一些金属类的产品需要拍摄。量很大，希望可以优惠一些"},
    {"name": "金*", "budget": "10000-30000", "message": "可以拍餐具吗？大约20件，需要白底图和场景图模特图。"},
]


def load_baseline():
    if os.path.exists(BASELINE_FILE):
        with open(BASELINE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return INITIAL_BASELINE.copy()


def save_baseline(data):
    with open(BASELINE_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def fetch_page_content():
    """使用 Playwright 渲染 SPA 页面"""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(CONTACT_URL, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(2000)

        # 切换到中文
        try:
            lang_btn = page.locator('select, [role="combobox"]').first
            if lang_btn:
                lang_btn.click()
                page.wait_for_timeout(500)
                cn_option = page.locator('text=简体中文')
                if cn_option.count() > 0:
                    cn_option.first.click()
                    page.wait_for_timeout(2000)
        except:
            pass  # 中文切换失败也不影响

        # 获取页面文本内容
        content = page.content()
        text_content = page.inner_text("body")
        browser.close()
        return text_content, content


def parse_entries_from_text(text):
    """从页面文本中解析客户条目"""
    entries = []
    lines = text.split('\n')

    in_section = False
    current_name = None
    current_budget = None
    current_message = None

    for line in lines:
        line = line.strip()
        if not line:
            continue

        if '提交信息记录' in line or 'Client Say' in line:
            in_section = True
            continue

        if in_section and ('为保护客户隐私' in line or 'anonymized' in line):
            if current_name:
                entries.append({"name": current_name, "budget": current_budget or "N/A", "message": current_message or ""})
            break

        if not in_section:
            continue

        # 检测是否在"预算范围"之后出现新的客户名
        # 客户名通常含 *（脱敏标记）
        if ('*' in line or '＊' in line) and current_budget:
            # 上一条结束，保存
            if current_name:
                entries.append({"name": current_name, "budget": current_budget or "N/A", "message": current_message or ""})
            current_name = line
            current_budget = None
            current_message = None
            continue

        # 如果还没设名字且含*，可能是第一个客户名
        if not current_name and ('*' in line or '＊' in line) and len(line) < 20:
            current_name = line
            continue

        # 检测预算
        budget_match = re.search(r'(\d+[\s]*[-–—][\s]*\d+)', line)
        if budget_match and current_name and not current_budget:
            # 排除太大或太小的数字（不是预算）
            val = budget_match.group(1).replace(' ', '')
            parts = val.split('-') if '-' in val else val.split('–')
            if len(parts) == 2:
                try:
                    low, high = int(parts[0]), int(parts[1])
                    if 100 <= low <= 100000 and 100 <= high <= 100000:
                        current_budget = val
                        continue
                except:
                    pass

        # 检测消息（引号内容）
        msg_match = re.search(r'["""](.+?)["""]', line)
        if msg_match and current_name and not current_message:
            current_message = msg_match.group(1)
            continue

        # 如果是"今天"/"Today"等时间标记，跳过
        if line in ('今天', 'Today', '昨天', 'Yesterday'):
            continue

    if current_name:
        entries.append({"name": current_name, "budget": current_budget or "N/A", "message": current_message or ""})

    return entries


def find_new_entries(current, baseline):
    baseline_names = {e["name"] for e in baseline}
    return [e for e in current if e["name"] not in baseline_names]


def push_to_wechat(new_entries):
    title = f"🚨 10song新客户提醒 ({len(new_entries)}条)"
    desp = [f"## 发现 {len(new_entries)} 条新客户咨询\n"]
    for i, e in enumerate(new_entries, 1):
        desp.append(f"### 客户 {i}")
        desp.append(f"- **姓名**：{e['name']}")
        desp.append(f"- **预算**：¥{e['budget']}")
        desp.append(f"- **需求**：{e['message']}")
        desp.append("")
    desp.append(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    desp.append("🔗 https://www.10song.com/contact")

    try:
        resp = requests.post(
            f"https://sctapi.ftqq.com/{SENDKEY}.send",
            data={"title": title, "desp": "\n".join(desp)},
            timeout=10
        )
        return resp.json().get("code") == 0
    except Exception as ex:
        print(f"推送失败: {ex}")
        return False


def main():
    print(f"[{datetime.now()}] 开始监控...")

    text, html = fetch_page_content()
    entries = parse_entries_from_text(text)
    print(f"解析到 {len(entries)} 条客户留言")

    if not entries:
        print("⚠️ 未解析到客户条目")
        return

    baseline = load_baseline()
    new = find_new_entries(entries, baseline)

    if new:
        print(f"🚨 发现 {len(new)} 条新客户！")
        for e in new:
            print(f"  - {e['name']} | ¥{e['budget']} | {e['message'][:40]}...")
        ok = push_to_wechat(new)
        print(f"微信推送: {'成功' if ok else '失败'}")
        baseline.extend(new)
        save_baseline(baseline)
        print(f"基线已更新，共 {len(baseline)} 条")
    else:
        print(f"✅ 暂无新提交，当前 {len(entries)} 条")


if __name__ == "__main__":
    main()
