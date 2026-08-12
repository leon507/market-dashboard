#!/usr/bin/env python3
"""
Standalone data fetcher for A-share market dashboard.
Uses public APIs (Tencent + Eastmoney + Yahoo Finance) - no local dependencies.
Works in GitHub Actions environment (US-based servers).
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
    ("sh000001", "上证指数", "000001.SS"),
    ("sz399001", "深证成指", "399001.SZ"),
    ("sh000300", "沪深300", "000300.SS"),
    ("sh000905", "中证500", "000905.SS"),
    ("sh000852", "中证1000", "000852.SS"),
    ("sz399006", "创业板指", "399006.SZ"),
    ("sh000688", "科创50", "000688.SS"),
]

# Eastmoney secid mapping: sh -> 1.xxxxxx, sz -> 0.xxxxxx
EASTMONEY_SECID = {
    "sh000001": "1.000001",
    "sz399001": "0.399001",
    "sh000300": "1.000300",
    "sh000905": "1.000905",
    "sh000852": "1.000852",
    "sz399006": "0.399006",
    "sh000688": "1.000688",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://data.eastmoney.com/",
}


def fetch_url(url, encoding="utf-8", timeout=20):
    """Fetch URL content with retry. Tries requests, then urllib, then curl."""
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

            # Method 2: urllib (standard library)
            if not text:
                try:
                    req = urllib.request.Request(url, headers=HEADERS)
                    with urllib.request.urlopen(req, timeout=timeout) as resp:
                        text = resp.read().decode(encoding)
                except Exception:
                    text = None

            # Method 3: curl subprocess (fallback)
            if not text:
                try:
                    result = subprocess.run(
                        ["curl", "-s", "-L", "--max-time", str(timeout), url],
                        capture_output=True,
                        timeout=timeout + 5,
                    )
                    if result.returncode == 0 and result.stdout:
                        text = result.stdout.decode(encoding)
                except Exception:
                    text = None

            if text:
                # Strip BOM if present
                if text[0] == "\ufeff":
                    text = text[1:]
                return text

            raise Exception("All fetch methods returned empty")

        except Exception as e:
            print(f"  Attempt {attempt+1} failed: {e}")
            if attempt < 2:
                time.sleep(3)
    return None  # Return None instead of raising, so caller can handle gracefully


def save_json(filename, data):
    """Save JSON to data directory."""
    path = os.path.join(DATA_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ============================================================
# Yahoo Finance API (works internationally - primary for GitHub Actions)
# ============================================================

def fetch_yahoo_chart(yahoo_code, range_str="1mo"):
    """Fetch chart data from Yahoo Finance API."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_code}?interval=1d&range={range_str}"
    raw = fetch_url(url)
    if not raw:
        return None
    try:
        data = json.loads(raw)
        result = data.get("chart", {}).get("result", [])
        if not result:
            return None
        return result[0]
    except Exception as e:
        print(f"  Yahoo Finance parse error: {e}")
        return None


def fetch_quotes_yahoo():
    """Fetch quotes from Yahoo Finance API."""
    print("Fetching real-time quotes (Yahoo Finance)...")
    data_list = []
    for code, name, yahoo_code in INDICES:
        chart = fetch_yahoo_chart(yahoo_code, range_str="5d")
        if not chart:
            print(f"  Failed to fetch {name} from Yahoo")
            continue

        meta = chart.get("meta", {})
        price = meta.get("regularMarketPrice", 0)
        prev_close = meta.get("previousClose", 0)
        chart_prev_close = meta.get("chartPreviousClose", 0)

        change = price - prev_close if price and prev_close else 0
        change_pct = (change / prev_close * 100) if prev_close else 0

        quote_data = {
            "code": code,
            "name": name,
            "symbol": code,
            "market_type": 1 if code.startswith("sh") else 51,
            "market_name": "上海" if code.startswith("sh") else "深圳",
            "price": price,
            "prev_close": prev_close,
            "open": meta.get("regularMarketOpen", 0),
            "high": meta.get("regularMarketDayHigh", 0),
            "low": meta.get("regularMarketDayLow", 0),
            "volume": meta.get("regularMarketVolume", 0),
            "turnover": 0,  # Yahoo Finance doesn't provide turnover directly
            "change": round(change, 2),
            "change_percent": round(change_pct, 2),
            "pe_ratio": 0,
            "total_market_cap": 0,
            "chg_5d": 0,
            "chg_20d": 0,
            "chg_ytd": 0,
        }
        data_list.append({"symbol": code, "data": quote_data})
        time.sleep(0.3)

    if data_list:
        result = {"success": True, "status": 200, "data": data_list, "errors": [], "metadata": {}}
        save_json("quotes.json", result)
        print(f"  Saved {len(data_list)} quotes (Yahoo Finance)")
    return data_list


