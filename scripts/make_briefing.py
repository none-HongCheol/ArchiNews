#!/usr/bin/env python3
"""건설·건축 데일리 브리핑 생성 스크립트.

매일 GitHub Actions에서 실행되어
  1) OpenAI API(기본 모델: gpt-6-luna)에 웹 검색을 시켜 최근 뉴스를 모으고
  2) 정해진 JSON 형식으로 브리핑을 받아 검증한 뒤
  3) data/YYYY-MM-DD.json 을 쓰고 data/index.json 맨 앞에 그날 항목을 추가합니다.

외부 패키지 없이 파이썬 표준 라이브러리만 씁니다.

환경 변수
  OPENAI_API_KEY      (필수) OpenAI API 키
  OPENAI_MODEL        (선택) 기본값 gpt-6-luna
  OPENAI_EFFORT       (선택) 추론 강도 low / medium / high. 기본값 medium
  BRIEFING_DATE       (선택) YYYY-MM-DD. 비우면 오늘(한국시간)
  BRIEFING_MOCK_FILE  (테스트용) API 대신 이 파일 내용을 응답으로 사용
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
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
KST = ZoneInfo("Asia/Seoul")
WEEKDAYS = "월화수목금토일"
CATS = {"design", "build", "public", "market", "biz"}
API_URL = "https://api.openai.com/v1/responses"

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
- 출력은 JSON 하나만 씁니다. 설명, 마크다운, 코드블록 표시는 쓰지 않습니다."""

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


def call_openai(prompt: str) -> str:
    mock = os.environ.get("BRIEFING_MOCK_FILE")
    if mock:
        return Path(mock).read_text(encoding="utf-8")

    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        sys.exit("OPENAI_API_KEY 가 설정되지 않았습니다. GitHub 저장소 Settings > Secrets 에 등록하세요.")

    body = {
        "model": os.environ.get("OPENAI_MODEL", "gpt-6-luna"),
        "instructions": SYSTEM,
        "input": prompt,
        "tools": [{"type": "web_search"}],
        "reasoning": {"effort": os.environ.get("OPENAI_EFFORT", "medium")},
    }

    def post(payload: dict) -> dict:
        req = urllib.request.Request(
            API_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=900) as r:
            return json.loads(r.read().decode("utf-8"))

    for attempt in range(3):
        try:
            data = post(body)
            break
        except urllib.error.HTTPError as e:
            msg = e.read().decode("utf-8", "replace")
            if e.code == 400 and "reasoning" in msg and "reasoning" in body:
                body.pop("reasoning")  # 추론 강도 옵션을 지원하지 않는 모델이면 빼고 다시 시도
                continue
            if e.code in (429, 500, 502, 503, 504) and attempt < 2:
                time.sleep(30 * (attempt + 1))
                continue
            sys.exit(f"OpenAI API 오류 {e.code}: {msg[:800]}")
        except urllib.error.URLError as e:
            if attempt < 2:
                time.sleep(30)
                continue
            sys.exit(f"OpenAI API 연결 실패: {e}")
    else:
        sys.exit("OpenAI API 호출에 실패했습니다.")

    texts = []
    for item in data.get("output", []):
        if item.get("type") == "message":
            for c in item.get("content", []):
                if c.get("type") == "output_text":
                    texts.append(c.get("text", ""))
    if not texts and isinstance(data.get("output_text"), str):
        texts.append(data["output_text"])
    usage = data.get("usage")
    if usage:
        print("토큰 사용량:", json.dumps(usage, ensure_ascii=False))
    return "\n".join(texts)


def extract_json(text: str) -> dict:
    text = text.strip()
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


def main() -> None:
    day = today_kst()
    index = load_json(DATA / "index.json", [])
    if not isinstance(index, list):
        index = []

    prompt = build_prompt(day, index)
    last_err = None
    for attempt in range(2):
        text = call_openai(prompt)
        try:
            brief = validate(extract_json(text), day)
            break
        except (ValueError, json.JSONDecodeError) as e:
            last_err = e
            print(f"응답 검증 실패({attempt + 1}회차): {e}")
            prompt += "\n\n주의: 직전 응답이 형식에 맞지 않았습니다. 위 JSON 형식만, 다른 글자 없이 출력하세요."
    else:
        sys.exit(f"브리핑 생성 실패: {last_err}. 오늘은 발행하지 않고 기존 사이트를 유지합니다.")

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
