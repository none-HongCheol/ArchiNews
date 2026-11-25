# 건설·건축 데일리 브리핑 — 설정 가이드

매일 오전 7시 30분 전후로 건설·건축 뉴스 브리핑을 자동 발행하는 사내용 사이트입니다.

- **사이트**: GitHub Pages (무료)
- **자동 실행**: GitHub Actions가 매일 07:10(한국시간)에 시작
- **뉴스 조사·요약**: OpenAI API, 기본 모델 `gpt-6-luna`
- **비용**: OpenAI API 사용료만 나갑니다. GitHub와 Claude 비용은 들지 않습니다.

처음 설정은 30분 정도 걸립니다. 아래 순서대로 따라 하세요.

---

## 0. 미리 알아둘 점: 사이트 공개 범위

GitHub 무료 플랜의 Pages 사이트는 **주소를 아는 사람은 누구나 볼 수 있습니다.**

- 검색엔진에는 잡히지 않도록 설정해 두었습니다(`noindex`). 그래도 주소가 밖으로 퍼지면 외부인도 볼 수 있습니다.
- 브리핑 내용은 공개된 기사 요약과 원문 링크이므로 큰 문제는 없습니다. 다만 **회사 내부 정보는 절대 넣지 마세요.**
- 사내 인원만 보게 하려면 회사가 GitHub Enterprise Cloud를 쓸 때 가능한 '비공개 Pages' 기능이 필요합니다. IT 담당자에게 문의하세요.

---

## 1. OpenAI API 키 만들기

1. https://platform.openai.com 에 로그인합니다. ChatGPT 계정과 같은 계정을 써도 되지만, **API 결제는 ChatGPT 구독과 별개**입니다.
2. 왼쪽 메뉴 **Billing**에서 결제 수단을 등록하고 소액(예: 5~10달러)을 충전합니다.
3. **Usage limits**에서 월 한도를 정해 두면(예: 10달러) 예상 밖 과금을 막을 수 있습니다.
4. **API keys → Create new secret key**를 눌러 이름을 `aa-briefing`으로 하고 키를 만듭니다.
5. 화면에 나온 키(`sk-`로 시작)를 복사해 둡니다. **창을 닫으면 다시 볼 수 없습니다.** 키는 메신저나 메일로 보내지 마세요.

## 2. GitHub 저장소 만들기

1. https://github.com 에 가입하거나 로그인합니다. 회사 계정이나 회사 Organization을 권장합니다.
2. 오른쪽 위 **+ → New repository**를 누릅니다.
   - Repository name: `aa-briefing` (원하는 이름 가능)
   - **Public** 선택 (무료 플랜에서 Pages를 쓰려면 필요)
   - 나머지는 그대로 두고 **Create repository**를 누릅니다.
3. 새 저장소 화면에서 **uploading an existing file** 링크를 누릅니다.
4. 받은 zip을 풀고 **폴더 안의 내용물 전체**를 끌어다 놓습니다. `index.html`, `README.md`, `data` 폴더, `scripts` 폴더가 들어가야 합니다.
   - 주의: `.github` 폴더와 `.nojekyll` 파일은 이름이 점(.)으로 시작해서, 컴퓨터 설정에 따라 숨김 파일로 안 보일 수 있습니다.
     - Mac: Finder에서 `Cmd + Shift + .`
     - Windows: 탐색기 **보기 → 숨긴 항목** 체크
   - 업로드 목록에 `.github/workflows/daily-briefing.yml`이 꼭 있어야 자동 실행이 됩니다.
5. 아래 **Commit changes**를 누릅니다.

> `.github` 폴더가 끌어다 놓기로 안 올라가면: 저장소에서 **Add file → Create new file**을 누르세요. 파일 이름 칸에 `.github/workflows/daily-briefing.yml`을 입력하고, zip 안의 같은 파일 내용을 붙여 넣은 뒤 Commit하면 됩니다.

## 3. API 키를 저장소에 등록하기

이 단계가 OpenAI에 "이 저장소에서만" 일할 수 있게 해 주는 부분입니다.

1. 저장소 위쪽 **Settings → Secrets and variables → Actions**로 갑니다.
2. **New repository secret**을 누릅니다.
   - Name: `OPENAI_API_KEY`
   - Secret: 1단계에서 복사한 키
3. **Add secret**을 누릅니다. 키는 암호화되어 저장되고, 등록한 사람도 다시 볼 수 없습니다.

선택 사항으로 같은 화면의 **Variables** 탭에서 아래 값을 바꿀 수 있습니다.

