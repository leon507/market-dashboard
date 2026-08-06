#!/usr/bin/env python3
"""
Standalone data fetcher for A-share market dashboard.
Uses public APIs (Tencent + Eastmoney) - no local dependencies.
Works in GitHub Actions environment.
"""

import urllib.request
import json
import os
import time
import subprocess
from datetime import datetime, timedelta
from urllib.parse import quote

try:
    import requests
    USE_REQUESTS = True
except ImportError:
    USE_REQUESTS = False

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
os.makedirs(DATA_DIR, exist_ok=True)

INDICES = [
    ("sh000001", "上证指数"),
    ("sz399001", "深证成指"),
    ("sh000300", "沪深300"),
    ("sh000905", "中证500"),
    ("sh000852", "中证1000"),
    ("sz399006", "创业板指"),
    ("sh000688", "科创50"),
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://data.eastmoney.com/",
}


def fetch_url(url, encoding="utf-8", timeout=15):
    """Fetch URL content with retry. Tries requests, then curl, then urllib."""
    for attempt in range(3):
        try:
            text = None
            # Method 1: requests (best for GitHub Actions)
            if USE_REQUESTS:
                try:
                    resp = requests.get(url, headers=HEADERS, timeout=timeout)
                    resp.encoding = encoding
                    text = resp.text
                except Exception:
                    text = None

            # Method 2: curl subprocess (best for local sandboxed environments)
            if not text:
                try:
                    result = subprocess.run(
                        ["curl", "-s", "--max-time", str(timeout), url],
                        capture_output=True,
                        timeout=timeout + 5,
                    )
                    if result.returncode == 0 and result.stdout:
                        text = result.stdout.decode(encoding)
                except Exception:
                    text = None

            # Method 3: urllib (fallback)
            if not text:
                try:
                    req = urllib.request.Request(url, headers=HEADERS)
                    with urllib.request.urlopen(req, timeout=timeout) as resp:
                        text = resp.read().decode(encoding)
                except Exception:
                    text = None

            if text:
                # Strip BOM if present
                if text[0] == "\ufeff":
                    text = text[1:]
                return text

            raise Exception("All fetch methods failed")

        except Exception as e:
            print(f"  Attempt {attempt+1} failed: {e}")
            if attempt < 2:
                time.sleep(2)
    raise Exception(f"Failed to fetch: {url}")


def fetch_quotes():
    """Fetch real-time quotes from Tencent API (GBK encoded)."""
    print("Fetching real-time quotes...")
    codes = ",".join([c for c, _ in INDICES])
    url = f"https://qt.gtimg.cn/q={codes}"
    raw = fetch_url(url, encoding="gbk")

    data_list = []
    for line in raw.strip().split(";"):
        line = line.strip()
        if not line or "=" not in line:
            continue
        code = line.split("=")[0].replace("v_", "")
        value = line.split('"')[1] if '"' in line else ""
        fields = value.split("~")
        if len(fields) < 35:
            continue

        # Find the date+time field (format: YYYYMMDDHHMMSS)
        date_idx = None
        for i, f in enumerate(fields):
            if len(f) == 14 and f.isdigit():
                date_idx = i
                break

        if date_idx is None:
            continue

        # Fields after date: [date+1]=change, [date+2]=change_pct, [date+3]=high, [date+4]=low
        def safe_float(idx):
            if idx < len(fields) and fields[idx]:
                try:
                    return float(fields[idx].split("/")[0])
                except:
                    return 0
            return 0

        # Find PE ratio (usually around field 41, but use relative search)
        pe_ratio = 0
        for i in range(date_idx + 5, min(len(fields), date_idx + 15)):
            try:
                val = float(fields[i])
                if 5 < val < 100:  # Reasonable PE range
                    pe_ratio = val
                    break
            except:
                continue

        # Find total market cap (large number, usually after PE)
        total_mc = 0
        for i in range(date_idx + 8, min(len(fields), date_idx + 20)):
            try:
                val = float(fields[i])
                if 100000 < val < 10000000:  # Reasonable market cap range (亿)
                    total_mc = val
                    break
            except:
                continue

        quote_data = {
            "code": code,
            "name": fields[1],
            "symbol": code,
            "market_type": 1 if code.startswith("sh") else 51,
            "market_name": "上海" if code.startswith("sh") else "深圳",
            "price": safe_float(3),
            "prev_close": safe_float(4),
            "open": safe_float(5),
            "high": safe_float(date_idx + 3),
            "low": safe_float(date_idx + 4),
            "volume": int(safe_float(6)),
            "change": safe_float(date_idx + 1),
            "change_percent": safe_float(date_idx + 2),
            "pe_ratio": pe_ratio,
            "total_market_cap": total_mc,
            "chg_5d": 0,
            "chg_20d": 0,
            "chg_ytd": 0,
        }
        data_list.append({"symbol": code, "data": quote_data})

    result = {"success": True, "status": 200, "data": data_list, "errors": [], "metadata": {}}
    save_json("quotes.json", result)
    print(f"  Saved {len(data_list)} quotes")
    return result