def fetch_kline_yahoo(code, name, yahoo_code):
    """Fetch 30-day K-line from Yahoo Finance API."""
    chart = fetch_yahoo_chart(yahoo_code, range_str="1mo")
    if not chart:
        return []

    timestamps = chart.get("timestamp", [])
    indicators = chart.get("indicators", {}).get("quote", [{}])[0]
    closes = indicators.get("close", [])
    opens = indicators.get("open", [])
    highs = indicators.get("high", [])
    lows = indicators.get("low", [])
    volumes = indicators.get("volume", [])

    result = []
    for i, ts in enumerate(timestamps):
        dt = datetime.utcfromtimestamp(ts)
        date_str = dt.strftime("%Y-%m-%d")
        close = closes[i] if i < len(closes) and closes[i] else 0
        if close == 0:
            continue
        result.append({
            "date": date_str,
            "open": float(opens[i]) if i < len(opens) and opens[i] else 0,
            "last": float(close),
            "high": float(highs[i]) if i < len(highs) and highs[i] else 0,
            "low": float(lows[i]) if i < len(lows) and lows[i] else 0,
            "volume": float(volumes[i]) if i < len(volumes) and volumes[i] else 0,
            "amount": float(volumes[i]) * float(close) if i < len(volumes) and volumes[i] and close else 0,
            "exchange": "0",
        })

    result.sort(key=lambda x: x["date"], reverse=True)
    save_json(f"kline_{code}.json", result)
    print(f"  kline_{code}.json: {len(result)} records (Yahoo Finance)")
    return result


# ============================================================
# Eastmoney Index API (has turnover/amount - primary source)
# ============================================================

def fetch_quotes_eastmoney():
    """Fetch real-time index quotes from Eastmoney API (includes f6=turnover)."""
    print("Fetching real-time quotes (Eastmoney)...")
    secids = "&".join([f"secid={EASTMONEY_SECID[c]}" for c, _, _ in INDICES])
    fields = "f2,f3,f4,f6,f12,f14,f15,f16,f17,f8,f9,f23,f24"
    url = (
        f"https://push2.eastmoney.com/api/qt/ulist.np/get?"
        f"{secids}&fields={fields}&fltt=2&invt=2"
    )
    raw = fetch_url(url)
    if not raw:
        return None
    try:
        data = json.loads(raw)
        data_field = data.get("data")
        if not data_field:
            print("  Eastmoney quotes: no data field in response")
            return None
        items = data_field.get("diff", [])
        if not items:
            print("  Eastmoney quotes: no diff items in response")
            return None

        data_list = []
        for item in items:
            code_raw = item.get("f12", "")
            # Map back to our code format (sh/sz prefix)
            matching = [c for c, _, _ in INDICES if c.endswith(code_raw)]
            code = matching[0] if matching else code_raw
            name = item.get("f14", "")
            price = item.get("f2", 0)
            change_pct = item.get("f3", 0)
            change = item.get("f4", 0)
            turnover = item.get("f6", 0)  # f6 = turnover (成交额, in yuan)

            quote_data = {
                "code": code,
                "name": name,
                "symbol": code,
                "market_type": 1 if code.startswith("sh") else 51,
                "market_name": "上海" if code.startswith("sh") else "深圳",
                "price": price,
                "prev_close": round(price - change, 2) if change else price,
                "open": item.get("f17", 0),
                "high": item.get("f15", 0),
                "low": item.get("f16", 0),
                "volume": 0,  # Will be filled from K-line if needed
                "turnover": turnover,  # 成交额 in yuan
                "change": change,
                "change_percent": change_pct,
                "pe_ratio": item.get("f9", 0) if item.get("f9") else 0,
                "total_market_cap": 0,
                "chg_5d": 0,
                "chg_20d": 0,
                "chg_ytd": 0,
            }
            data_list.append({"symbol": code, "data": quote_data})

        if data_list:
            result = {"success": True, "status": 200, "data": data_list, "errors": [], "metadata": {}}
            save_json("quotes.json", result)
            print(f"  Saved {len(data_list)} quotes (Eastmoney, with turnover)")
            for d in data_list:
                amt = d["data"].get("turnover", 0)
                print(f"    {d['data']['name']}: turnover={amt/1e8:.2f}亿")
        return data_list
    except Exception as e:
        print(f"  Eastmoney quotes parse error: {e}")
        return None


