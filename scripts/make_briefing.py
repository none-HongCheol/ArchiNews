#!/usr/bin/env python3
"""건설·건축 데일리 브리핑 생성 스크립트.

매일 자동으로 실행되어
  1) 회사 Open WebUI(또는 OpenAI API)에 웹 검색을 시켜 최근 뉴스를 모으고
  2) 정해진 JSON 형식으로 브리핑을 받아 검증한 뒤
  3) data/YYYY-MM-DD.json 을 쓰고 data/index.json 맨 앞에 그날 항목을 추가합니다.

외부 패키지 없이 파이썬 표준 라이브러리만 씁니다.

환경 변수
  BRIEFING_BACKEND    openwebui(기본) 또는 openai

  [openwebui]
  OPENWEBUI_URL       (필수) 예: https://ai.aaarchigroup-ai.com
  OPENWEBUI_API_KEY   (필수) Open WebUI 설정 > 계정 > API 키
  OPENWEBUI_MODEL     (필수) Open WebUI의 모델 ID (예: gpt-6-luna)

  [openai]
  OPENAI_API_KEY      (필수) OpenAI API 키
  OPENAI_MODEL        (선택) 기본값 gpt-6-luna
  OPENAI_EFFORT       (선택) low / medium / high. 기본값 medium

  공통
  BRIEFING_DATE       (선택) YYYY-MM-DD. 비우면 오늘(한국시간)
  BRIEFING_MOCK_FILE  (테스트용) 모델 대신 이 파일 내용을 응답으로 사용
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
KST = ZoneInfo("Asia/Seoul")
WEEKDAYS = "월화수목금토일"
CATS = {"design", "seoul", "build", "public", "market", "biz"}

COMPANY = "AA아키그룹(에이에이아키그룹건축사사무소, 영문 AA Archigroup)"
COMPANY_NEWSROOM = "https://www.aaarchigroup.com/news"

SYSTEM = f"""당신은 한국 건축설계 회사 {COMPANY}의 사내 뉴스 브리핑 편집자입니다.
매일 아침 임직원이 5분 안에 읽을 건설·건축 업계 브리핑을 한국어로 만듭니다.

반드시 지킬 규칙
- 웹 검색으로 직접 확인한 기사만 씁니다. 기억이나 추측으로 기사·숫자·날짜·URL을 만들지 않습니다.
- 기사 본문을 복사하지 않습니다. 제목(t)과 요약(p)은 모두 직접 새로 씁니다. 원문 문장을 그대로 옮기지 않습니다.
- 모든 기사에 실제 원문 URL을 붙입니다. URL은 검색 결과에서 확인한 것만 씁니다.
- 최근 7일 이내 기사만 씁니다. 기사 날짜를 반드시 확인합니다.
- 블로그·업체 홍보글처럼 출처가 약하면 출처명에 그렇게 표시합니다. 예: "산군 블로그(입찰정보 업체)"
- 최종 출력은 JSON 하나만 씁니다. 설명, 마크다운, 코드블록 표시는 쓰지 않습니다."""

SCHEMA_HINT = """출력 JSON 형식 (키 이름과 구조를 정확히 지킬 것)
{
 "key": [ {"b": "굵게 보일 한 줄 요지(마침표로 끝)", "t": "보충 한 문장"} ],   // 정확히 3개
 "figure": {"label": "숫자 설명", "value": "24.6", "unit": "조원", "change": "전년 동월 대비 +49.3%", "note": "짧은 맥락"},
 "gauge": {"label": "지수 이름 (기준선 100)", "value": 74.9, "note": "짧은 해석"},   // 기준선 100짜리 지수가 있을 때만. 없으면 키 자체를 생략
 "aa": {
   "today": [ {"d": "YYYY.MM.DD", "t": "제목", "p": "한 줄 요약", "u": "https://..."} ],   // 회사 관련 새 보도. 없으면 []
   "recent": [ {"d": "YYYY.MM.DD", "t": "제목", "u": "https://..."} ],   // 최근 보도 최대 4건
   "signal": "회사 사업(반도체·데이터센터 등 하이테크, 주거, 업무·복합)과 연결되는 오늘의 시장 신호 1~2문장"
 },
 "news": [
   {"c": "design|seoul|build|public|market|biz 중 하나", "t": "제목", "p": "2~3문장 요약",
    "s": [["언론사", "MM.DD", "https://..."]]}
 ],   // 6~12건
 "head": "그날 핵심 한 줄 (40자 안팎)",
 "cal": [ ["날짜", "다가오는 총회·입찰마감·발표 일정"] ]   // 0~5건
}
분야(c) 뜻
- design: 재건축·재개발 설계자 선정, 설계공모, 건축사사무소 동향
- seoul: 서울시 공공건축 설계공모(프로젝트 서울 project.seoul.go.kr)의 공고·마감·심사·당선 발표
- build: 정비사업 시공사 선정, 건설사 수주
- public: LH·조달청·공공기관 발주, 입찰
- market: 건설수주·기성·CBSI·공사비지수 등 경기 지표
- biz: PF, 건설사 실적·인사, 정책·규제"""


# ---------------------------------------------------------------- 공통 유틸
def today_kst() -> dt.date:
    raw = os.environ.get("BRIEFING_DATE", "").strip()
    if raw:
        return dt.date.fromisoformat(raw)
    return dt.datetime.now(KST).date()


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def need(name: str) -> str:
    v = os.environ.get(name, "").strip()
    if not v:
        sys.exit(f"{name} 가 설정되지 않았습니다. GitHub 저장소 Settings > Secrets and variables > Actions 에 등록하세요.")
    return v


def http(method: str, url: str, key: str, body: dict | None = None, timeout: int = 120):
    """JSON 요청 한 번. 일시 오류는 최대 3번 재시도합니다."""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    for attempt in range(3):
        req = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": f"Bearer {key}", "Content-Type": "application/json", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read().decode("utf-8")
                return json.loads(raw) if raw.strip() else None
        except urllib.error.HTTPError as e:
            msg = e.read().decode("utf-8", "replace")
            if e.code in (429, 500, 502, 503, 504) and attempt < 2:
                time.sleep(20 * (attempt + 1))
                continue
            raise RuntimeError(f"HTTP {e.code} {url}\n{msg[:800]}") from None
        except urllib.error.URLError as e:
            if attempt < 2:
                time.sleep(20)
                continue
            raise RuntimeError(f"서버에 연결하지 못했습니다: {url} ({e.reason})") from None


# ---------------------------------------------------------------- 프롬프트
def prev_context(day: dt.date, index: list) -> tuple[str, str]:
    """어제 실린 기사 제목 목록과 회사 최근 보도 목록을 돌려줍니다."""
    prev_titles: list[str] = []
    prev_aa: list = []
    earlier = [e for e in index if isinstance(e, dict) and e.get("date", "") < day.isoformat()][:2]
    for i, entry in enumerate(earlier):
        prev = load_json(DATA / f"{entry.get('date')}.json", {})
        prev_titles += [n.get("t", "") for n in prev.get("news", [])]
        if i == 0:
            prev_aa = (prev.get("aa") or {}).get("recent") or []
    prev_block = "\n".join(f"- {t}" for t in prev_titles if t) or "(없음)"
    recent_block = json.dumps(prev_aa, ensure_ascii=False) if prev_aa else "(없음)"
    return prev_block, recent_block


def build_prompt(day: dt.date, index: list) -> str:
    prev_titles: list[str] = []
    prev_aa: list = []
    earlier = [e for e in index if isinstance(e, dict) and e.get("date", "") < day.isoformat()][:2]
    for i, entry in enumerate(earlier):
        prev = load_json(DATA / f"{entry.get('date')}.json", {})
        prev_titles += [n.get("t", "") for n in prev.get("news", [])]
        if i == 0:
            prev_aa = (prev.get("aa") or {}).get("recent") or []
    prev_block = "\n".join(f"- {t}" for t in prev_titles if t) or "(없음)"
    recent_block = json.dumps(prev_aa, ensure_ascii=False) if prev_aa else "(없음)"
    return f"""오늘은 {day.isoformat()} ({WEEKDAYS[day.weekday()]}) 입니다. 한국시간 기준입니다.

