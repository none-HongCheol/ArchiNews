#!/usr/bin/env python3
"""건설·건축 데일리 브리핑 생성 스크립트.

매일 자동으로 실행되어
  1) 회사 Open WebUI(또는 OpenAI API)에 웹 검색을 시켜 최근 뉴스를 모으고
  2) 정해진 JSON 형식으로 브리핑을 받아 검증한 뒤
  3) data/YYYY-MM-DD.json 을 쓰고 data/index.json 맨 앞에 그날 항목을 추가합니다.

외부 패키지 없이 파이썬 표준 라이브러리만 씁니다.

환경 변수
  BRIEFING_BACKEND    openwebui(기본) 또는 openai
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
CATS = {"design", "build", "public", "market", "biz"}

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
   {"c": "design|build|public|market|biz 중 하나", "t": "제목", "p": "2~3문장 요약",
    "s": [["언론사", "MM.DD", "https://..."]]}
 ],   // 6~12건
 "head": "그날 핵심 한 줄 (40자 안팎)",
 "cal": [ ["날짜", "다가오는 총회·입찰마감·발표 일정"] ]   // 0~5건
}
분야(c) 뜻
- design: 재건축·재개발 설계자 선정, 설계공모, 건축사사무소 동향
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
6. 우리 회사 {COMPANY}: "AA아키그룹", "에이에이아키그룹"으로 검색하고 회사 뉴스룸 {COMPANY_NEWSROOM} 도 확인. 반도체 공장·데이터센터 등 하이테크 설계 시장 소식도 확인.

우리 회사 관련 기사는 news에 넣지 말고 aa.today에만 넣으세요.

어제 브리핑에 이미 실린 기사(새 진전이 없으면 다시 싣지 말 것):
{prev_block}

어제 기준 회사 최근 보도 목록(aa.recent에 이어서 쓰고, 새 보도가 있으면 맨 앞에 추가해 최대 4건 유지):
{recent_block}

{SCHEMA_HINT}"""


# ---------------------------------------------------------------- 모델 호출: Open WebUI
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


def call_openwebui(prompt: str, day: dt.date) -> str:
    """회사 Open WebUI에서 웹 검색을 켜고 답을 받아옵니다.

    Open WebUI는 웹 검색 같은 내장 도구를 '저장된 채팅 + 스트리밍 + session_id' 요청에서만
    실행합니다. 그래서 (1) 채팅을 만들고 (2) 백그라운드로 답을 생성시킨 뒤
    (3) 끝날 때까지 기다렸다가 (4) 채팅에서 답을 읽어 옵니다.
    만들어진 채팅은 Open WebUI 채팅 목록에 '데일리 브리핑 날짜'로 남습니다.
    """
    base = need("OPENWEBUI_URL").rstrip("/")
    key = need("OPENWEBUI_API_KEY")
    model = resolve_model(base, key, need("OPENWEBUI_MODEL"))

    uid, aid = str(uuid.uuid4()), str(uuid.uuid4())
    ts = int(time.time())
    user_msg = {"id": uid, "parentId": None, "childrenIds": [aid], "role": "user",
                "content": prompt, "timestamp": ts, "models": [model]}
    asst_msg = {"id": aid, "parentId": uid, "childrenIds": [], "role": "assistant",
                "content": "", "model": model, "modelName": model, "timestamp": ts, "done": False}
    chat = {"title": f"데일리 브리핑 {day.isoformat()}", "models": [model],
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
        "features": {"web_search": True},
        "background_tasks": {"title_generation": False, "tags_generation": False, "follow_up_generation": False},
    }
    started = http("POST", f"{base}/api/chat/completions", key, body, timeout=180)
    print("Open WebUI 작업 시작:", json.dumps(started, ensure_ascii=False)[:200])

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
    rules = [("design", ("design", "설계", "정비", "재건축", "재개발", "건축사")),
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


# ---------------------------------------------------------------- 실행
def main() -> None:
    day = today_kst()
    index = load_json(DATA / "index.json", [])
    if not isinstance(index, list):
        index = []

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

    head = brief.pop("_head")
    DATA.mkdir(exist_ok=True)
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
import urllib.request
import uuid
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
KST = ZoneInfo("Asia/Seoul")
WEEKDAYS = "월화수목금토일"
CATS = {"design", "build", "public", "market", "biz"}

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
   {"c": "design|build|public|market|biz 중 하나", "t": "제목", "p": "2~3문장 요약",
    "s": [["언론사", "MM.DD", "https://..."]]}
 ],   // 6~12건
 "head": "그날 핵심 한 줄 (40자 안팎)",
 "cal": [ ["날짜", "다가오는 총회·입찰마감·발표 일정"] ]   // 0~5건
}
분야(c) 뜻
- design: 재건축·재개발 설계자 선정, 설계공모, 건축사사무소 동향
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
6. 우리 회사 {COMPANY}: "AA아키그룹", "에이에이아키그룹"으로 검색하고 회사 뉴스룸 {COMPANY_NEWSROOM} 도 확인. 반도체 공장·데이터센터 등 하이테크 설계 시장 소식도 확인.

우리 회사 관련 기사는 news에 넣지 말고 aa.today에만 넣으세요.