| 이름 | 기본값 | 설명 |
|---|---|---|
| `OPENAI_MODEL` | `gpt-6-luna` | 품질을 더 높이려면 `gpt-6-sol` 등 상위 모델로 변경 (비용 증가) |
| `OPENAI_EFFORT` | `medium` | `low`는 더 싸고 빠름, `high`는 더 꼼꼼함 |

## 4. 자동 실행 권한 켜기

1. **Settings → Actions → General**로 갑니다.
2. 맨 아래 **Workflow permissions**에서 **Read and write permissions**를 선택하고 **Save**를 누릅니다.
   (매일 새 브리핑 파일을 저장소에 올리기 위해 필요합니다.)

## 5. 사이트 열기 (GitHub Pages)

1. **Settings → Pages**로 갑니다.
2. **Source**: `Deploy from a branch`를 고릅니다.
3. **Branch**: `main` / `/ (root)`를 고르고 **Save**를 누릅니다.
4. 1~2분 뒤 같은 화면 위쪽에 사이트 주소가 나타납니다.
   예: `https://회사계정.github.io/aa-briefing/`
5. 주소로 들어가 11월 25일 자 브리핑이 보이면 성공입니다.

## 6. 첫 자동 발행 테스트

내일 아침까지 기다리지 말고 지금 한 번 돌려 보세요.

1. 저장소 위쪽 **Actions** 탭으로 갑니다. 처음이면 "I understand… enable" 버튼이 나올 수 있는데, 눌러서 켭니다.
2. 왼쪽 **데일리 브리핑 발행**을 누르고, 오른쪽 **Run workflow → Run workflow**를 누릅니다.
3. 5~15분 뒤 초록색 체크가 뜨면 완료입니다. 사이트를 새로고침하면 오늘 날짜 브리핑이 올라와 있습니다.
4. 빨간 X가 뜨면 실행 기록을 눌러 오류 문구를 확인하세요. 아래 '문제 해결'을 참고하세요.

이후로는 매일 07:10에 자동으로 시작합니다. GitHub 서버 사정으로 시작이 몇 분~수십 분 늦어질 때가 있습니다.

## 7. 사내 공유

5단계에서 얻은 사이트 주소 하나만 공유하면 됩니다. 주소는 바뀌지 않고, 매일 내용만 새로 바뀝니다. 지난 브리핑은 사이트의 **지난 브리핑** 탭에 날짜별로 쌓입니다.

---

## 문제 해결

| 증상 | 확인할 것 |
|---|---|
| `OPENAI_API_KEY 가 설정되지 않았습니다` | 3단계 Secret 이름이 정확히 `OPENAI_API_KEY`인지 |
| `OpenAI API 오류 401` | 키가 틀렸거나 삭제됨 → 새 키 발급 후 Secret 수정 |
| `OpenAI API 오류 429` / `insufficient_quota` | OpenAI 크레딧 부족 → Billing에서 충전 |
| `OpenAI API 오류 400` + model | 모델 이름 확인 → Variables의 `OPENAI_MODEL` 수정 |
| `브리핑 생성 실패` | 그날은 발행을 건너뛰고 어제 브리핑이 그대로 유지됩니다. 다시 실행하려면 6단계 |
| 실행은 성공했는데 사이트가 안 바뀜 | 4단계 쓰기 권한, 5단계 Pages 설정 확인. 반영까지 1~2분 걸립니다 |
| 자동 실행이 멈춤 | Actions 탭에서 워크플로가 꺼져(Disabled) 있지 않은지 확인 |

**지난 날짜 다시 만들기**: Run workflow를 누를 때 date 칸에 `2026-11-27`처럼 날짜를 넣으면 그 날짜 파일을 다시 만듭니다. 다만 그 날짜 기준이 아니라 실행 시점의 뉴스로 조사합니다.

## 파일 구성

```
index.html                       사이트 화면 (수정할 일 거의 없음)
data/index.json                  날짜 목록 (자동 갱신)
data/YYYY-MM-DD.json             날짜별 브리핑 (자동 생성)
scripts/make_briefing.py         뉴스 조사·요약 스크립트
.github/workflows/daily-briefing.yml   매일 자동 실행 설정
```

조사 분야, 검색 키워드, 경쟁사 목록을 바꾸려면 `scripts/make_briefing.py` 안의 `build_prompt` 부분 글을 고치면 됩니다.

## 저작권 원칙

브리핑은 기사 제목과 요약을 새로 쓰고 원문 링크를 다는 방식입니다. 기사 본문을 복사해 붙이도록 바꾸지 마세요. 언론사 기사는 대부분 무단 전재와 재배포를 금지하고 있습니다.
