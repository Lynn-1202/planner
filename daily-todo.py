#!/usr/bin/env python3
"""Daily Feishu Todo Push — structured card with tasks, progress, habits."""

import os, sys, json, requests
from datetime import datetime, timezone, timedelta

# Fix Windows GBK encoding for emoji output
if sys.platform == "win32":
    import io
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    except Exception:
        pass

# ── Config ──────────────────────────────────────────────
APP_ID     = os.environ["FEISHU_APP_ID"]
APP_SECRET = os.environ["FEISHU_APP_SECRET"]
OPEN_ID    = os.environ["FEISHU_OPEN_ID"]
BASE_TOKEN = "L1bLbhLhiauzFWsiywNcBkGannb"
BITABLE_URL = "https://my.feishu.cn/base/L1bLbhLhiauzFWsiywNcBkGannb"
BASE_URL   = "https://open.feishu.cn/open-apis"

PROJECTS = [
    ("P0 毕业论文",              "tblQfXrI8FOFAog4"),
    ("P1 AI占卜合作论文",        "tblGzWRKLT4CCXkz"),
    ("P1 公考二轮",              "tbl1PzLFZey4udBT"),
    ("P1 实习复盘 & 简历",       "tblke5IFp7JebHm1"),
    ("P1 线上兼职",              "tbl9EUrdnNNBJCdo"),
    ("P2 找房子",                "tblrDxNFBmCzSKzD"),
]
OVERVIEW_TABLE  = "tblmgBQIYyXW6pJW"
CST = timezone(timedelta(hours=8))

STATUS_ICON = {"已完成": "✅", "进行中": "🔄", "阻塞": "🚫"}

# ── Auth ────────────────────────────────────────────────
def get_token():
    r = requests.post(f"{BASE_URL}/auth/v3/tenant_access_token/internal",
                      json={"app_id": APP_ID, "app_secret": APP_SECRET}, timeout=10)
    r.raise_for_status()
    return r.json()["tenant_access_token"]

# ── API helpers ─────────────────────────────────────────
def list_records(token, table_id):
    records = []
    page_token = None
    while True:
        params = {"page_size": 100}
        if page_token:
            params["page_token"] = page_token
        r = requests.get(
            f"{BASE_URL}/bitable/v1/apps/{BASE_TOKEN}/tables/{table_id}/records",
            headers={"Authorization": f"Bearer {token}"}, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        if data.get("code") != 0:
            break
        records.extend(data.get("data", {}).get("items", []))
        if not data.get("data", {}).get("has_more"):
            break
        page_token = data["data"].get("page_token")
    return records

def send_card(token, card_json):
    """Send interactive card message."""
    r = requests.post(
        f"{BASE_URL}/im/v1/messages?receive_id_type=open_id",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"receive_id": OPEN_ID, "msg_type": "interactive", "content": json.dumps(card_json, ensure_ascii=False)},
        timeout=15)
    r.raise_for_status()
    return r.json()

# ── Helpers ─────────────────────────────────────────────
def ts_date(ms):
    if not ms: return None
    return datetime.fromtimestamp(int(ms) / 1000, tz=CST).strftime("%m/%d")

def txt(val):
    if isinstance(val, str): return val
    if isinstance(val, list): return "".join(e.get("text", "") for e in val if isinstance(e, dict))
    if isinstance(val, (int, float)): return str(val)
    return ""

def is_active(fields, today_str):
    """Only show tasks whose date range covers today."""
    status = txt(fields.get("状态", ""))
    if status == "已完成":
        return False
    start, end = fields.get("计划开始"), fields.get("计划完成")
    if start and end:
        s, e = ts_date(start), ts_date(end)
        if s and e and s <= today_str <= e:
            return True
    return False

def progress_bar(pct_or_val, width=8):
    """pct can be 0-100 or 0-1 (Feishu progress field)."""
    try:
        pct = float(pct_or_val)
    except (TypeError, ValueError):
        return ""
    if pct <= 1:        # Feishu progress field: 0-1
        pct *= 100
    n = max(0, min(width, round(pct / 100 * width)))
    return "█" * n + "░" * (width - n) + f" {pct:.0f}%"

