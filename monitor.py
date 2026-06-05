#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
10Song Contact Page Monitor
监视 10song.com/contact 页面的客户留言
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
                return set(data.get("hashes", []))
        except Exception as e:
            log(f"加载基线失败: {e}")
    return set()


def save_baseline(hashes):
    data = {"updated_at": datetime.now().isoformat(), "hashes": list(hashes)}
    with open(BASELINE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    log(f"基线已保存到 {BASELINE_FILE}")


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
    返回 [{"name":..., "budget":..., "message":...}, ...]
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    resp = requests.get(CONTACT_URL, headers=headers, timeout=30)
    resp.raise_for_status()
    html = resp.text

    # 调试：保存 HTML 到文件（GitHub Actions 里可以通过 artifact 下载）
    with open("debug_page.html", "w", encoding="utf-8") as f:
        f.write(html[:5000])  # 只保存前 5000 字符

    messages = []
    seen = set()

    # 模式1: 从 JSON 数据中提取（SPA 常用方式）
    # 查找 <script> 标签里的 JSON 数据
    json_patterns = [
        r'"name"\s*:\s*"([^"]+)"\s*,\s*"budget"\s*:\s*"([^"]*)"\s*,\s*"message"\s*:\s*"([^"]*)"',
        r'"name"\s*:\s*"([^"]+)"[^}]*"message"\s*:\s*"([^"]*)"',
    ]
    for pattern in json_patterns:
        for m in re.finditer(pattern, html, re.DOTALL):
            name    = m.group(1).strip()
            budget  = m.group(2).strip() if len(m.groups()) > 1 else ""
            msg     = m.group(3).strip() if len(m.groups()) > 2 else ""
            key     = f"{name}|{budget}|{msg}"
            if key not in seen and name:
                seen.add(key)
                messages.append({"name": name, "budget": budget, "message": msg})

    # 模式2: 从 HTML 文本中匹配中文姓名（脱敏格式：王*生）
    if not messages:
        # 匹配 "姓名 | 预算 | 消息" 的模式
        # 查找所有看起来像留言的块
        # 这里根据实际页面结构需要调整
        name_pattern = r'([\u4e00-\u9fa5]\*[\u4e00-\u9fa5]|[\u4e00-\u9fa5]{2,4})'
        matches = re.findall(name_pattern, html)
        if matches:
            log(f"  正则匹配到 {len(matches)} 个可能的姓名")
            for name in matches[:20]:
                key = f"{name}||"
                if key not in seen:
                    seen.add(key)
                    messages.append({"name": name, "budget": "", "message": ""})

    return messages


def main():
    log("开始监控...")
    messages = fetch_and_parse()

    if not messages:
        log("未解析到留言，本次跳过")
        # 保存一个空基线，避免下次全部推送
        save_baseline(set())
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
