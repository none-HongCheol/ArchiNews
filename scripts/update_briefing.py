import json, os, urllib.parse, urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

KST = timezone(timedelta(hours=9))
QUERY = "건설 수주 OR 건설 시공 OR 정비사업 OR 건설 발주"
FEED = "https://news.google.com/rss/search?" + urllib.parse.urlencode(
    {"q": QUERY, "hl": "ko", "gl": "KR", "ceid": "KR:ko"})
DATA = "data/briefings.json"
MAX_DAYS = 30
DEFAULT_STAT = {"label": "직접 입력 필요", "value": "-", "unit": "",
                "change": "", "sentiment": "", "index": 0}

def category_of(title):
    if any(k in title for k in ["설계", "정비", "재건축", "재개발"]): return "설계·정비사업"
    if any(k in title for k in ["발주", "입찰", "LH", "조달", "공공"]): return "공공 발주"
    if any(k in title for k in ["수주", "시공"]): return "시공 수주"
    if any(k in title for k in ["지수", "전망", "수주액", "통계"]): return "경기 지표"
    return "업계·금융"

def fetch_articles():
    req = urllib.request.Request(FEED, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        root = ET.fromstring(r.read())
    now = datetime.now(KST)
    seen, articles = set(), []
    for it in root.iter("item"):
        raw = it.findtext("title", "")
        link = it.findtext("link", "")
        pub = it.findtext("pubDate")
        dt = parsedate_to_datetime(pub).astimezone(KST) if pub else now
        if now - dt > timedelta(hours=36):
            continue
        title, _, source = raw.rpartition(" - ")
        if not title:
            title, source = raw, ""
        if title in seen:
            continue
        seen.add(title)
        articles.append({
            "category": category_of(title),
            "title": title,
            "summary": "",
            "source": source,
            "date": dt.strftime("%m.%d"),
            "url": link,
        })
    return articles[:12]

def main():
    os.makedirs("data", exist_ok=True)
    briefings = []
    if os.path.exists(DATA):
        with open(DATA, encoding="utf-8") as f:
            briefings = json.load(f)
    today = datetime.now(KST).strftime("%Y-%m-%d")
    articles = fetch_articles()
    entry = {
        "date": today,
        "keyPoints": [{"title": a["title"], "text": ""} for a in articles[:3]],
        "stat": briefings[0]["stat"] if briefings else DEFAULT_STAT,
        "articles": articles,
    }
    briefings = [b for b in briefings if b["date"] != today]
    briefings.insert(0, entry)
    briefings.sort(key=lambda b: b["date"], reverse=True)
    with open(DATA, "w", encoding="utf-8") as f:
        json.dump(briefings[:MAX_DAYS], f, ensure_ascii=False, indent=2)
    print(f"{today}: 기사 {len(articles)}건 저장")

if __name__ == "__main__":
    main()