# ── Card builders ───────────────────────────────────────
def build_task_section(token, today_str):
    """Build the '今日待办' card section."""
    md = ""
    has_any = False
    for proj_name, table_id in PROJECTS:
        records = list_records(token, table_id)
        active = [r for r in records if is_active(r.get("fields", {}), today_str)]
        if not active:
            continue
        has_any = True
        # Project header with priority color
        if "P0" in proj_name:
            md += f"\n**🔴 {proj_name}**\n"
        elif "P1" in proj_name:
            md += f"\n**🟡 {proj_name}**\n"
        else:
            md += f"\n**🟢 {proj_name}**\n"

        for rec in active:
            f = rec.get("fields", {})
            node    = txt(f.get("环节", ""))
            end_d   = ts_date(f.get("计划完成")) or ""
            status  = txt(f.get("状态", ""))
            icon    = STATUS_ICON.get(status, "☐")
            md += f"{icon} {node}"
            if end_d:
                md += f" → {end_d}"
            md += "\n"

    if not has_any:
        md += "\n🎉 今天没有到期任务，按习惯节奏推进即可～\n"
    return md

def build_progress_section(token):
    """Build the project progress section — compact one-liner per project."""
    overview = list_records(token, OVERVIEW_TABLE)
    prio_order = {"P0": 0, "P1": 1, "P2": 2}
    overview.sort(key=lambda r: prio_order.get(txt(r.get("fields", {}).get("优先级", "")), 99))

    SHORT = {"毕业论文(调整+实验设计+成文)": "毕业论文", "AI占卜合作论文": "AI占卜",
             "公考二轮课程": "公考二轮", "实习复盘 & 简历": "简历",
             "线上兼职": "兼职", "找房子": "找房子"}
    md = ""
    for rec in overview:
        f = rec.get("fields", {})
        name = SHORT.get(txt(f.get("项目", "")), txt(f.get("项目", ""))[:6])
        prog_val = f.get("完成进度(%)")
        bar = progress_bar(prog_val, 6) if prog_val is not None else ""
        prio_icon = {"P0": "🔴", "P1": "🟡", "P2": "🟢"}.get(txt(f.get("优先级", "")), "⚪")
        md += f"{prio_icon} {name}"
        if bar:
            md += f" {bar}"
        md += "\n"
    return md

# ── Main ────────────────────────────────────────────────
def main():
    token = get_token()
    today = datetime.now(CST)
    today_str = today.strftime("%m/%d")
    wday  = ["一","二","三","四","五","六","日"][today.weekday()]
    wnum  = today.isocalendar()[1]
    header_title = f"📅 {today.month}月{today.day}日 周{wday} · 第{wnum}周"

    # Build card sections
    task_md     = build_task_section(token, today_str)
    progress_md = build_progress_section(token)

    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": header_title},
            "template": "blue"
        },
        "elements": [
            # ── Section 1: Today's Tasks ──
            {"tag": "div", "text": {"tag": "lark_md", "content": "**🔥 今日待办**"}},
            {"tag": "hr"},
            {"tag": "div", "text": {"tag": "lark_md", "content": task_md}},
            # ── Section 2: Progress ──
            {"tag": "div", "text": {"tag": "lark_md", "content": "**📊 项目进度**"}},
            {"tag": "hr"},
            {"tag": "div", "text": {"tag": "lark_md", "content": progress_md}},
            # ── Actions ──
            {"tag": "hr"},
            {"tag": "action", "actions": [
                {"tag": "button", "text": {"tag": "plain_text", "content": "📋 打开多维表格"},
                 "url": BITABLE_URL, "type": "primary", "value": {}}
            ]},
            {"tag": "note", "elements": [
                {"tag": "plain_text", "content": "🤖 每日 9:00 自动推送 · GitHub Actions"}
            ]},
        ]
    }

    result = send_card(token, card)
    code = result.get("code", -1)
    if code == 0:
        print(f"✅ Card sent: msg_id={result.get('data',{}).get('message_id','?')}")
    else:
        print(f"❌ Send failed: {result}", file=sys.stderr)
        # Fallback to plain text
        print("Falling back to text message...", file=sys.stderr)
        plain = f"{header_title}\n\n{task_md}\n\n📊 进度\n{progress_md}"
        content = json.dumps({"text": plain}, ensure_ascii=False)
        requests.post(
            f"{BASE_URL}/im/v1/messages?receive_id_type=open_id",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"receive_id": OPEN_ID, "msg_type": "text", "content": content}, timeout=15)

if __name__ == "__main__":
    main()
