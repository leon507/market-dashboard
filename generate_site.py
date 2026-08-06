#!/usr/bin/env python3
"""Generate A-share market overview website from westock-data JSON files."""

import json
import os
from datetime import datetime, timedelta

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
OUTPUT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "market_dashboard.html")

# Index definitions
INDICES = [
    ("sh000001", "上证指数"),
    ("sz399001", "深证成指"),
    ("sh000300", "沪深300"),
    ("sh000905", "中证500"),
    ("sh000852", "中证1000"),
    ("sz399006", "创业板指"),
    ("sh000688", "科创50"),
]

def compute_dates(kline_dates):
    """Dynamically compute comparison dates from available K-line dates.
    
    - CURRENT_DATE: if before 15:00, use the second-to-last date; if after 15:00, use the last date
    - YESTERDAY: the trading day before CURRENT_DATE
    - LAST_WEEK: ~7 calendar days before CURRENT_DATE
    - LAST_MONTH: ~30 calendar days before CURRENT_DATE
    """
    from datetime import datetime, timedelta
    
    sorted_dates = sorted(kline_dates)
    now = datetime.now()
    
    # If before 15:00, market is still open - use yesterday's close as the latest
    # If after 15:00, market is closed - use today's close
    if now.hour < 15:
        # Use the second-to-last date (yesterday's close)
        if len(sorted_dates) >= 2:
            current = sorted_dates[-2]
        else:
            current = sorted_dates[-1]
    else:
        current = sorted_dates[-1]
    
    current_dt = datetime.strptime(current, "%Y-%m-%d")
    
    # Find yesterday: the closest trading day before current
    yesterday = None
    for d in reversed(sorted_dates):
        if d < current:
            yesterday = d
            break
    
    # Find last week: closest trading day ~7 days before current
    target_week = current_dt - timedelta(days=7)
    last_week = None
    best_diff = float('inf')
    for d in sorted_dates:
        d_dt = datetime.strptime(d, "%Y-%m-%d")
        diff = abs((d_dt - target_week).days)
        if diff < best_diff and d < current:
            best_diff = diff
            last_week = d
    
    # Find last month: closest trading day ~30 days before current
    target_month = current_dt - timedelta(days=30)
    last_month = None
    best_diff = float('inf')
    for d in sorted_dates:
        d_dt = datetime.strptime(d, "%Y-%m-%d")
        diff = abs((d_dt - target_month).days)
        if diff < best_diff and d < current:
            best_diff = diff
            last_month = d
    
    return current, yesterday or current, last_week or current, last_month or current


def load_json(filename):
    path = os.path.join(DATA_DIR, filename)
    if not os.path.exists(path):
        print(f"  WARNING: {filename} not found, using empty data")
        if filename == "quotes.json":
            return {"data": []}
        elif filename == "sector_ranking.json":
            return {"sections": [[], [], []]}
        elif filename == "news.json":
            return []
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"  WARNING: Failed to parse {filename}: {e}")
        if filename == "quotes.json":
            return {"data": []}
        elif filename == "sector_ranking.json":
            return {"sections": [[], [], []]}
        elif filename == "news.json":
            return []
        return []


def get_kline_close_map(kline_data):
    """Return {date: close_price} from kline data."""
    result = {}
    for item in kline_data:
        result[item["date"]] = item["last"]
    return result


def calc_change_pct(current, base):
    if base == 0 or base is None:
        return 0.0
    return round((current - base) / base * 100, 2)


def fmt_num(n):
    """Format number with thousands separator and 2 decimals."""
    if n is None:
        return "--"
    return f"{n:,.2f}"


def fmt_pct(pct):
    """Format percentage with sign."""
    if pct is None:
        return "--"
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.2f}%"


def get_color_class(pct):
    """Return CSS class based on percentage (red for up, green for down - Chinese convention)."""
    if pct is None:
        return "neutral"
    return "up" if pct >= 0 else "down"