def fetch_kline_eastmoney(code):
    """Fetch 30-day K-line from Eastmoney API (includes f57=amount/turnover)."""
    secid = EASTMONEY_SECID.get(code)
    if not secid:
        return None

    url = (
        f"https://push2his.eastmoney.com/api/qt/stock/kline/get?"
        f"secid={secid}&fields1=f1,f2,f3,f4,f5,f6"
        f"&fields2=f51,f52,f53,f54,f55,f56,f57"
        f"&klt=101&fqt=1&lmt=30"
    )
    raw = fetch_url(url)
    if not raw:
        return None
    try:
        data = json.loads(raw)
        data_field = data.get("data")
        if not data_field:
            return None
        klines = data_field.get("klines", [])
        if not klines:
            return None

        result = []
        for line in klines:
            parts = line.split(",")
            if len(parts) < 7:
                continue
            result.append({
                "date": parts[0],
                "open": float(parts[1]),
                "last": float(parts[2]),
                "high": float(parts[3]),
                "low": float(parts[4]),
                "volume": float(parts[5]),    # f56 = volume (shares)
                "amount": float(parts[6]),     # f57 = turnover (yuan)
                "exchange": "0",
            })

        result.sort(key=lambda x: x["date"], reverse=True)
        save_json(f"kline_{code}.json", result)
        name = [n for c, n, _ in INDICES if c == code]
        nm = name[0] if name else code
        if result:
            latest = result[0]
            print(f"  kline_{code}.json: {len(result)} records (Eastmoney), latest amount={latest['amount']/1e8:.2f}亿")
        else:
            print(f"  kline_{code}.json: 0 records (Eastmoney)")
        return result
    except Exception as e:
        print(f"  Eastmoney kline parse error for {code}: {e}")
        return None


# ============================================================
# Tencent API (works in China - fallback for local execution)
# ============================================================

def fetch_quotes_tencent():
    """Fetch real-time quotes from Tencent API (GBK encoded)."""
    print("Fetching real-time quotes (Tencent)...")
    codes = ",".join([c for c, _, _ in INDICES])
    url = f"https://qt.gtimg.cn/q={codes}"
    raw = fetch_url(url, encoding="gbk")
    if not raw:
        return None

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

        date_idx = None
        for i, f in enumerate(fields):
            if len(f) == 14 and f.isdigit():
                date_idx = i
                break
        if date_idx is None:
            continue

        def safe_float(idx):
            if idx < len(fields) and fields[idx]:
                try:
                    return float(fields[idx].split("/")[0])
                except:
                    return 0
            return 0

        pe_ratio = 0
        for i in range(date_idx + 5, min(len(fields), date_idx + 15)):
            try:
                val = float(fields[i])
                if 5 < val < 100:
                    pe_ratio = val
                    break
            except:
                continue

        total_mc = 0
        for i in range(date_idx + 8, min(len(fields), date_idx + 20)):
            try:
                val = float(fields[i])
                if 100000 < val < 10000000:
                    total_mc = val
                    break
            except:
                continue

        # Extract turnover (成交额) from composite field: "price/volume/amount_in_yuan"
        turnover = 0
        composite_idx = date_idx + 5
        if composite_idx < len(fields) and "/" in fields[composite_idx]:
            parts = fields[composite_idx].split("/")
            if len(parts) >= 3:
                try:
                    turnover = float(parts[2])
                except:
                    turnover = 0
        # Fallback: field date_idx + 7 is amount in 万元 (multiply by 10000)
        if turnover == 0:
            amt_wan_idx = date_idx + 7
            if amt_wan_idx < len(fields) and fields[amt_wan_idx]:
                try:
                    turnover = float(fields[amt_wan_idx]) * 10000
                except:
                    turnover = 0

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
            "turnover": turnover,  # 成交额 in yuan (extracted from Tencent composite field)
            "change": safe_float(date_idx + 1),
            "change_percent": safe_float(date_idx + 2),
            "pe_ratio": pe_ratio,
            "total_market_cap": total_mc,
            "chg_5d": 0,
            "chg_20d": 0,
            "chg_ytd": 0,
        }
        data_list.append({"symbol": code, "data": quote_data})

    if data_list:
        result = {"success": True, "status": 200, "data": data_list, "errors": [], "metadata": {}}
        save_json("quotes.json", result)
        print(f"  Saved {len(data_list)} quotes (Tencent)")
        for d in data_list:
            amt = d["data"].get("turnover", 0)
            if amt:
                print(f"    {d['data']['name']}: turnover={amt/1e8:.2f}亿")
    return data_list