def fetch_kline(code):
    """Fetch 30-day K-line from Tencent API."""
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={code},day,,,30,qfq"
    raw = fetch_url(url)
    data = json.loads(raw)
    kline_data = data.get("data", {}).get(code, {})
    records = kline_data.get("qfqday", kline_data.get("day", []))

    result = []
    for rec in records:
        result.append({
            "date": rec[0],
            "open": float(rec[1]),
            "last": float(rec[2]),
            "high": float(rec[3]),
            "low": float(rec[4]),
            "volume": float(rec[5]) if len(rec) > 5 else 0,
            "amount": 0,
            "exchange": "0",
        })
    # Sort by date descending (newest first) to match westock-data format
    result.sort(key=lambda x: x["date"], reverse=True)
    save_json(f"kline_{code}.json", result)
    print(f"  kline_{code}.json: {len(result)} records")
    return result


def fetch_sectors():
    """Fetch sector rankings from Eastmoney API."""
    print("Fetching sector rankings...")

    # Industry gainers (sorted by change% desc)
    industry = fetch_eastmoney_sectors("m:90+t:2", "f3", 6, is_capital=False)

    # Concept gainers
    concepts = fetch_eastmoney_sectors("m:90+t:3", "f3", 6, is_capital=False)

    # Capital flow (sorted by main net inflow desc)
    capital = fetch_eastmoney_sectors("m:90+t:2", "f62", 3, is_capital=True)

    result = {"sections": [industry, concepts, capital]}
    save_json("sector_ranking.json", result)
    print(f"  Saved: {len(industry)} industries, {len(concepts)} concepts, {len(capital)} capital")
    return result


def fetch_eastmoney_sectors(fs, sort_fid, limit, is_capital):
    """Fetch sector data from Eastmoney clist API."""
    fields = "f2,f3,f4,f12,f14"
    if is_capital:
        fields += ",f62,f184,f66,f69,f72,f75,f128,f136"

    # Do NOT URL-encode - Eastmoney API expects raw + and : characters
    url = (
        f"https://push2.eastmoney.com/api/qt/clist/get?"
        f"pn=1&pz={limit}&po=1&np=1&fltt=2&invt=2&fid={sort_fid}&fs={fs}&fields={fields}"
    )
    raw = fetch_url(url)
    data = json.loads(raw)
    items = data.get("data", {}).get("diff", [])

    result = []
    for item in items:
        entry = {
            "name": item.get("f14", ""),
            "changePct": str(round(item.get("f3", 0), 2)),
            "turnoverRate": "0",
            "changePct5d": "0",
            "changePct20d": "0",
            "leadStock": "--",
        }
        if is_capital:
            inflow = item.get("f62", 0)
            inflow_5d = item.get("f184", 0)
            entry["mainNetInflow"] = str(round(inflow / 10000, 2))  # Convert to 万
            entry["mainNetInflow5d"] = str(round(inflow_5d / 10000, 2))
            entry["upDownRatio"] = "--"
        result.append(entry)
    return result


def fetch_news():
    """Fetch market news from Eastmoney kuaixun API."""
    print("Fetching news...")
    news = []

    # Eastmoney kuaixun (快讯) API - returns var ajaxResult={...};
    try:
        url = "https://newsapi.eastmoney.com/kuaixun/v1/getlist_101_ajaxResult_30_1_.html"
        raw = fetch_url(url)
        # Strip JavaScript variable assignment
        raw = raw.replace("var ajaxResult=", "").strip().rstrip(";")
        data = json.loads(raw)
        items = data.get("LivesList", [])

        for i, item in enumerate(items):
            title = item.get("title", "")
            showtime = item.get("showtime", "")
            editor = item.get("editor_name", "") or "东方财富"

            # Parse timestamp from showtime
            ts = 0
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
                try:
                    ts = int(datetime.strptime(showtime, fmt).timestamp())
                    break
                except:
                    continue
            if ts == 0:
                ts = int(time.time())

            news.append({
                "news_id": item.get("newsid", f"news_{i}"),
                "news_title": title,
                "rank": str(i + 1),
                "publish_time": ts,
                "source": editor,
                "news_type": 1,
                "cont_type": 0,
                "property": 0,
                "has_video": 0,
                "images": [],
            })
    except Exception as e:
        print(f"  Eastmoney kuaixun failed: {e}, trying Sina fallback...")

        # Fallback: Sina Finance roll news
        try:
            url = "https://feed.mix.sina.com.cn/api/roll/get?pageid=153&lid=2516&k=&num=30&page=1"
            raw = fetch_url(url, encoding="utf-8")
            data = json.loads(raw)
            items = data.get("result", {}).get("data", [])

            for i, item in enumerate(items):
                news.append({
                    "news_id": str(item.get("docid", f"sina_{i}")),
                    "news_title": item.get("title", ""),
                    "rank": str(i + 1),
                    "publish_time": int(item.get("ctime", time.time())),
                    "source": item.get("media_name", "新浪财经"),
                    "news_type": 1,
                    "cont_type": 0,
                    "property": 0,
                    "has_video": 0,
                    "images": [],
                })
        except Exception as e2:
            print(f"  Sina fallback also failed: {e2}")

    save_json("news.json", news)
    print(f"  Saved {len(news)} news items")
    return news


def save_json(filename, data):
    """Save JSON to data directory."""
    path = os.path.join(DATA_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def main():
    print("=== Standalone Data Fetch ===")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # 1. Quotes
    fetch_quotes()

    # 2. K-line for each index
    print("Fetching K-line data...")
    for code, name in INDICES:
        fetch_kline(code)
        time.sleep(0.3)  # Be polite

    # 3. Sectors
    fetch_sectors()

    # 4. News
    fetch_news()

    print("=== Data fetch complete ===")


if __name__ == "__main__":
    main()