def process_indices():
    """Process index data and return list of index info dicts."""
    quotes = load_json("quotes.json")
    quote_map = {}
    for item in quotes.get("data", []):
        code = item.get("symbol", "")
        quote_map[code] = item.get("data", {})

    # Load first index's kline to compute dynamic dates
    first_kline = load_json(f"kline_{INDICES[0][0]}.json")
    first_close_map = get_kline_close_map(first_kline) if first_kline else {}
    
    if first_close_map:
        CURRENT_DATE, YESTERDAY, LAST_WEEK, LAST_MONTH = compute_dates(first_close_map.keys())
    else:
        # Fallback if no K-line data at all
        now = datetime.now()
        CURRENT_DATE = now.strftime("%Y-%m-%d")
        YESTERDAY = LAST_WEEK = LAST_MONTH = CURRENT_DATE

    print(f"  Date context: current={CURRENT_DATE}, yesterday={YESTERDAY}, last_week={LAST_WEEK}, last_month={LAST_MONTH}")

    results = []
    for code, name in INDICES:
        kline = load_json(f"kline_{code}.json")
        close_map = get_kline_close_map(kline) if kline else {}

        current_val = close_map.get(CURRENT_DATE, 0)
        yesterday_val = close_map.get(YESTERDAY, 0)
        last_week_val = close_map.get(LAST_WEEK, 0)
        last_month_val = close_map.get(LAST_MONTH, 0)

        # For trend chart: all available days
        chart_dates = sorted(close_map.keys())
        chart_values = [close_map[d] for d in chart_dates]

        # Real-time data from quote
        rt = quote_map.get(code, {})
        rt_price = rt.get("price", 0)
        rt_change_pct = rt.get("change_percent", 0)

        results.append({
            "code": code,
            "name": name,
            "current": current_val,
            "yesterday": yesterday_val,
            "last_week": last_week_val,
            "last_month": last_month_val,
            "chg_vs_yesterday": calc_change_pct(current_val, yesterday_val),
            "chg_vs_last_week": calc_change_pct(current_val, last_week_val),
            "chg_vs_last_month": calc_change_pct(current_val, last_month_val),
            "chart_dates": chart_dates,
            "chart_values": chart_values,
            "rt_price": rt_price,
            "rt_change_pct": rt_change_pct,
            "pe_ratio": rt.get("pe_ratio", 0),
            "total_market_cap": rt.get("total_market_cap", 0),
            "chg_5d": rt.get("chg_5d", 0),
            "chg_20d": rt.get("chg_20d", 0),
            "chg_ytd": rt.get("chg_ytd", 0),
        })
    return results, CURRENT_DATE


def process_sectors():
    """Process sector ranking data."""
    data = load_json("sector_ranking.json")
    sections = data.get("sections", [])

    industry_gainers = sections[0] if len(sections) > 0 else []
    concept_gainers = sections[1] if len(sections) > 1 else []
    capital_inflow = sections[2] if len(sections) > 2 else []

    return {
        "industry_gainers": industry_gainers,
        "concept_gainers": concept_gainers,
        "capital_inflow": capital_inflow,
    }


def process_news():
    """Process news data."""
    data = load_json("news.json")
    news_list = []
    for item in data:
        ts = item.get("publish_time", 0)
        dt = datetime.fromtimestamp(ts) if ts else None
        date_str = dt.strftime("%Y-%m-%d %H:%M") if dt else ""
        date_only = dt.strftime("%Y-%m-%d") if dt else ""

        news_list.append({
            "title": item.get("news_title", ""),
            "source": item.get("source", ""),
            "time": date_str,
            "date": date_only,
            "rank": item.get("rank", ""),
        })
    return news_list


