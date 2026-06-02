#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
10song.com 联系页面客户留言监控
- 使用 Playwright 浏览器 SPA 页面
- 对比基线检测新客户
- 通过 Server酱 推送微信通知
"""

import json
import os
import re
import requests
from datetime import datetime

SENDKEY = os.environ.get("SENDKEY", "SCT353652Ts1TsOQBCzCHq8YgWX6Vxd0a3")
CONTACT_URL = "https://www.10song.com/contact"
BASELINE_FILE = os.environ.get("BASELINE_FILE", "baseline.json")


def load_baseline():
    """加载基线数据，不存在则返回空列表（首次运行）"""
    if os.path.exists(BASELINE_FILE):
        with open(BASELINE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []


def save_baseline(data):
    with open(BASELINE_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def fetch_page_content():
    """使用 Playwright 浏览器 SPA 页面，适配 GitHub Actions 网络环境"""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        # 启动 chromium，禁沙箱（GitHub Actions 需要）
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        page = browser.new_page()

        # 加载页面，不等待 networkidle（SPA 页面可能永远不 idle）
        try:
            page.goto(CONTACT_URL, timeout=60000, wait_until="domcontentloaded")
        except Exception as e:
            print(f"页面加载超时（已忽略）: {e}")

        # 等待语言切换按钮出现
        page.wait_for_timeout(3000)

        # 切换到中文
        try:
            # 尝试点击语言下拉框
            combobox = page.locator('[role="combobox"]')
            if combobox.count() > 0:
                combobox.first.click()
                page.wait_for_timeout(800)
                cn = page.locator('text=简体中文')
                if cn.count() > 0:
                    cn.first.click()
                    page.wait_for_timeout(3000)
            else:
                # 尝试 select 元素
                select = page.locator('select')
                if select.count() > 0:
                    select.first.select_option(label="简体中文")
                    page.wait_for_timeout(3000)
        except Exception as e:
            print(f"中文切换失败（已忽略）: {e}")

        # 获取页面文本内容
        text_content = page.inner_text("body")
        browser.close()
        return text_content


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

        # 检测客户名（含 * 号模糊标记，且长度合理）
        if ('*' in line or '+' in line or '（' in line) and len(line) < 20:
            # 如果已经有 current_name，保存上一条
            if current_name and current_message:
                entries.append({"name": current_name, "budget": current_budget or "N/A", "message": current_message})
            elif current_name:
                pass
            current_name = line
            current_budget = None
            current_message = None
            continue

        # 检测预算（数字-数字，范围合理）
        budget_match = re.search(r'(\d{3,5})\s*[-–—]\s*(\d{3,5})', line)
        if budget_match and current_name and not current_budget:
            low, high = int(budget_match.group(1)), int(budget_match.group(2))
            if 100 <= low <= 100000 and 100 <= high <= 100000:
                current_budget = f"{low}-{high}"
                continue

        # 检测消息（引号内容，50字以上更可能是客户留言）
        msg_match = re.search(r'[""\u300c](.{10,}?)[""\u300d\'\u201d]', line)
        if msg_match and current_name and not current_message:
            current_message = msg_match.group(1)
            continue

        # 如果是"今天"/"Today"等时间标记，跳过
        if line in ('今天', 'Today', '昨天', 'Yesterday'):
            continue

    # 循环结束后保存最后一条
    if current_name and current_message:
        entries.append({"name": current_name, "budget": current_budget or "N/A", "message": current_message})

    # 去重（同一个人只保留第一条）
    seen = set()
    unique = []
    for e in entries:
        if e["name"] not in seen:
            seen.add(e["name"])
            unique.append(e)
    return unique


def find_new_entries(current, baseline):
    baseline_names = {e["name"] for e in baseline}
    return [e for e in current if e["name"] not in baseline_names]


def push_to_wechat(new_entries):
    title = f"🚨 10song新客户提醒 ({len(new_entries)}条)"
    desc = [f"## 发现 {len(new_entries)} 条新客户留言\n"]
    for i, e in enumerate(new_entries, 1):
        desc.append(f"### 客户 {i}")
        desc.append(f"- **昵称**：{e['name']}")
        desc.append(f"- **预算**：¥{e['budget']}")
        desc.append(f"- **需求**：{e['message']}")
        desc.append("")
    desc.append(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    desc.append("🔗 https://www.10song.com/contact")

    try:
        resp = requests.post(
            f"https://sctapi.ftqq.com/{SENDKEY}.send",
            data={"title": title, "desp": "\n".join(desc)},
            timeout=15
        )
        result = resp.json()
        if result.get("code") == 0:
            print("微信推送成功")
            return True
        else:
            print(f"微信推送失败: {result}")
            return False
    except Exception as ex:
        print(f"推送异常: {ex}")
        return False


def main():
    print(f"[{datetime.now()}] 开始监控...")

    text = fetch_page_content()
    entries = parse_entries_from_text(text)
    print(f"解析到 {len(entries)} 条客户留言: {[e['name'] for e in entries]}")

    if not entries:
        print("⚠️ 未解析到客户条目，请检查页面结构")
        return

    baseline = load_baseline()

    # 首次运行：基线为空，静默初始化基线（不发通知）
    if not baseline:
        print(f"🆕 首次运行，将 {len(entries)} 条记录设为基线")
        save_baseline(entries)
        print("基线初始化完成，下次运行开始正式监控")
        return

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
        print(f"✅ 暂无新提交，当前 {len(entries)} 条: {[e['name'] for e in entries]}")


if __name__ == "__main__":
    main()
