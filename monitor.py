#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
10Song Contact Page Monitor
监视 10song.com/contact 页面的客户留言，有新留言时通过 Server酱 推送微信通知
"""

import os
import json
import time
import hashlib
import requests
from datetime import datetime

# ── 配置 ─────────────────────────────────────────────────────
SENDKEY      = os.environ.get("SENDKEY", "")
BASELINE_FILE = os.environ.get("BASELINE_FILE", "baseline.json")
CONTACT_URL  = "https://10song.com/contact"
TIMEOUT      = 15
# ───────────────────────────────────────────────────────────────


def log(msg):
    print(f"[{datetime.now()}] {msg}")


def get_page_content():
    """获取 contact 页面 HTML"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    resp = requests.get(CONTACT_URL, headers=headers, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.text


def parse_messages(html):
    """
    从 contact 页面解析客户留言
    这是 SPA 页面，需要找 JSON 数据或 script 标签中的留言信息
    如果没有结构化的数据，返回空列表（静默跳过，不报错）
    """
    messages = []
    try:
        # 尝试从 script 标签中提取 JSON 数据
        import re
        # 匹配可能的留言数据模式
        patterns = [
            r'"name"\s*:\s*"([^"]+)"\s*,\s*"budget"\s*:\s*"([^"]*)"\s*,\s*"message"\s*:\s*"([^"]*)"',
            r'name["\']\s*[:=]\s*["\']([^"\']+)["\'][^>]*message["\']\s*[:=]\s*["\']([^"\']+)',
        ]
        for p in patterns:
            for m in re.finditer(p, html, re.DOTALL):
                name = m.group(1).strip()
                budget = m.group(2).strip() if len(m.groups()) > 1 else ""
                msg = m.group(3).strip() if len(m.groups()) > 2 else ""
                if name and len(name) > 1:
                    messages.append({"name": name, "budget": budget, "message": msg[:100]})
    except Exception as e:
        log(f"解析页面异常（非致命）: {e}")
    return messages


def compute_hash(msg):
    """计算单条留言的唯一哈希"""
    key = f"{msg.get('name','')}|{msg.get('budget','')}|{msg.get('message','')}"
    return hashlib.md5(key.encode("utf-8")).hexdigest()


def load_baseline():
    """加载已有基线（上次运行时看到的留言哈希集合）"""
    if os.path.exists(BASELINE_FILE):
        try:
            with open(BASELINE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return set(data.get("hashes", []))
        except Exception:
            pass
    return set()


def save_baseline(hashes):
    """保存当前基线"""
    data = {"updated_at": datetime.now().isoformat(), "hashes": list(hashes)}
    with open(BASELINE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def send_notify(messages):
    """通过 Server酱 推送微信通知"""
    if not SENDKEY:
        log("⚠️  SENDKEY 未设置，跳过推送")
        return False
    text = f"🚨 10Song 发现 {len(messages)} 条新客户留言！"
    desp = "# 新客户留言\n\n"
    for m in messages:
        name    = m.get("name", "（未知）")
        budget  = m.get("budget", "")
        msg     = m.get("message", "")[:80]
        desp += f"## {name}  |  {budget}\n> {msg}\n\n---\n"
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


def main():
    log("开始监控...")
    html = get_page_content()
    messages = parse_messages(html)
    log(f"解析到 {len(messages)} 条客户留言: {[m['name'] for m in messages]}")

    if not messages:
        log("页面无留言数据（SPA 渲染？），本次跳过")
        return

    current_hashes = {compute_hash(m) for m in messages}
    baseline_hashes = load_baseline()

    new_messages = [m for m in messages if compute_hash(m) not in baseline_hashes]

    if not new_messages:
        log("No new messages detected. ✅")
        # 仍然更新基线（防止页面结构变化导致哈希漂移）
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
