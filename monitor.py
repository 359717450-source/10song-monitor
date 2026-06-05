#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
10Song Contact Page Monitor
监视 10song.com/contact 页面的客户留言
页面是 React SSR 渲染，数据直接内嵌在 HTML 中
"""

import os
import json
import hashlib
import re
import requests
from datetime import datetime

# ── 配置 ──────────────────────────────────────────────────
SENDKEY      = os.environ.get("SENDKEY", "")
BASELINE_FILE = os.environ.get("BASELINE_FILE", "baseline.json")
CONTACT_URL  = "https://10song.com/contact"
# ───────────────────────────────────────────────────────────

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
                hashes = data.get("hashes", [])
                log(f"加载基线: {len(hashes)} 条历史留言")
                return set(hashes)
        except Exception as e:
            log(f"加载基线失败: {e}")
    log("基线文件不存在或为空，首次运行")
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
        resp = requests.post(url, data={"text": text, "desp": desp}, timeout=15)
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


def fetch_and_parse():
    """
    获取页面并解析留言。
    HTML 结构（React SSR 渲染，数据直接内嵌）：
      <h4 class="font-bold text-gray-900">NAME</h4>
      <p class="...line-clamp-3">"MESSAGE"</p>
      预算范围</span><span class="...text-[#FF6B35]">BUDGET</span>
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    resp = requests.get(CONTACT_URL, headers=headers, timeout=30)
    resp.raise_for_status()
    html = resp.text

    # 提取姓名（在 h4 标签中）
    names = re.findall(r'<h4 class="font-bold text-gray-900">([^<]+)</h4>', html)
    # 提取留言内容（在 <p class="...line-clamp-3">"..."</p> 中）
    msgs  = re.findall(r'line-clamp-3">"([^"]*)"</p>', html)
    # 提取预算（在 "预算范围</span><span ...>BUDGET</span>" 中）
    budgets = re.findall(
        r'预算范围</span><span class="text-sm font-semibold text-$$#FF6B35$$">([^<]+)</span>',
        html
    )

    messages = []
    seen = set()
    for i in range(min(len(names), len(msgs), len(budgets))):
        name   = names[i].strip()
        budget = budgets[i].strip()
        msg    = msgs[i].strip()
        key    = f"{name}|{budget}|{msg}"
        if key not in seen and name:
            seen.add(key)
            messages.append({"name": name, "budget": budget, "message": msg})

    return messages


def main():
    log("开始监控...")
    messages = fetch_and_parse()

    if not messages:
        log("未解析到留言，本次跳过")
        # 保持现有基线不变（不保存空基线，避免下次全部推送）
        return

    log(f"解析到 {len(messages)} 条客户留言: {[m['name'] for m in messages]}")

    current_hashes  = {compute_hash(m["name"], m.get("budget",""), m.get("message","")) for m in messages}
    baseline_hashes = load_baseline()

    new_messages = [
        m for m in messages
        if compute_hash(m["name"], m.get("budget",""), m.get("message","")) not in baseline_hashes
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
        log("推送失败，不更新基线，下次重试")


if __name__ == "__main__":
    main()

