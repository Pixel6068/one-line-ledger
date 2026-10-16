#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一句话记账 · one-line-ledger
说一句话就记完，数据存本地 SQLite。零第三方依赖（只用 Python 标准库）。

用法
    python3 ledger.py add "打车 45"        # 记一笔（支持「昨天/前天」补记）
    python3 ledger.py list [n]             # 看最近 n 笔（默认 20）
    python3 ledger.py report               # 生成 HTML 报表并打印路径
    python3 ledger.py stats                # 命令行看本月汇总
    python3 ledger.py init                 # 初始化数据库（首次运行会自动执行）

数据文件默认在 ~/.one-line-ledger/ledger.db，可用环境变量 LEDGER_DB 覆盖。
"""
import os
import re
import sys
import json
import html
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

HOME_DIR = Path(os.environ.get("LEDGER_HOME", Path.home() / ".one-line-ledger"))
DB_PATH = Path(os.environ.get("LEDGER_DB", HOME_DIR / "ledger.db"))

# ────────────────────────────── 分类规则 ──────────────────────────────
# 想适配自己的说法，改这里即可。命中顺序：PRE_RULES → CATEGORIES → 其他
CATEGORIES = {
    "餐饮": ["饭", "吃", "餐", "外卖", "火锅", "咖啡", "奶茶", "水果", "零食", "早餐", "早饭",
             "午饭", "晚饭", "夜宵", "酒", "鱼", "肉", "虾", "蛋", "面", "包", "饺", "粉",
             "烧烤", "甜品", "蛋糕", "饮料"],
    "交通": ["打车", "滴滴", "出租", "地铁", "公交", "加油", "油费", "充电", "停车", "过路",
             "路费", "通行费", "高速", "高铁", "火车", "机票", "车票", "ETC", "洗车", "保养"],
    "购物": ["买", "网购", "快递", "超市", "淘宝", "京东", "拼多多", "手机壳", "数据线", "充电器",
             "耳机", "鼠标", "键盘"],
    "日用": ["洗衣", "纸巾", "纸", "牙刷", "牙膏", "洗发", "沐浴", "指甲", "理发", "剪发",
             "美发", "洗剪吹", "剃须", "护肤", "润肤", "清洁", "拖把", "垃圾袋", "日用品"],
    "住房": ["房租", "水电", "电费", "水费", "物业", "物业费", "燃气", "取暖", "宽带", "网费",
             "维修", "装修", "家具", "家电"],
    "医疗": ["医", "药", "看病", "检查", "体检", "挂号", "牙", "眼科", "门诊", "住院", "疫苗"],
    "娱乐": ["电影", "游戏", "KTV", "旅游", "门票", "会员", "娱乐", "视频", "音乐", "演唱会",
             "展览", "剧本杀", "密室"],
    "服饰": ["衣服", "服装", "外套", "裤", "裙", "内衣", "毛衣", "衬衫", "T恤", "鞋", "帽",
             "围巾", "表带"],
    "教育": ["书", "课", "培训", "学费", "考试", "报名", "教材", "网课"],
    "通讯": ["话费", "流量", "电话费", "电信", "联通", "移动", "充值"],
    "人情": ["红包", "随礼", "礼金", "份子", "送礼", "人情"],
    "其他": [],
}

# 前置规则：优先于关键词命中（防止被别的词抢走）
# 原则是「按支付场景分类，不按物品分类」——在超市买的菜算购物，不算餐饮
PRE_RULES = [
    (re.compile(r"买菜|菜市场|生鲜"), "购物"),
    (re.compile(r"水费|电费|燃气费|取暖费"), "住房"),
]

CN_DIGIT = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
            "六": 6, "七": 7, "八": 8, "九": 9}
CN_UNIT = {"十": 10, "百": 100, "千": 1000}


def cn2num(s: str) -> int:
    """中文数字转阿拉伯数字：两千=2000 五百=500 两万=20000 两千五=2500 五百三=530"""
    total = section = num = 0
    last_unit = 1
    for ch in s:
        if ch in CN_DIGIT:
            num = CN_DIGIT[ch]
        elif ch == "万":
            section = (section + num) * 10000
            total += section
            section = num = 0
            last_unit = 10000
        elif ch in CN_UNIT:
            u = CN_UNIT[ch]
            if num == 0:
                num = 1
            section += num * u
            num = 0
            last_unit = u
    if num > 0:
        if last_unit == 10000:
            num *= 1000
        elif last_unit == 1000:
            num *= 100
        elif last_unit == 100:
            num *= 10
    return total + section + num


USD_RATE = 7.2


def parse_amount(text: str):
    """从一句话里抠出金额。支持：45 / 45元 / 1.2万 / 两千五 / $20 / 花了30"""
    m = re.search(r"[零一二两三四五六七八九十百千万]{2,}", text)
    if m:
        v = cn2num(m.group(0))
        if v > 0:
            return float(v)
    patterns = [
        (r"[¥￥]\s*(\d+(?:\.\d+)?)", 1),
        (r"(\d+(?:\.\d+)?)\s*[元块]", 1),
        (r"(\d+(?:\.\d+)?)\s*万\s*(\d+)?", "wan"),
        (r"(\d+(?:\.\d+)?)\s*美元", "usd"),
        (r"\$\s*(\d+(?:\.\d+)?)", "usd"),
        (r"(\d+(?:\.\d+)?)\s*$", 1),
        (r"花费?\s*(\d+(?:\.\d+)?)", 1),
        (r"花了?\s*(\d+(?:\.\d+)?)", 1),
        (r"^(\d{2,}(?:\.\d+)?)", 1),
    ]
    for pat, grp in patterns:
        mm = re.search(pat, text)
        if not mm:
            continue
        if grp == "wan":
            base = float(mm.group(1)) * 10000
            return base + (float(mm.group(2)) * 1000 if mm.group(2) else 0.0)
        if grp == "usd":
            return round(float(mm.group(1)) * USD_RATE, 2)
        return float(mm.group(grp))
    return None


def classify(text: str) -> str:
    for rx, cat in PRE_RULES:
        if rx.search(text):
            return cat
    for cat, words in CATEGORIES.items():
        for w in words:
            if w in text:
                return cat
    return "其他"


def resolve_date(text: str) -> str:
    """句子里带「昨天 / 前天」就记到那一天"""
    off = 2 if "前天" in text else (1 if "昨天" in text else 0)
    d = datetime.now() - timedelta(days=off)
    return d.strftime("%Y-%m-%d")


# ────────────────────────────── 数据库 ──────────────────────────────
SCHEMA = """
CREATE TABLE IF NOT EXISTS ledger (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    date      TEXT NOT NULL,
    text      TEXT NOT NULL,
    amount    REAL NOT NULL,
    category  TEXT NOT NULL,
    created   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ledger_date ON ledger(date);
"""


def connect():
    HOME_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def cmd_init(_args):
    with connect() as conn:
        conn.execute("SELECT 1")
    print(f"✓ 数据库就绪：{DB_PATH}")
    return 0


def cmd_add(args):
    if not args:
        print("用法：ledger.py add \"打车 45\"", file=sys.stderr)
        return 2
    text = " ".join(args).strip()
    amount = parse_amount(text)
    if amount is None:
        print(f"✗ 没找到金额：「{text}」\n  可以写成「打车 45」或「买菜 32 块」这种带数字的说法。", file=sys.stderr)
        return 3
    category = classify(text)
    date = resolve_date(text)
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO ledger (date, text, amount, category, created) VALUES (?,?,?,?,?)",
            (date, text, amount, category, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        )
        rid = cur.lastrowid
    amt = f"¥{amount:,.2f}".rstrip("0").rstrip(".")
    print(f"✓ 已记 [{rid}] {date}  {text}  {amt}  → {category}")
    return 0


def fmt(v):
    s = f"¥{v:,.2f}"
    return s[:-3] if s.endswith(".00") else s


def cmd_list(args):
    n = int(args[0]) if args and args[0].isdigit() else 20
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM ledger ORDER BY date DESC, id DESC LIMIT ?", (n,)
        ).fetchall()
    if not rows:
        print("还没有记录。试试：ledger.py add \"打车 45\"")
        return 0
    for r in rows:
        print(f"{r['date']}  {fmt(r['amount']):>10}  {r['category']:<4}  {r['text']}")
    return 0


def month_prefix(offset=0):
    d = datetime.now()
    y, m = d.year, d.month - offset
    while m <= 0:
        m += 12
        y -= 1
    return f"{y:04d}-{m:02d}"


def cmd_stats(_args):
    cur_month = month_prefix()
    with connect() as conn:
        rows = conn.execute(
            "SELECT category, SUM(amount) s, COUNT(*) c FROM ledger WHERE date LIKE ? "
            "GROUP BY category ORDER BY s DESC", (cur_month + "%",)
        ).fetchall()
        tot = conn.execute(
            "SELECT COALESCE(SUM(amount),0), COUNT(*) FROM ledger WHERE date LIKE ?",
            (cur_month + "%",)
        ).fetchone()
    print(f"本月（{cur_month}）：共 {fmt(tot[0])}，{tot[1]} 笔")
    for r in rows:
        print(f"  {r['category']:<4}  {fmt(r['s']):>12}  ({r['c']} 笔)")
    return 0


# ────────────────────────────── 报表 ──────────────────────────────
REPORT_CSS = """
*{margin:0;padding:0;box-sizing:border-box}
body{background:#F2F2F7;color:#000;padding:28px 22px 60px;
 font-family:-apple-system,"SF Pro Display","PingFang SC","Helvetica Neue",sans-serif;
 -webkit-font-smoothing:antialiased}
.wrap{max-width:920px;margin:0 auto}
h1{font-size:30px;font-weight:700;letter-spacing:-.03em}
.sub{font-size:13px;color:#8E8E93;margin:6px 0 22px}
.card{background:#fff;border-radius:18px;box-shadow:0 1px 2px rgba(0,0,0,.04),0 10px 28px -14px rgba(0,0,0,.14);
 padding:20px 22px;margin-bottom:16px}
h2{font-size:14.5px;font-weight:600;color:#3C3C43;margin-bottom:14px}
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:16px}
.kpis .card{margin:0;text-align:center;padding:18px 12px}
.kv{font-size:30px;font-weight:700;letter-spacing:-.035em}
.kl{font-size:12.5px;color:#8E8E93;margin-top:8px}
.o{color:#C86A00}.b{color:#0040DD}.g{color:#248A3D}.p{color:#8E44AD}
table{width:100%;border-collapse:collapse;font-size:14px}
th,td{text-align:left;padding:9px 6px;border-bottom:1px solid #F2F2F7}
th{font-size:12px;color:#8E8E93;font-weight:500}
td.n{font-variant-numeric:tabular-nums;font-weight:600;text-align:right}
.two{display:grid;grid-template-columns:1fr 1fr;gap:16px}
@media(max-width:700px){.kpis{grid-template-columns:repeat(2,1fr)}.two{grid-template-columns:1fr}}
"""


def cmd_report(_args):
    with connect() as conn:
        rows = conn.execute("SELECT * FROM ledger ORDER BY date DESC, id DESC").fetchall()
        month = month_prefix()
        mrows = [r for r in rows if r["date"].startswith(month)]
        total_month = sum(r["amount"] for r in mrows)
        total_all = sum(r["amount"] for r in rows)

        agg = {}
        for r in mrows:
            agg[r["category"]] = agg.get(r["category"], 0) + r["amount"]
        cats = sorted(agg.items(), key=lambda x: -x[1])

        # 近 12 个月
        months = [month_prefix(i) for i in range(11, -1, -1)]
        msum = {m: 0.0 for m in months}
        for r in rows:
            k = r["date"][:7]
            if k in msum:
                msum[k] += r["amount"]

    days = max(datetime.now().day, 1)
    kpis = [
        (fmt(total_month), "本月支出", "o"),
        (str(len(mrows)), "本月笔数", "b"),
        (fmt(total_month / days), "本月日均", "p"),
        (fmt(total_all), "累计支出", "g"),
    ]
    kpi_html = "".join(
        f'<div class="card"><div class="kv {c}">{v}</div><div class="kl">{l}</div></div>'
        for v, l, c in kpis
    )

    cat_html = "".join(
        f"<tr><td>{html.escape(k)}</td><td class='n'>{fmt(v)}</td>"
        f"<td class='n' style='color:#8E8E93'>{v/total_month*100:.1f}%</td></tr>"
        for k, v in cats
    ) or "<tr><td colspan='3' style='color:#8E8E93'>本月还没有记录</td></tr>"

    # 走势 SVG
    vals = [msum[m] for m in months]
    vmax = max(vals + [1])
    PL, PR, PT, PB = 54, 640, 16, 170
    xs = [PL + i * (PR - PL) / (len(vals) - 1) for i in range(len(vals))]
    yp = lambda v: PB - (v / vmax) * (PB - PT)
    pts = " ".join(f"{x:.1f},{yp(v):.1f}" for x, v in zip(xs, vals))
    grid = ""
    for i in range(5):
        gv = vmax * i / 4
        gy = yp(gv)
        lab = f"{int(round(gv/1000))}k" if gv >= 1000 else f"{int(round(gv))}"
        grid += (f'<line x1="{PL}" y1="{gy:.1f}" x2="{PR}" y2="{gy:.1f}" stroke="#E5E5EA"/>'
                 f'<text x="{PL-8}" y="{gy+3.5:.1f}" font-size="9.5" fill="#8E8E93" text-anchor="end">{lab}</text>')
    xlab = "".join(
        f'<text x="{xs[i]:.1f}" y="{PB+16}" font-size="8.5" fill="#8E8E93" text-anchor="middle">'
        f'{int(m[5:7])}月</text>' for i, m in enumerate(months)
    )
    trend_svg = (f'<svg width="100%" viewBox="0 0 660 200">{grid}{xlab}'
                 f'<polygon points="{PL},{PB} {pts} {PR},{PB}" fill="rgba(255,149,0,.10)"/>'
                 f'<polyline points="{pts}" fill="none" stroke="#FF9500" stroke-width="2.5" '
                 f'stroke-linejoin="round" stroke-linecap="round"/>'
                 f'<circle cx="{xs[-1]:.1f}" cy="{yp(vals[-1]):.1f}" r="4" fill="#FF9500" '
                 f'stroke="#fff" stroke-width="2"/></svg>')

    recent = "".join(
        f"<tr><td style='color:#8E8E93'>{r['date']}</td><td>{html.escape(r['text'])}</td>"
        f"<td class='n'>{fmt(r['amount'])}</td><td style='color:#8E8E93'>{r['category']}</td></tr>"
        for r in rows[:25]
    ) or "<tr><td colspan='4' style='color:#8E8E93'>还没有记录</td></tr>"

    doc = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>记账报表</title><style>{REPORT_CSS}</style></head><body><div class="wrap">
<h1>记账报表</h1>
<div class="sub">生成于 {datetime.now().strftime('%Y-%m-%d %H:%M')} · 共 {len(rows)} 笔记录</div>
<div class="kpis">{kpi_html}</div>
<div class="card"><h2>支出走势（近 12 个月）</h2>{trend_svg}</div>
<div class="two">
  <div class="card"><h2>本月分类</h2><table><tr><th>分类</th><th style="text-align:right">金额</th>
  <th style="text-align:right">占比</th></tr>{cat_html}</table></div>
  <div class="card"><h2>最近记录</h2><table><tr><th>日期</th><th>原文</th>
  <th style="text-align:right">金额</th><th>分类</th></tr>{recent}</table></div>
</div>
</div></body></html>"""

    out = DB_PATH.parent / "report.html"
    out.write_text(doc, encoding="utf-8")
    print(f"✓ 报表已生成：{out}")
    return 0


COMMANDS = {
    "init": cmd_init,
    "add": cmd_add,
    "list": cmd_list,
    "stats": cmd_stats,
    "report": cmd_report,
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    cmd = sys.argv[1]
    if cmd not in COMMANDS:
        print(f"未知命令：{cmd}\n可用：{', '.join(COMMANDS)}", file=sys.stderr)
        return 2
    return COMMANDS[cmd](sys.argv[2:])


if __name__ == "__main__":
    sys.exit(main())