어제 브리핑에 이미 실린 기사(새 진전이 없으면 다시 싣지 말 것):
{prev_block}

어제 기준 회사 최근 보도 목록(aa.recent에 이어서 쓰고, 새 보도가 있으면 맨 앞에 추가해 최대 4건 유지):
{recent_block}

{SCHEMA_HINT}"""


# ---------------------------------------------------------------- 모델 호출: Open WebUI
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


def call_openwebui(prompt: str, day: dt.date) -> str:
    """회사 Open WebUI에서 웹 검색을 켜고 답을 받아옵니다.

    Open WebUI는 웹 검색 같은 내장 도구를 '저장된 채팅 + 스트리밍 + session_id' 요청에서만
    실행합니다. 그래서 (1) 채팅을 만들고 (2) 백그라운드로 답을 생성시킨 뒤
    (3) 끝날 때까지 기다렸다가 (4) 채팅에서 답을 읽어 옵니다.
    만들어진 채팅은 Open WebUI 채팅 목록에 '데일리 브리핑 날짜'로 남습니다.
    """
    base = need("OPENWEBUI_URL").rstrip("/")
    key = need("OPENWEBUI_API_KEY")
    model = resolve_model(base, key, need("OPENWEBUI_MODEL"))

    uid, aid = str(uuid.uuid4()), str(uuid.uuid4())
    ts = int(time.time())
    user_msg = {"id": uid, "parentId": None, "childrenIds": [aid], "role": "user",
                "content": prompt, "timestamp": ts, "models": [model]}
    asst_msg = {"id": aid, "parentId": uid, "childrenIds": [], "role": "assistant",
                "content": "", "model": model, "modelName": model, "timestamp": ts, "done": False}
    chat = {"title": f"데일리 브리핑 {day.isoformat()}", "models": [model],
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
        "features": {"web_search": True},
        "background_tasks": {"title_generation": False, "tags_generation": False, "follow_up_generation": False},
    }
    started = http("POST", f"{base}/api/chat/completions", key, body, timeout=180)
    print("Open WebUI 작업 시작:", json.dumps(started, ensure_ascii=False)[:200])

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


def is_url(v) -> bool:
    return isinstance(v, str) and re.match(r"^https?://\S+$", v) is not None


def s(v, limit=600) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()[:limit]


def validate(raw: dict, day: dt.date) -> dict:
    """모델 응답을 사이트 형식에 맞게 정리하고, 쓸 수 없는 항목은 버립니다."""
    news = []
    for n in raw.get("news") or []:
        if not isinstance(n, dict) or n.get("c") not in CATS:
            continue
        srcs = [[s(x[0], 60), s(x[1], 10), x[2]] for x in (n.get("s") or [])
                if isinstance(x, (list, tuple)) and len(x) >= 3 and is_url(x[2])]
        if not srcs or not s(n.get("t")) or not s(n.get("p")):
            continue
        news.append({"c": n["c"], "t": s(n["t"], 120), "p": s(n["p"], 600), "s": srcs[:3]})
    if len(news) < 3:
        raise ValueError(f"쓸 수 있는 기사가 {len(news)}건뿐입니다.")

    key = [{"b": s(k.get("b"), 80), "t": s(k.get("t"), 200)}
           for k in (raw.get("key") or []) if isinstance(k, dict) and s(k.get("b"))][:3]
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
        "today": [{"d": s(x.get("d"), 12), "t": s(x.get("t"), 140), "p": s(x.get("p"), 300), "u": x["u"]}
                  for x in (a.get("today") or []) if isinstance(x, dict) and is_url(x.get("u")) and s(x.get("t"))][:5],
        "recent": [{"d": s(x.get("d"), 12), "t": s(x.get("t"), 140), "u": x["u"]}
                   for x in (a.get("recent") or []) if isinstance(x, dict) and is_url(x.get("u")) and s(x.get("t"))][:4],
        "signal": s(a.get("signal"), 300),
    }
    out["news"] = news[:12]
    out["cal"] = [[s(c[0], 20), s(c[1], 200)] for c in (raw.get("cal") or [])
                  if isinstance(c, (list, tuple)) and len(c) >= 2 and s(c[1])][:5]
    out["_head"] = s(raw.get("head"), 60) or key[0]["b"].rstrip(".")
    return out


# ---------------------------------------------------------------- 실행
def main() -> None:
    day = today_kst()
    index = load_json(DATA / "index.json", [])
    if not isinstance(index, list):
        index = []

    prompt = build_prompt(day, index)
    last_err = None
    for attempt in range(2):
        try:
            text = ask_model(prompt, day)
            brief = validate(extract_json(text), day)
            break
        except (ValueError, json.JSONDecodeError, RuntimeError) as e:
            last_err = e
            print(f"{attempt + 1}회차 실패: {e}")
            prompt += "\n\n주의: 직전 응답이 형식에 맞지 않았습니다. 위 JSON 형식만, 다른 글자 없이 출력하세요."
    else:
        sys.exit(f"브리핑 생성 실패: {last_err}\n오늘은 발행하지 않고 기존 사이트를 유지합니다.")

    head = brief.pop("_head")
    DATA.mkdir(exist_ok=True)
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