def fetch_kline_tencent(code):
    """Fetch 30-day K-line from Tencent API."""
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={code},day,,,30,qfq"
    raw = fetch_url(url)
    if not raw:
        return None
    try:
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
        result.sort(key=lambda x: x["date"], reverse=True)
        save_json(f"kline_{code}.json", result)
        print(f"  kline_{code}.json: {len(result)} records (Tencent)")
        return result
    except Exception as e:
        print(f"  Tencent kline parse error: {e}")
        return None


# ============================================================
# Eastmoney API (for sectors and news)
# ============================================================

def fetch_eastmoney_sectors(fs, sort_fid, limit, is_capital):
    """Fetch sector data from Eastmoney clist API."""
    fields = "f2,f3,f4,f12,f14"
    if is_capital:
        fields += ",f62,f184,f66,f69,f72,f75,f128,f136"

    url = (
        f"https://push2.eastmoney.com/api/qt/clist/get?"
        f"pn=1&pz={limit}&po=1&np=1&fltt=2&invt=2&fid={sort_fid}&fs={fs}&fields={fields}"
    )
    raw = fetch_url(url)
    if not raw:
        return []
    try:
        data = json.loads(raw)
        items = data.get("data", {}).get("diff", [])

        result = []
        for item in items:
            entry = {
                "name": item.get("f14", ""),
                "changePct": str(round(float(item.get("f3", 0) or 0), 2)),
                "turnoverRate": "0",
                "changePct5d": "0",
                "changePct20d": "0",
                "leadStock": "--",
            }
            if is_capital:
                inflow = float(item.get("f62", 0) or 0)
                inflow_5d = float(item.get("f184", 0) or 0)
                entry["mainNetInflow"] = str(round(inflow / 10000, 2))
                entry["mainNetInflow5d"] = str(round(inflow_5d / 10000, 2))
                entry["upDownRatio"] = "--"
            result.append(entry)
        return result
    except Exception as e:
        print(f"  Eastmoney sector parse error: {e}")
        return []


def fetch_sectors():
    """Fetch sector rankings. Tries Eastmoney, preserves old data on failure."""
    print("Fetching sector rankings...")
    industry = fetch_eastmoney_sectors("m:90+t:2", "f3", 6, is_capital=False)
    concepts = fetch_eastmoney_sectors("m:90+t:3", "f3", 6, is_capital=False)
    capital = fetch_eastmoney_sectors("m:90+t:2", "f62", 3, is_capital=True)

    result = {"sections": [industry, concepts, capital]}

    # Only save if we got at least some data; otherwise preserve previous data
    if industry or concepts or capital:
        save_json("sector_ranking.json", result)
        print(f"  Saved: {len(industry)} industries, {len(concepts)} concepts, {len(capital)} capital")
    else:
        old_path = os.path.join(DATA_DIR, "sector_ranking.json")
        if os.path.exists(old_path):
            print("  All sectors empty, preserving previous data")
        else:
            save_json("sector_ranking.json", result)
            print("  No previous data, saved empty sectors")
    return result