아래 분야를 하나씩 따로 웹 검색해서 최근 24~48시간(부족하면 7일 이내) 뉴스를 모으세요.
1. 설계·정비사업: 재건축 설계자 선정, 설계공모, 희림·해안·삼우·건원·에이앤유·나우동인·DA그룹·정림 등 건축사사무소 동향
2. 시공 수주: 정비사업 시공사 선정 총회와 결과, 건설사 수주
3. 공공 발주: LH 발주, 조달청 시설공사 주간 입찰 동향, 공공 설계공모
4. 경기 지표: 한국건설산업연구원 건설시장동향·CBSI, 건설수주·기성, 공사비지수
5. 업계·금융: 부동산 PF, 건설사 실적·인사, 건설 정책
6. 서울시 공공건축 설계공모: 프로젝트 서울(https://project.seoul.go.kr)의 공모 공고·접수마감·심사·당선 발표
7. 우리 회사 {COMPANY}: "AA아키그룹", "에이에이아키그룹"으로 검색하고 회사 뉴스룸 {COMPANY_NEWSROOM} 도 확인. 반도체 공장·데이터센터 등 하이테크 설계 시장 소식도 확인.

우리 회사 관련 기사는 news에 넣지 말고 aa.today에만 넣으세요.

어제 브리핑에 이미 실린 기사(새 진전이 없으면 다시 싣지 말 것):
{prev_block}

어제 기준 회사 최근 보도 목록(aa.recent에 이어서 쓰고, 새 보도가 있으면 맨 앞에 추가해 최대 4건 유지):
{recent_block}

{SCHEMA_HINT}"""


# ---------------------------------------------------------------- 모델 호출: Open WebUI
_MODEL = ""


def resolve_model(base: str, key: str, wanted: str) -> str:
    """모델 ID 또는 화면에 보이는 모델 이름을 받아 실제 모델 ID를 찾습니다."""
    try:
        listing = http("GET", f"{base}/api/models", key) or {}
    except RuntimeError as e:
        print(f"모델 목록을 읽지 못해 입력값을 그대로 씁니다: {e}")
        return wanted
    models = listing.get("data", listing) if isinstance(listing, dict) else listing
    models = [m for m in (models or []) if isinstance(m, dict)]
    norm = lambda v: re.sub(r"\s+", "", str(v or "")).lower()
    w = norm(wanted)
    for field in ("id", "name"):
        for m in models:
            if norm(m.get(field)) == w:
                print(f"사용 모델: {m.get('name')} (ID: {m.get('id')})")
                return m["id"]
    for m in models:
        if w and (w in norm(m.get("name")) or w in norm(m.get("id"))):
            print(f"사용 모델(부분 일치): {m.get('name')} (ID: {m.get('id')})")
            return m["id"]
    names = ", ".join(f"{m.get('name')} [{m.get('id')}]" for m in models[:40])
    raise RuntimeError(f"모델 '{wanted}'을(를) 찾지 못했습니다. 사용할 수 있는 모델: {names}")


def call_openwebui(prompt: str, day: dt.date, web: bool = True, label: str = "") -> str:
    """회사 Open WebUI에서 웹 검색을 켜고 답을 받아옵니다.

    Open WebUI는 웹 검색 같은 내장 도구를 '저장된 채팅 + 스트리밍 + session_id' 요청에서만
    실행합니다. 그래서 (1) 채팅을 만들고 (2) 백그라운드로 답을 생성시킨 뒤
    (3) 끝날 때까지 기다렸다가 (4) 채팅에서 답을 읽어 옵니다.
    만들어진 채팅은 Open WebUI 채팅 목록에 '데일리 브리핑 날짜'로 남습니다.
    """
    base = need("OPENWEBUI_URL").rstrip("/")
    key = need("OPENWEBUI_API_KEY")
    global _MODEL
    if not _MODEL:
        _MODEL = resolve_model(base, key, need("OPENWEBUI_MODEL"))
    model = _MODEL

    uid, aid = str(uuid.uuid4()), str(uuid.uuid4())
    ts = int(time.time())
    user_msg = {"id": uid, "parentId": None, "childrenIds": [aid], "role": "user",
                "content": prompt, "timestamp": ts, "models": [model]}
    asst_msg = {"id": aid, "parentId": uid, "childrenIds": [], "role": "assistant",
                "content": "", "model": model, "modelName": model, "timestamp": ts, "done": False}
    chat = {"title": f"데일리 브리핑 {day.isoformat()} {label}".strip(), "models": [model],
            "history": {"currentId": aid, "messages": {uid: user_msg, aid: asst_msg}},
            "messages": [user_msg, asst_msg], "tags": [], "timestamp": ts * 1000}

    created = http("POST", f"{base}/api/v1/chats/new", key, {"chat": chat})
    chat_id = (created or {}).get("id")
    if not chat_id:
        raise RuntimeError(f"Open WebUI 채팅을 만들지 못했습니다: {str(created)[:300]}")

    body = {
        "model": model,
        "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
        "stream": True,
        "chat_id": chat_id,
        "id": aid,
        "user_message": user_msg,
        "session_id": f"api-{uuid.uuid4()}",
        "features": {"web_search": web},
        "background_tasks": {"title_generation": False, "tags_generation": False, "follow_up_generation": False},
    }
    started = http("POST", f"{base}/api/chat/completions", key, body, timeout=180)
    print(f"[{label or '요청'}] Open WebUI 작업 시작:", json.dumps(started, ensure_ascii=False)[:120])

    deadline = time.time() + 20 * 60
    time.sleep(15)
    while time.time() < deadline:
        tasks = http("GET", f"{base}/api/tasks/chat/{chat_id}", key) or {}
        if not tasks.get("task_ids"):
            break
        time.sleep(15)
    else:
        raise RuntimeError("Open WebUI 답변이 20분 안에 끝나지 않았습니다.")

    full = http("GET", f"{base}/api/v1/chats/{chat_id}", key) or {}
    msg = (((full.get("chat") or {}).get("history") or {}).get("messages") or {}).get(aid) or {}
    if msg.get("usage"):
        print("토큰 사용량:", json.dumps(msg["usage"], ensure_ascii=False))
    content = msg.get("content") or ""
    if not os.environ.get("OPENWEBUI_KEEP_CHATS"):
        try:  # 매일 생기는 작업용 채팅은 지워서 채팅 목록을 깔끔하게 유지합니다.
            http("DELETE", f"{base}/api/v1/chats/{chat_id}", key)
        except RuntimeError as e:
            print(f"작업용 채팅을 지우지 못했습니다(무시): {e}")
    if not content.strip():
        err = msg.get("error") or msg.get("statusHistory") or "빈 답변"
        raise RuntimeError(f"Open WebUI 답변이 비어 있습니다: {str(err)[:500]}")
    return content


# ---------------------------------------------------------------- 모델 호출: OpenAI API
def call_openai(prompt: str, day: dt.date) -> str:
    key = need("OPENAI_API_KEY")
    body = {
        "model": os.environ.get("OPENAI_MODEL", "gpt-6-luna"),
        "instructions": SYSTEM,
        "input": prompt,
        "tools": [{"type": "web_search"}],
        "reasoning": {"effort": os.environ.get("OPENAI_EFFORT", "medium")},
    }
    try:
        data = http("POST", "https://api.openai.com/v1/responses", key, body, timeout=900)
    except RuntimeError as e:
        if "HTTP 400" in str(e) and "reasoning" in str(e):
            body.pop("reasoning")
            data = http("POST", "https://api.openai.com/v1/responses", key, body, timeout=900)
        else:
            raise
    texts = [c.get("text", "") for item in (data or {}).get("output", []) if item.get("type") == "message"
             for c in item.get("content", []) if c.get("type") == "output_text"]
    if (data or {}).get("usage"):
        print("토큰 사용량:", json.dumps(data["usage"], ensure_ascii=False))
    return "\n".join(texts)


# ---------------------------------------------------------------- 네이버 뉴스 검색
# NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 이 있으면 켜집니다. 없으면 회사 웹UI 검색만 씁니다.
NAVER_COMMON = ["건축", "건설"]          # 모든 분야에 공통으로 붙는 키워드 (관련도순)
NAVER_QUERIES = {
    "design": ["재건축 설계자 선정", "설계공모 당선", "건축사사무소"],
    "seoul": ["서울시 설계공모", "프로젝트 서울 설계공모"],
    "build": ["시공사 선정 총회", "건설 수주"],
    "public": ["조달청 시설공사 발주", "LH 발주 입찰"],
    "market": ["건설경기 실사지수", "건설수주 통계", "건설공사비지수"],
    "biz": ["건설사 PF", "건설사 실적", "건설 정책 규제"],
    "aa": ["AA아키그룹", "에이에이아키그룹"],
}


def naver_news(query: str, day: dt.date, display: int = 50, days: int = 3) -> list:
    """네이버 뉴스 검색 API(관련도순). 최근 days일 기사만 남깁니다."""
    cid, sec = os.environ.get("NAVER_CLIENT_ID", "").strip(), os.environ.get("NAVER_CLIENT_SECRET", "").strip()
    if not (cid and sec):
        return []
    from email.utils import parsedate_to_datetime
    qs = urllib.parse.urlencode({"query": query, "display": display, "start": 1, "sort": "sim"})
    # NAVER API HUB(네이버 클라우드) 키가 기본, 예전 개발자센터 키면 두 번째 주소로 시도합니다.
    tries = [("https://naverapihub.apigw.ntruss.com/search/v1/news?" + qs,
              {"X-NCP-APIGW-API-KEY-ID": cid, "X-NCP-APIGW-API-KEY": sec}),
             ("https://openapi.naver.com/v1/search/news.json?" + qs,
              {"X-Naver-Client-Id": cid, "X-Naver-Client-Secret": sec})]
    items, errs = None, []
    for url, hdr in tries:
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=hdr), timeout=30) as r:
                items = json.loads(r.read().decode("utf-8")).get("items") or []
            break
        except Exception as e:  # 네이버가 안 되면 조용히 건너뜁니다.
            errs.append(f"{url.split('/')[2]}: {e}")
    if items is None:
        print(f"[네이버] '{query}' 검색 실패: {' / '.join(errs)}")
        return []
    end = dt.datetime.combine(day, dt.time(23, 59), KST)
    out = []
    for it in items:
        try:
            when = parsedate_to_datetime(it.get("pubDate", "")).astimezone(KST)
        except (TypeError, ValueError):
            continue
        if not (end - dt.timedelta(days=days) <= when <= end):
            continue
        link = it.get("originallink") or it.get("link") or ""
        if not is_url(link):
            continue
        clean = lambda x: _strip(re.sub(r"</?b>", "", x or ""))
        out.append({"t": clean(it.get("title")), "d": clean(it.get("description")),
                    "u": link, "m": domain(link), "w": when.strftime("%m.%d")})
    return out


def naver_pool(day: dt.date) -> dict:
    """분야별 네이버 검색 결과. 공통 키워드(건축·건설) 결과는 모든 분야에 함께 줍니다."""
    if not (os.environ.get("NAVER_CLIENT_ID") and os.environ.get("NAVER_CLIENT_SECRET")):
        print("[네이버] 키가 없어 건너뜁니다.")
        return {}
    common, seen = [], set()
    for q in NAVER_COMMON:
        for a in naver_news(q, day, 100, 2):
            if a["u"] not in seen:
                seen.add(a["u"]); common.append(a)
    pool = {}
    for cat, qs in NAVER_QUERIES.items():
        got, cs = [], set()
        for q in [f"{x} 건축" if cat == "design" and "건축" not in x else x for x in qs]:
            for a in naver_news(q, day, 30, 7 if cat in ("aa", "market") else 3):
                if a["u"] not in cs:
                    cs.add(a["u"]); got.append(a)
        pool[cat] = got[:20]
    pool["_common"] = common[:40]
    print(f"[네이버] 공통 {len(common)}건, " + ", ".join(f"{k} {len(v)}건" for k, v in pool.items() if k != "_common"))
    return pool


def naver_block(pool: dict, cat: str) -> str:
    if not pool:
        return ""
    rows, seen = [], set()
    for a in (pool.get(cat) or []) + ([] if cat == "aa" else pool.get("_common") or []):
        if a["u"] in seen:
            continue
        seen.add(a["u"])
        rows.append(f"- {a['w']} | {a['t']} | {a['d'][:160]} | {a['m']} | {a['u']}")
    if not rows:
        return ""
    return ("\n네이버 뉴스 검색 결과(키워드 '건축'·'건설'과 분야 키워드, 관련도순, 최근 기사만). "
            "이 목록을 먼저 살펴 주제에 맞는 기사를 고르고, 부족하면 웹 검색으로 보충하세요. "
            "목록의 기사를 쓸 때는 끝에 있는 주소를 그대로 링크로 쓰고, 언론사 이름은 주소를 보고 적으세요. "
            "제목과 요약은 목록 문구를 베끼지 말고 직접 새로 쓰세요.\n" + "\n".join(rows[:45]) + "\n")


GROUPS = [
    ("design", "설계·정비사업: 재건축·재개발 설계자(설계사) 선정, 민간·공공 설계공모 결과, 주요 건축사사무소(희림·해안·삼우·건원·에이앤유·나우동인·DA그룹·정림 등) 동향"),
    ("seoul", "서울시 공공건축 설계공모: 프로젝트 서울(https://project.seoul.go.kr)에 올라온 설계공모 공고·접수마감·심사·당선작 발표와 이를 다룬 보도. 공모 상세 페이지 주소가 있으면 그 주소를 링크로 쓰세요"),
    ("build", "시공 수주: 재건축·재개발 시공사 선정 총회와 결과, 건설사 수주 소식"),
    ("public", "공공 발주: LH·조달청 시설공사 발주와 입찰(조달청 시설공사 주간 입찰 동향 포함), 공공기관 설계공모"),
    ("market", "경기 지표: 한국건설산업연구원 건설시장동향·건설경기실사지수(CBSI), 통계청 건설수주·기성, 건설공사비지수"),
    ("biz", "업계·금융: 부동산 PF, 건설사 실적·인사, 건설·부동산 정책과 규제"),
]

GROUP_FORMAT = """출력은 JSON 하나만 (다른 글자 없이):
{"news": [{"t": "제목(직접 새로 씀)", "p": "2~3문장 요약(직접 새로 씀)", "s": [["언론사", "MM.DD", "https://실제 기사 주소"]]}],
 "cal": [["날짜", "다가오는 총회·입찰마감·발표 일정"]]}
기사는 2~4건. 찾지 못하면 {"news": [], "cal": []}"""


def gather_openwebui(day: dt.date, index: list) -> dict:
    """분야마다 따로 요청해 검색 한도를 나눠 쓰고, 마지막에 핵심 3줄만 따로 정리합니다."""
    prev_block, recent_block = prev_context(day, index)
    head = f"오늘은 {day.isoformat()} ({WEEKDAYS[day.weekday()]}) 입니다. 한국시간 기준입니다.\n"
    news, cal, seen = [], [], set()
    pool = naver_pool(day)
    for cat, desc in GROUPS:
        prompt = (head + f"아래 주제만 웹 검색해서 최근 24~48시간(부족하면 7일 이내) 기사를 찾으세요.\n주제: {desc}\n"
                  f"우리 회사({COMPANY}) 관련 기사는 넣지 마세요.\n"
                  f"어제 브리핑에 이미 실린 기사(새 진전이 없으면 제외):\n{prev_block}\n{naver_block(pool, cat)}\n{GROUP_FORMAT}")
        try:
            raw = extract_json(call_openwebui(prompt, day, True, cat))
        except (RuntimeError, ValueError, json.JSONDecodeError) as e:
            print(f"[{cat}] 건너뜀: {e}")
            continue
        got = 0
        for n in raw.get("news") or raw.get("articles") or []:
            if not isinstance(n, dict):
                continue
            srcs = parse_sources(n)
            if not srcs or srcs[0][2] in seen:
                continue
            seen.add(srcs[0][2])
            n = dict(n)
            n["c"] = cat
            n["s"] = srcs
            news.append(n)
            got += 1
        cal += [c for c in (raw.get("cal") or []) if isinstance(c, (list, tuple)) and len(c) >= 2]
        print(f"[{cat}] 기사 {got}건")

    aa = {"today": [], "recent": [], "signal": ""}
    aa_prompt = (head + f"우리 회사 {COMPANY} 관련 최근 7일 보도를 웹 검색하세요. "
                 f'"AA아키그룹", "에이에이아키그룹"으로 검색하고 회사 뉴스룸 {COMPANY_NEWSROOM} 도 확인하세요. '
                 "반도체 공장·데이터센터 등 하이테크 설계 시장 소식도 확인하세요.\n"
                 f"어제 기준 회사 최근 보도 목록(새 보도가 있으면 맨 앞에 추가해 최대 4건 유지):\n{recent_block}\n"
                 f"{naver_block(pool, 'aa')}\n"
                 'JSON 하나만 출력: {"today": [{"d": "YYYY.MM.DD", "t": "제목", "p": "한 줄 요약", "u": "https://..."}], '
                 '"recent": [{"d": "YYYY.MM.DD", "t": "제목", "u": "https://..."}], '
                 '"signal": "회사 사업(반도체·데이터센터 등 하이테크, 주거, 업무·복합)과 연결되는 오늘의 시장 신호 1~2문장"}. '
                 "새 보도가 없으면 today는 []")
    try:
        raw = extract_json(call_openwebui(aa_prompt, day, True, "aa"))
        aa = {k: raw.get(k, aa[k]) for k in aa}
        if re.search(r"(검색|확인)[^.]{0,20}(못|제한|없)", str(aa.get("signal") or "")):
            aa["signal"] = ""  # 작업 과정 메모는 싣지 않습니다.
        print(f"[aa] 새 소식 {len(raw.get('today') or [])}건")
    except (RuntimeError, ValueError, json.JSONDecodeError) as e:
        print(f"[aa] 건너뜀: {e}")
        try:
            aa["recent"] = json.loads(recent_block) if recent_block != "(없음)" else []
        except json.JSONDecodeError:
            pass

    if not news:
        raise ValueError("모든 분야에서 기사를 찾지 못했습니다.")

    listing = "\n".join(f"- [{n['c']}] {s(n.get('t') or n.get('title'), 120)} / {s(n.get('p') or n.get('summary'), 300)} ({n['s'][0][0]})"
                         for n in news)
    summary_prompt = (head + "아래는 오늘 브리핑에 실을 기사 목록입니다. 이 목록에 있는 사실만 써서 핵심 정리를 하세요. "
                      "새로 검색하거나 목록에 없는 숫자를 만들지 마세요. 검색이 부족했다는 등 작업 과정 이야기는 쓰지 마세요.\n\n"
                      f"{listing}\n\n"
                      'JSON 하나만 출력: {"key": [{"b": "굵게 보일 한 줄 요지(마침표로 끝)", "t": "보충 한 문장"}] (정확히 3개), '
                      '"figure": {"label": "숫자 설명", "value": "24.6", "unit": "조원", "change": "변화", "note": "짧은 맥락"} (목록에 의미 있는 숫자가 없으면 생략), '
                      '"gauge": {"label": "지수 이름 (기준선 100)", "value": 74.9, "note": "해석"} (기준선 100 지수가 목록에 있을 때만), '
                      '"head": "그날 핵심 한 줄 (40자 안팎)"}')
    try:
        top = extract_json(call_openwebui(summary_prompt, day, False, "핵심 정리"))
    except (RuntimeError, ValueError, json.JSONDecodeError) as e:
        print(f"[핵심 정리] 실패, 기사 제목으로 대신합니다: {e}")
        top = {}
    return {"key": top.get("key") or [], "figure": top.get("figure"), "gauge": top.get("gauge"),
            "head": top.get("head") or "", "aa": aa, "news": news, "cal": cal}


def ask_model(prompt: str, day: dt.date) -> str:
    mock = os.environ.get("BRIEFING_MOCK_FILE")
    if mock:
        return Path(mock).read_text(encoding="utf-8")
    backend = os.environ.get("BRIEFING_BACKEND", "openwebui").strip().lower()
    if backend == "openai":
        return call_openai(prompt, day)
    return call_openwebui(prompt, day)


# ---------------------------------------------------------------- 응답 정리·검증
def extract_json(text: str) -> dict:
    # Open WebUI는 검색·도구 실행 기록을 <details> 블록으로 답 앞에 붙일 수 있어 먼저 지웁니다.
    text = re.sub(r"<details[\s\S]*?</details>", "", text).strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("응답에서 JSON을 찾지 못했습니다.")
        return json.loads(text[start : end + 1])


URL_RE = re.compile(r"https?://[^\s\"'<>\)\]]+")


def first_url(v) -> str:
    """문자열·목록·딕셔너리 어디에 있든 첫 번째 http(s) 주소를 찾아 돌려줍니다."""
    if isinstance(v, str):
        m = URL_RE.search(v)
        return m.group(0).rstrip(".,;") if m else ""
    if isinstance(v, dict):
        for k in ("u", "url", "link", "href"):
            u = first_url(v.get(k))
            if u:
                return u
        return ""
    if isinstance(v, (list, tuple)):
        for x in v:
            u = first_url(x)
            if u:
                return u
    return ""


def is_url(v) -> bool:
    return bool(first_url(v))


def s(v, limit=600) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()[:limit]


def domain(u: str) -> str:
    host = urllib.parse.urlparse(u).netloc
    return host[4:] if host.startswith("www.") else host


def norm_cat(c) -> str:
    """분야 값이 한글·다른 표현으로 와도 다섯 분야 중 하나로 맞춥니다."""
    c = s(c).lower()
    if c in CATS:
        return c
    rules = [("seoul", ("seoul", "서울시 설계공모", "프로젝트 서울", "project.seoul", "서울시 공공건축")),
             ("design", ("design", "설계", "정비", "재건축", "재개발", "건축사")),
             ("market", ("market", "경기", "지표", "통계", "cbsi", "기성")),
             ("public", ("public", "공공", "발주", "입찰", "lh", "조달")),
             ("build", ("build", "시공", "수주", "건설사"))]
    for cat, words in rules:
        if any(w in c for w in words):
            return cat
    return "biz"


def parse_sources(n: dict) -> list:
    raw = n.get("s") or n.get("sources") or n.get("source") or []
    if isinstance(raw, (str, dict)):
        raw = [raw]
    # ["언론사", "11.26", "https://..."] 처럼 한 겹으로 온 경우
    if isinstance(raw, list) and raw and all(isinstance(x, str) for x in raw) and first_url(raw[-1]) and not first_url(raw[0]):
        raw = [raw]
    out = []
    for x in raw if isinstance(raw, list) else []:
        u = first_url(x)
        if not u:
            continue
        if isinstance(x, (list, tuple)):
            name = x[0] if x and not first_url(x[0]) else domain(u)
            date = x[1] if len(x) >= 3 else ""
        elif isinstance(x, dict):
            name = x.get("name") or x.get("source") or x.get("media") or domain(u)
            date = x.get("date") or x.get("d") or ""
        else:
            name, date = domain(u), ""
        out.append([s(name, 60), s(date, 10), u])
    if not out:
        u = first_url({k: n.get(k) for k in ("u", "url", "link")})
        if u:
            out.append([s(n.get("media") or n.get("source_name") or domain(u), 60), s(n.get("date") or n.get("d"), 10), u])
    return out[:3]


def validate(raw: dict, day: dt.date) -> dict:
    """모델 응답을 사이트 형식에 맞게 정리하고, 쓸 수 없는 항목은 버립니다."""
    news, dropped = [], []
    items = raw.get("news") or raw.get("articles") or []
    for n in items if isinstance(items, list) else []:
        if not isinstance(n, dict):
            dropped.append("형식 아님")
            continue
        t = s(n.get("t") or n.get("title"), 120)
        p = s(n.get("p") or n.get("summary") or n.get("desc"), 600)
        srcs = parse_sources(n)
        if not t:
            dropped.append("제목 없음")
            continue
        if not srcs:
            dropped.append(f"링크 없음: {t[:30]}")
            continue
        news.append({"c": norm_cat(n.get("c") or n.get("category")), "t": t, "p": p or t, "s": srcs})
    if dropped:
        print(f"걸러낸 기사 {len(dropped)}건: " + " / ".join(dropped[:10]))
    if not news:
        raise ValueError(f"쓸 수 있는 기사가 없습니다. (받은 기사 {len(items) if isinstance(items, list) else 0}건)")

    key = [{"b": s(k.get("b") or k.get("title"), 80), "t": s(k.get("t") or k.get("text"), 200)}
           for k in (raw.get("key") or []) if isinstance(k, dict) and s(k.get("b") or k.get("title"))][:3]
    if not key:
        key = [{"b": n["t"] + ".", "t": ""} for n in news[:3]]

    out = {"date": day.isoformat(), "weekday": WEEKDAYS[day.weekday()], "key": key}

    f = raw.get("figure")
    if isinstance(f, dict) and s(f.get("value")):
        out["figure"] = {k: s(f.get(k), 120) for k in ("label", "value", "unit", "change", "note")}

    g = raw.get("gauge")
    if isinstance(g, dict):
        try:
            gv = float(g.get("value"))
            if 0 < gv <= 200:
                out["gauge"] = {"label": s(g.get("label"), 80), "value": round(gv, 1), "note": s(g.get("note"), 160)}
        except (TypeError, ValueError):
            pass

    a = raw.get("aa") if isinstance(raw.get("aa"), dict) else {}
    out["aa"] = {
        "today": [{"d": s(x.get("d") or x.get("date"), 12), "t": s(x.get("t") or x.get("title"), 140),
                   "p": s(x.get("p") or x.get("summary"), 300), "u": first_url(x)}
                  for x in (a.get("today") or []) if isinstance(x, dict) and first_url(x) and s(x.get("t") or x.get("title"))][:5],
        "recent": [{"d": s(x.get("d") or x.get("date"), 12), "t": s(x.get("t") or x.get("title"), 140), "u": first_url(x)}
                   for x in (a.get("recent") or []) if isinstance(x, dict) and first_url(x) and s(x.get("t") or x.get("title"))][:4],
        "signal": s(a.get("signal"), 300),
    }
    out["news"] = news[:12]
    out["cal"] = [[s(c[0], 20), s(c[1], 200)] for c in (raw.get("cal") or [])
                  if isinstance(c, (list, tuple)) and len(c) >= 2 and s(c[1])][:5]
    out["_head"] = s(raw.get("head"), 60) or key[0]["b"].rstrip(".")
    return out


# ---------------------------------------------------------------- 프로젝트 서울 목록
PS_BASE = "https://project.seoul.go.kr"


def _strip(html_text: str) -> str:
    import html as _html
    text = _html.unescape(_html.unescape(re.sub(r"<[^>]+>", " ", html_text)))
    return re.sub(r"\s+", " ", text).strip()


def _fetch_page(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (daily-briefing; +github actions)",
                                               "Accept-Language": "ko-KR,ko;q=0.9"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", "replace")


def parse_ps_notices(page: str) -> list:
    out = []
    for href, body in re.findall(r'<a class="ps-notice-row[^"]*"\s+href="([^"]+)"[^>]*>(.*?)</a>', page, re.S):
        dt = re.search(r'class="dt[^"]*"[^>]*>(.*?)</span>', body, re.S)
        src = re.search(r'class="src"[^>]*>(.*?)</span>', body, re.S)
        src_t = _strip(src.group(1)).strip("[]") if src else ""
        ttl = _strip(body)
        if dt:
            ttl = ttl.replace(_strip(dt.group(1)), "", 1).strip()
        if src:
            ttl = ttl.replace(_strip(src.group(1)), "", 1).strip()
        out.append({"d": _strip(dt.group(1)) if dt else "", "c": src_t, "t": ttl, "u": PS_BASE + href.replace("&amp;", "&")})
    return out


def parse_ps_archive(page: str) -> list:
    out = []
    for href, body in re.findall(r'<a class="ps-cptt-card"\s+href="(/view/viewDetailArchive\.do\?[^"]+)"[^>]*>(.*?)</a>', page, re.S):
        badges = [_strip(b) for b in re.findall(r'<span class="ps-arv-badge[^"]*"[^>]*>(.*?)</span>', body, re.S)]
        title = re.search(r"<h2[^>]*>(.*?)</h2>", body, re.S)
        meta = re.search(r'class="ps-arv-submeta"[^>]*>(.*?)</p>', body, re.S)
        rest = body
        for part in (title.group(0) if title else "", meta.group(0) if meta else ""):
            rest = rest.replace(part, " ")
        rest = re.sub(r'<span class="ps-arv-badge[^"]*"[^>]*>.*?</span>', " ", rest, flags=re.S)
        out.append({"stage": " · ".join(b for b in badges if b), "t": _strip(title.group(1)) if title else "",
                    "meta": _strip(meta.group(1)) if meta else "", "info": _strip(rest), "u": PS_BASE + href.replace("&amp;", "&")})
    return out


def update_project_seoul() -> None:
    """프로젝트 서울 공모알림·아카이브 목록을 data/project_seoul.json 에 저장합니다. 실패하면 이전 파일을 그대로 둡니다."""
    path = DATA / "project_seoul.json"
    old = load_json(path, {})
    try:
        notices = parse_ps_notices(_fetch_page(PS_BASE + "/view/viewListNotice.do?noticeType=CPTT"))
        archive = parse_ps_archive(_fetch_page(PS_BASE + "/view/viewListArchive.do"))
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        print(f"[프로젝트 서울] 목록을 가져오지 못해 이전 목록을 유지합니다: {e}")
        return
    if not notices and not archive:
        print("[프로젝트 서울] 목록이 비어 있어 이전 목록을 유지합니다(페이지 구조가 바뀌었을 수 있음).")
        return
    data = {"updated": dt.datetime.now(KST).strftime("%Y-%m-%d %H:%M"),
            "notices": notices[:30] or old.get("notices", []), "archive": archive[:30] or old.get("archive", [])}
    DATA.mkdir(exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"[프로젝트 서울] 공모알림 {len(data['notices'])}건, 아카이브 {len(data['archive'])}건 저장")


# ---------------------------------------------------------------- 실행
# ---------------------------------------------------------------- 사이트 안 열람 가능 여부
# 언론사 중에는 다른 사이트 안(iframe)에서 열리지 않게 막아 둔 곳이 있습니다.
# 매일 새로 나온 언론사 주소를 한 번씩 확인해 data/noframe.json 에 적어 두면,
# 화면에서 그 언론사 기사는 처음부터 새 탭으로 엽니다.
SITE_HOST = "none-hongcheol.github.io"


def _host(u: str) -> str:
    try:
        return urllib.parse.urlsplit(u).hostname or ""
    except ValueError:
        return ""


def _frame_blocked(url: str):
    """True: 막힘, False: 열림, None: 확인 못 함."""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130 Safari/537.36",
                                               "Accept-Language": "ko-KR,ko;q=0.9"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            h = r.headers
    except urllib.error.HTTPError as e:
        h = e.headers
        if e.code >= 400 and not (h.get("X-Frame-Options") or h.get("Content-Security-Policy")):
            return None
    except Exception:
        return None
    xfo = (h.get("X-Frame-Options") or "").strip().upper()
    if xfo and xfo != "ALLOWALL":
        return True
    for csp in h.get_all("Content-Security-Policy") or []:
        m = re.search(r"frame-ancestors([^;]*)", csp, re.I)
        if m:
            v = m.group(1)
            return not ("*" in v.split() or SITE_HOST in v)
    return False


def update_noframe(urls: list) -> None:
    path = DATA / "noframe.json"
    known = load_json(path, {})
    blocked, ok = set(known.get("blocked") or []), set(known.get("ok") or [])
    todo = {}
    for u in urls:
        h = _host(u)
        if h and h not in blocked and h not in ok and h not in todo:
            todo[h] = u
    if todo:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(8) as ex:
            for h, res in zip(todo, ex.map(_frame_blocked, todo.values())):
                if res is True:
                    blocked.add(h)
                elif res is False:
                    ok.add(h)
    DATA.mkdir(exist_ok=True)
    path.write_text(json.dumps({"blocked": sorted(blocked), "ok": sorted(ok)}, ensure_ascii=False, indent=1) + "\n",
                    encoding="utf-8")
    print(f"[열람 확인] 새로 본 언론사 {len(todo)}곳, 사이트 안에서 막힌 곳 총 {len(blocked)}곳")


def brief_urls(brief: dict) -> list:
    out = [x[2] for n in brief.get("news") or [] for x in n.get("s") or [] if len(x) > 2]
    a = brief.get("aa") or {}
    out += [x.get("u", "") for x in (a.get("today") or []) + (a.get("recent") or []) if isinstance(x, dict)]
    return [u for u in out if u]


def main() -> None:
    if os.environ.get("BRIEFING_ONLY") == "frames":
        index = load_json(DATA / "index.json", [])
        urls = []
        for e in (index if isinstance(index, list) else [])[:14]:
            urls += brief_urls(load_json(DATA / f"{e.get('date')}.json", {}))
        update_noframe(urls)
        return
    if os.environ.get("BRIEFING_ONLY") == "project_seoul":
        update_project_seoul()
        return
    update_project_seoul()
    day = today_kst()
    index = load_json(DATA / "index.json", [])
    if not isinstance(index, list):
        index = []

    backend = os.environ.get("BRIEFING_BACKEND", "openwebui").strip().lower()
    if backend == "openwebui" and not os.environ.get("BRIEFING_MOCK_FILE"):
        try:
            brief = validate(gather_openwebui(day, index), day)
        except (ValueError, RuntimeError) as e:
            sys.exit(f"브리핑 생성 실패: {e}\n오늘은 발행하지 않고 기존 사이트를 유지합니다.")
        publish(day, index, brief)
        return

    prompt = build_prompt(day, index)
    last_err = None
    for attempt in range(2):
        text = ""
        try:
            text = ask_model(prompt, day)
            brief = validate(extract_json(text), day)
            break
        except (ValueError, json.JSONDecodeError, RuntimeError) as e:
            last_err = e
            print(f"{attempt + 1}회차 실패: {e}")
            if text:
                body = re.sub(r"<details[\s\S]*?</details>", "", text).strip()
                print("---- 받은 답 앞부분(원인 확인용) ----\n" + body[:1500] + "\n----")
            prompt += ("\n\n주의: 직전 응답이 형식에 맞지 않았습니다. 위 JSON 형식만, 다른 글자 없이 출력하세요. "
                       "news는 6건 이상, 각 항목의 s는 [[\"언론사\", \"MM.DD\", \"https://...\"]] 형식으로 실제 기사 주소를 넣으세요.")
    else:
        sys.exit(f"브리핑 생성 실패: {last_err}\n오늘은 발행하지 않고 기존 사이트를 유지합니다.")

    publish(day, index, brief)


def publish(day: dt.date, index: list, brief: dict) -> None:
    head = brief.pop("_head")
    DATA.mkdir(exist_ok=True)
    try:
        update_noframe(brief_urls(brief))
    except Exception as e:  # 확인이 실패해도 발행은 계속합니다.
        print(f"[열람 확인] 건너뜀: {e}")
    (DATA / f"{day.isoformat()}.json").write_text(json.dumps(brief, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    entry = {"date": day.isoformat(), "weekday": brief["weekday"], "head": head,
             "count": len(brief["news"]), "aa": len(brief["aa"]["today"])}
    index = [e for e in index if isinstance(e, dict) and e.get("date") != entry["date"]]
    index.insert(0, entry)
    index.sort(key=lambda e: e.get("date", ""), reverse=True)
    (DATA / "index.json").write_text(
        "[\n" + ",\n".join(json.dumps(e, ensure_ascii=False) for e in index) + "\n]\n", encoding="utf-8")

    print(f"{day.isoformat()} 브리핑 발행: 기사 {entry['count']}건, AA 소식 {entry['aa']}건")
    print("핵심:", head)


if __name__ == "__main__":
    main()