def generate_html(indices, sectors, news, CURRENT_DATE):
    """Generate the complete HTML file."""

    # Prepare JSON data for JavaScript
    chart_data_js = json.dumps([{
        "name": idx["name"],
        "code": idx["code"],
        "dates": idx["chart_dates"],
        "values": idx["chart_values"],
    } for idx in indices], ensure_ascii=False)

    # Index cards HTML
    index_cards = ""
    for idx in indices:
        cls_y = get_color_class(idx["chg_vs_yesterday"])
        cls_w = get_color_class(idx["chg_vs_last_week"])
        cls_m = get_color_class(idx["chg_vs_last_month"])

        index_cards += f"""
        <div class="index-card" onclick="switchChart('{idx['code']}')" id="card-{idx['code']}">
            <div class="card-header">
                <span class="index-name">{idx['name']}</span>
                <span class="index-code">{idx['code']}</span>
            </div>
            <div class="card-value {cls_y}">{fmt_num(idx['current'])}</div>
            <div class="card-rt">盘中 {fmt_num(idx['rt_price'])} <span class="rt-pct {get_color_class(idx['rt_change_pct'])}">{fmt_pct(idx['rt_change_pct'])}</span></div>
            <div class="card-comparisons">
                <div class="comp-row">
                    <span class="comp-label">较昨日</span>
                    <span class="comp-value {cls_y}">{fmt_pct(idx['chg_vs_yesterday'])}</span>
                </div>
                <div class="comp-row">
                    <span class="comp-label">较上周</span>
                    <span class="comp-value {cls_w}">{fmt_pct(idx['chg_vs_last_week'])}</span>
                </div>
                <div class="comp-row">
                    <span class="comp-label">较上月</span>
                    <span class="comp-value {cls_m}">{fmt_pct(idx['chg_vs_last_month'])}</span>
                </div>
            </div>
            <div class="card-footer">
                <span>PE {idx['pe_ratio']:.1f}</span>
                <span>YTD {fmt_pct(idx['chg_ytd'])}</span>
            </div>
        </div>"""

    # Sector industry gainers HTML
    sector_industry_html = ""
    for s in sectors["industry_gainers"]:
        pct = float(s.get("changePct", 0))
        cls = get_color_class(pct)
        bar_width = min(abs(pct) * 8, 100)
        sector_industry_html += f"""
            <div class="sector-bar-item">
                <div class="sector-bar-label">
                    <span class="sector-name">{s['name']}</span>
                    <span class="sector-pct {cls}">{fmt_pct(pct)}</span>
                </div>
                <div class="sector-bar-track">
                    <div class="sector-bar-fill {cls}" style="width: {bar_width}%"></div>
                </div>
                <div class="sector-bar-extra">
                    <span>领涨: {s.get('leadStock', '--')}</span>
                    <span>5日 {fmt_pct(float(s.get('changePct5d', 0)))}</span>
                </div>
            </div>"""

    # Sector capital flow HTML
    sector_capital_html = ""
    for s in sectors["capital_inflow"]:
        inflow = float(s.get("mainNetInflow", 0))
        inflow_5d = float(s.get("mainNetInflow5d", 0))
        cls = "up" if inflow >= 0 else "down"
        cls_5d = "up" if inflow_5d >= 0 else "down"
        sector_capital_html += f"""
            <div class="capital-flow-item">
                <div class="cf-name">{s['name']}</div>
                <div class="cf-bar-container">
                    <div class="cf-bar {cls}" style="width: {min(abs(inflow) / 200, 100)}%">
                        <span class="cf-amount">{inflow:,.0f}万</span>
                    </div>
                </div>
                <div class="cf-5d">5日累计 <span class="{cls_5d}">{inflow_5d:,.0f}万</span></div>
                <div class="cf-ratio">涨跌 {s.get('upDownRatio', '--')}</div>
            </div>"""

    # Concept gainers HTML
    concept_html = ""
    for s in sectors["concept_gainers"]:
        pct = float(s.get("changePct", 0))
        cls = get_color_class(pct)
        concept_html += f"""
            <div class="concept-tag">
                <span class="concept-name">{s['name']}</span>
                <span class="concept-pct {cls}">{fmt_pct(pct)}</span>
            </div>"""

    # News HTML
    news_html = ""
    for n in news:
        news_html += f"""
            <div class="news-item">
                <div class="news-rank">{n['rank']}</div>
                <div class="news-content">
                    <div class="news-title">{n['title']}</div>
                    <div class="news-meta">
                        <span class="news-source">{n['source']}</span>
                        <span class="news-time">{n['time']}</span>
                    </div>
                </div>
            </div>"""

    # Current date display
    now = datetime.now()
    current_time_str = now.strftime("%Y-%m-%d %H:%M")
    hour = now.hour
    if hour < 15:
        data_note = f"当前时间 {current_time_str}（盘中），展示最新收盘日 {CURRENT_DATE} 数据"
    else:
        data_note = f"当前时间 {current_time_str}（收盘后），展示今日 {CURRENT_DATE} 数据"

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>A股市场全景看板</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
            background: #f0f2f5;
            color: #333;
            line-height: 1.6;
        }}

        .container {{
            max-width: 1400px;
            margin: 0 auto;
            padding: 20px;
        }}

        /* Header */
        .header {{
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
            color: #fff;
            padding: 30px 40px;
            border-radius: 16px;
            margin-bottom: 24px;
            box-shadow: 0 4px 20px rgba(0,0,0,0.15);
        }}

        .header h1 {{
            font-size: 28px;
            font-weight: 700;
            margin-bottom: 8px;
        }}

        .header .subtitle {{
            font-size: 14px;
            opacity: 0.8;
        }}

        .header .data-note {{
            display: inline-block;
            background: rgba(255,255,255,0.15);
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 13px;
            margin-top: 8px;
        }}

        /* Section */
        .section {{
            background: #fff;
            border-radius: 16px;
            padding: 28px;
            margin-bottom: 24px;
            box-shadow: 0 2px 12px rgba(0,0,0,0.06);
        }}

        .section-title {{
            font-size: 20px;
            font-weight: 700;
            margin-bottom: 20px;
            padding-left: 12px;
            border-left: 4px solid #0f3460;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }}

        .section-title .section-badge {{
            font-size: 12px;
            font-weight: 400;
            color: #999;
            background: #f5f5f5;
            padding: 2px 10px;
            border-radius: 12px;
        }}

        /* Index Cards Grid */
        .index-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
            gap: 16px;
            margin-bottom: 24px;
        }}

        .index-card {{
            background: #fff;
            border: 2px solid #eee;
            border-radius: 12px;
            padding: 20px;
            cursor: pointer;
            transition: all 0.3s ease;
            position: relative;
            overflow: hidden;
        }}

        .index-card:hover {{
            border-color: #0f3460;
            box-shadow: 0 4px 16px rgba(15, 52, 96, 0.15);
            transform: translateY(-2px);
        }}

        .index-card.active {{
            border-color: #0f3460;
            background: #f8fafe;
            box-shadow: 0 4px 16px rgba(15, 52, 96, 0.15);
        }}

        .card-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 12px;
        }}

        .index-name {{
            font-size: 16px;
            font-weight: 600;
            color: #333;
        }}

        .index-code {{
            font-size: 12px;
            color: #999;
            font-family: monospace;
        }}

        .card-value {{
            font-size: 28px;
            font-weight: 700;
            font-family: "SF Mono", "Roboto Mono", monospace;
            margin-bottom: 4px;
        }}

        .card-rt {{
            font-size: 13px;
            color: #666;
            margin-bottom: 16px;
        }}

        .rt-pct {{
            font-weight: 600;
        }}

        .card-comparisons {{
            border-top: 1px solid #f0f0f0;
            padding-top: 12px;
        }}

        .comp-row {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 4px 0;
        }}

        .comp-label {{
            font-size: 13px;
            color: #888;
        }}

        .comp-value {{
            font-size: 14px;
            font-weight: 600;
            font-family: monospace;
        }}

        .card-footer {{
            display: flex;
            justify-content: space-between;
            margin-top: 12px;
            padding-top: 8px;
            border-top: 1px solid #f0f0f0;
            font-size: 12px;
            color: #999;
        }}

        /* Colors - Chinese stock market convention: red=up, green=down */
        .up {{ color: #e74c3c; }}
        .down {{ color: #27ae60; }}
        .neutral {{ color: #999; }}

        .sector-bar-fill.up {{ background: #e74c3c; }}
        .sector-bar-fill.down {{ background: #27ae60; }}
        .cf-bar.up {{ background: linear-gradient(90deg, #e74c3c, #c0392b); }}
        .cf-bar.down {{ background: linear-gradient(90deg, #27ae60, #229954); }}

        /* Chart Container */
        .chart-container {{
            background: #fff;
            border-radius: 12px;
            padding: 24px;
            margin-top: 16px;
            border: 1px solid #eee;
        }}

        .chart-title {{
            font-size: 16px;
            font-weight: 600;
            margin-bottom: 16px;
            color: #333;
        }}

        .chart-wrapper {{
            position: relative;
            height: 400px;
        }}

        /* Sector Section */
        .sector-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 24px;
        }}

        .sector-subsection {{
            background: #fafafa;
            border-radius: 12px;
            padding: 20px;
        }}

        .sector-subsection h3 {{
            font-size: 15px;
            font-weight: 600;
            margin-bottom: 16px;
            color: #555;
        }}

        .sector-bar-item {{
            margin-bottom: 14px;
        }}

        .sector-bar-label {{
            display: flex;
            justify-content: space-between;
            margin-bottom: 4px;
        }}

        .sector-name {{
            font-size: 14px;
            font-weight: 500;
        }}

        .sector-pct {{
            font-size: 14px;
            font-weight: 600;
            font-family: monospace;
        }}

        .sector-bar-track {{
            height: 8px;
            background: #e8e8e8;
            border-radius: 4px;
            overflow: hidden;
        }}

        .sector-bar-fill {{
            height: 100%;
            border-radius: 4px;
            transition: width 0.5s ease;
        }}

        .sector-bar-extra {{
            display: flex;
            justify-content: space-between;
            font-size: 12px;
            color: #999;
            margin-top: 4px;
        }}

        /* Capital Flow */
        .capital-flow-item {{
            display: grid;
            grid-template-columns: 100px 1fr auto;
            gap: 12px;
            align-items: center;
            padding: 10px 0;
            border-bottom: 1px solid #f0f0f0;
        }}

        .capital-flow-item:last-child {{
            border-bottom: none;
        }}

        .cf-name {{
            font-size: 14px;
            font-weight: 500;
        }}

        .cf-bar-container {{
            height: 24px;
            background: #f5f5f5;
            border-radius: 12px;
            overflow: hidden;
            position: relative;
        }}

        .cf-bar {{
            height: 100%;
            border-radius: 12px;
            display: flex;
            align-items: center;
            justify-content: flex-end;
            padding-right: 8px;
            min-width: 60px;
            transition: width 0.5s ease;
        }}

        .cf-amount {{
            font-size: 12px;
            color: #fff;
            font-weight: 600;
            white-space: nowrap;
        }}

        .cf-5d {{
            font-size: 12px;
            color: #999;
            text-align: right;
            white-space: nowrap;
        }}

        .cf-ratio {{
            font-size: 11px;
            color: #aaa;
            text-align: right;
        }}

        /* Concept Tags */
        .concept-tags {{
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
        }}

        .concept-tag {{
            background: #fff;
            border: 1px solid #e0e0e0;
            border-radius: 20px;
            padding: 6px 14px;
            display: flex;
            align-items: center;
            gap: 6px;
            font-size: 13px;
        }}

        .concept-name {{
            color: #555;
        }}

        .concept-pct {{
            font-weight: 600;
            font-family: monospace;
            font-size: 13px;
        }}

        /* News */
        .news-list {{
            display: flex;
            flex-direction: column;
            gap: 0;
        }}

        .news-item {{
            display: flex;
            gap: 16px;
            padding: 14px 0;
            border-bottom: 1px solid #f0f0f0;
            align-items: flex-start;
        }}

        .news-item:last-child {{
            border-bottom: none;
        }}

        .news-rank {{
            min-width: 32px;
            height: 32px;
            border-radius: 8px;
            background: #f0f2f5;
            color: #666;
            font-size: 14px;
            font-weight: 700;
            display: flex;
            align-items: center;
            justify-content: center;
            flex-shrink: 0;
        }}

        .news-rank:nth-child(-n+3) {{
            background: linear-gradient(135deg, #ff6b6b, #ee5a24);
            color: #fff;
        }}

        .news-content {{
            flex: 1;
        }}

        .news-title {{
            font-size: 15px;
            font-weight: 500;
            color: #333;
            margin-bottom: 4px;
            line-height: 1.5;
        }}

        .news-meta {{
            display: flex;
            gap: 12px;
            font-size: 12px;
            color: #999;
        }}

        .news-source {{
            color: #0f3460;
        }}

        /* Nanhua note */
        .nanhua-note {{
            background: #fff3cd;
            border: 1px solid #ffeaa7;
            border-radius: 8px;
            padding: 10px 16px;
            font-size: 13px;
            color: #856404;
            margin-top: 12px;
        }}

        /* Footer */
        .footer {{
            text-align: center;
            padding: 20px;
            color: #999;
            font-size: 12px;
        }}

        .footer p {{
            margin: 4px 0;
        }}

        @media (max-width: 768px) {{
            .sector-grid {{
                grid-template-columns: 1fr;
            }}
            .index-grid {{
                grid-template-columns: 1fr;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <!-- Header -->
        <div class="header">
            <h1>A股市场全景看板</h1>
            <div class="subtitle">主要指数 / 行业资金流向 / 热点资讯</div>
            <div class="data-note">{data_note}</div>
        </div>

        <!-- Section 1: Indices -->
        <div class="section">
            <div class="section-title">
                <span>一、主要指数概览</span>
                <span class="section-badge">数据日期 {CURRENT_DATE}</span>
            </div>

            <div class="index-grid">
                {index_cards}
            </div>

            <div class="nanhua-note">
                注：南华商品指数暂不在数据源覆盖范围内，已展示其余7大核心指数。当前为盘中时段，指数数值以最新收盘日为准，对比基准为前一交易日、上周同期及上月同期收盘价。
            </div>

            <div class="chart-container">
                <div class="chart-title" id="chartTitle">近1月走势 - 上证指数</div>
                <div class="chart-wrapper">
                    <canvas id="trendChart"></canvas>
                </div>
            </div>
        </div>

        <!-- Section 2: Sectors -->
        <div class="section">
            <div class="section-title">
                <span>二、行业板块资金流向</span>
                <span class="section-badge">实时数据</span>
            </div>

            <div class="sector-grid">
                <div class="sector-subsection">
                    <h3>行业涨幅榜 TOP6</h3>
                    {sector_industry_html}
                </div>

                <div class="sector-subsection">
                    <h3>主力资金净流入 TOP3</h3>
                    {sector_capital_html}
                </div>
            </div>

            <div class="sector-subsection" style="margin-top: 24px;">
                <h3>概念板块涨幅榜 TOP6</h3>
                <div class="concept-tags">
                    {concept_html}
                </div>
            </div>
        </div>

        <!-- Section 3: News -->
        <div class="section">
            <div class="section-title">
                <span>三、近3天行业热点新闻</span>
                <span class="section-badge">TOP 30</span>
            </div>
            <div class="news-list">
                {news_html}
            </div>
        </div>

        <!-- Footer -->
        <div class="footer">
            <p>数据来源：腾讯自选股 | 生成时间：{current_time_str}</p>
            <p>本看板仅供信息展示，不构成投资建议。投资有风险，决策需谨慎。</p>
        </div>
    </div>

    <script>
        // Chart data from Python
        const chartData = {chart_data_js};

        // Initialize trend chart
        const ctx = document.getElementById('trendChart').getContext('2d');
        let trendChart = null;

        function renderChart(code) {{
            const data = chartData.find(d => d.code === code);
            if (!data) return;

            document.getElementById('chartTitle').textContent = `近1月走势 - ${{data.name}}`;

            // Update active card
            document.querySelectorAll('.index-card').forEach(c => c.classList.remove('active'));
            const card = document.getElementById(`card-${{code}}`);
            if (card) card.classList.add('active');

            if (trendChart) {{
                trendChart.destroy();
            }}

            // Split dates into those <= CURRENT_DATE and the latest intraday
            const labels = data.dates;
            const values = data.values;

            // Mark current date index
            const currentDate = '{CURRENT_DATE}';
            const currentIdx = labels.indexOf(currentDate);

            // Point background colors: highlight current date
            const pointBgColors = labels.map((d, i) => {{
                if (i === currentIdx) return '#0f3460';
                if (i === labels.length - 1) return '#f39c12'; // today's intraday
                return 'rgba(15, 52, 96, 0.3)';
            }});

            const pointRadii = labels.map((d, i) => {{
                if (i === currentIdx) return 6;
                if (i === labels.length - 1) return 5;
                return 3;
            }});

            trendChart = new Chart(ctx, {{
                type: 'line',
                data: {{
                    labels: labels,
                    datasets: [{{
                        label: data.name,
                        data: values,
                        borderColor: '#0f3460',
                        backgroundColor: 'rgba(15, 52, 96, 0.08)',
                        borderWidth: 2,
                        fill: true,
                        tension: 0.3,
                        pointBackgroundColor: pointBgColors,
                        pointBorderColor: pointBgColors.map(c => c === '#f39c12' ? '#f39c12' : '#fff'),
                        pointBorderWidth: 2,
                        pointRadius: pointRadii,
                        pointHoverRadius: 7,
                    }}]
                }},
                options: {{
                    responsive: true,
                    maintainAspectRatio: false,
                    interaction: {{
                        mode: 'index',
                        intersect: false,
                    }},
                    plugins: {{
                        legend: {{
                            display: false,
                        }},
                        tooltip: {{
                            callbacks: {{
                                label: function(context) {{
                                    const idx = context.dataIndex;
                                    const date = context.label;
                                    const val = context.parsed.y;
                                    let label = `${{date}}: ${{val.toLocaleString('zh-CN', {{minimumFractionDigits: 2, maximumFractionDigits: 2}})}}`;
                                    if (idx === currentIdx) label += ' [收盘基准]';
                                    if (idx === labels.length - 1 && idx !== currentIdx) label += ' [盘中实时]';
                                    return label;
                                }}
                            }}
                        }}
                    }},
                    scales: {{
                        x: {{
                            grid: {{
                                display: false,
                            }},
                            ticks: {{
                                font: {{ size: 11 }},
                                maxRotation: 45,
                                color: '#888',
                            }}
                        }},
                        y: {{
                            grid: {{
                                color: '#f0f0f0',
                            }},
                            ticks: {{
                                font: {{ size: 11 }},
                                color: '#888',
                                callback: function(value) {{
                                    return value.toLocaleString('zh-CN');
                                }}
                            }}
                        }}
                    }}
                }}
            }});
        }}

        function switchChart(code) {{
            renderChart(code);
        }}

        // Default: render first index
        renderChart('sh000001');
    </script>
</body>
</html>"""

    return html


def main():
    print("Processing index data...")
    try:
        indices, CURRENT_DATE = process_indices()
    except Exception as e:
        print(f"  ERROR processing indices: {e}")
        indices, CURRENT_DATE = [], datetime.now().strftime("%Y-%m-%d")

    print("Processing sector data...")
    try:
        sectors = process_sectors()
    except Exception as e:
        print(f"  ERROR processing sectors: {e}")
        sectors = {"industry_gainers": [], "concept_gainers": [], "capital_inflow": []}

    print("Processing news data...")
    try:
        news = process_news()
    except Exception as e:
        print(f"  ERROR processing news: {e}")
        news = []

    print("Generating HTML...")
    html = generate_html(indices, sectors, news, CURRENT_DATE)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Website generated: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