def fetch_news():
    """Fetch market news. Tries Eastmoney, then Sina fallback."""
    print("Fetching news...")
    news = []

    # Try Eastmoney kuaixun API
    try:
        url = "https://newsapi.eastmoney.com/kuaixun/v1/getlist_101_ajaxResult_30_1_.html"
        raw = fetch_url(url)
        if raw:
            raw = raw.replace("var ajaxResult=", "").strip().rstrip(";")
            data = json.loads(raw)
            items = data.get("LivesList", [])

            for i, item in enumerate(items):
                title = item.get("title", "")
                showtime = item.get("showtime", "")
                editor = item.get("editor_name", "") or "东方财富"

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
        print(f"  Eastmoney news failed: {e}")

    # Fallback: Sina Finance
    if not news:
        print("  Trying Sina Finance fallback...")
        try:
            url = "https://feed.mix.sina.com.cn/api/roll/get?pageid=153&lid=2516&k=&num=30&page=1"
            raw = fetch_url(url, encoding="utf-8")
            if raw:
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


# ============================================================
# Main: try Chinese APIs first, fall back to Yahoo Finance
# ============================================================

def main():
    print("=== Standalone Data Fetch ===")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"requests available: {USE_REQUESTS}")
    print()

    # 1. Quotes: try Eastmoney first (has turnover), then Tencent, then Yahoo
    quotes_result = fetch_quotes_eastmoney()
    if not quotes_result:
        print("  Eastmoney failed, trying Tencent...")
        quotes_result = fetch_quotes_tencent()
    if not quotes_result:
        print("  Tencent failed, trying Yahoo Finance...")
        fetch_quotes_yahoo()
    print()

    # 2. K-line: try Eastmoney first (has amount), then Tencent, then Yahoo
    print("Fetching K-line data...")
    for code, name, yahoo_code in INDICES:
        result = fetch_kline_eastmoney(code)
        if not result:
            print(f"  Eastmoney kline failed for {name}, trying Tencent...")
            result = fetch_kline_tencent(code)
        if not result:
            print(f"  Tencent kline failed for {name}, trying Yahoo Finance...")
            fetch_kline_yahoo(code, name, yahoo_code)
        time.sleep(0.3)
    print()

    # 2b. Patch K-line amount from quotes turnover (for Tencent fallback which lacks amount)
    print("Patching K-line turnover from quotes...")
    try:
        quotes_path = os.path.join(DATA_DIR, "quotes.json")
        if os.path.exists(quotes_path):
            with open(quotes_path, "r", encoding="utf-8") as f:
                quotes_data = json.load(f)
            for item in quotes_data.get("data", []):
                code = item.get("symbol", "")
                turnover = item.get("data", {}).get("turnover", 0)
                if not turnover:
                    continue
                kline_path = os.path.join(DATA_DIR, f"kline_{code}.json")
                if not os.path.exists(kline_path):
                    continue
                with open(kline_path, "r", encoding="utf-8") as f:
                    kline = json.load(f)
                if not kline:
                    continue
                # Patch latest record's amount if it's 0
                patched = False
                if kline[0].get("amount", 0) == 0:
                    kline[0]["amount"] = turnover
                    patched = True
                if patched:
                    with open(kline_path, "w", encoding="utf-8") as f:
                        json.dump(kline, f, ensure_ascii=False, indent=2)
                    name = [n for c, n, _ in INDICES if c == code]
                    nm = name[0] if name else code
                    print(f"  Patched {nm}: latest amount={turnover/1e8:.2f}亿")
    except Exception as e:
        print(f"  K-line patch failed: {e}")
    print()

    # 3. Sectors (Eastmoney only, no international fallback)
    try:
        fetch_sectors()
    except Exception as e:
        print(f"  Sector fetch failed: {e}")
        # Don't overwrite - keep previous data if it exists
        old_path = os.path.join(DATA_DIR, "sector_ranking.json")
        if not os.path.exists(old_path):
            save_json("sector_ranking.json", {"sections": [[], [], []]})
    print()

    # 4. News
    try:
        fetch_news()
    except Exception as e:
        print(f"  News fetch failed: {e}")
        save_json("news.json", [])
    print()

    print("=== Data fetch complete ===")


if __name__ == "__main__":
    main()
