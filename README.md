# 건설·건축 데일리 브리핑 — 설정 가이드 (회사 Open WebUI 버전)

매일 오전 7시 30분 전후로 건설·건축 뉴스 브리핑을 자동 발행하는 사내용 사이트입니다.

- **사이트**: GitHub Pages (무료)
- **자동 실행**: GitHub Actions가 매일 07:10(한국시간)에 시작
- **뉴스 조사·요약**: 회사 Open WebUI(https://ai.aaarchigroup-ai.com)의 모델과 웹 검색
- **비용**: 회사 Open WebUI에 연결된 모델 사용료만 나갑니다. GitHub와 Claude 비용은 들지 않습니다.

```
GitHub Actions (매일 07:10)
   └─ scripts/make_briefing.py
        ├─ 회사 Open WebUI에 "오늘 뉴스 조사해서 JSON으로 정리" 요청 (웹 검색 켬)
        ├─ 답을 검사해서 data/날짜.json 저장
        └─ 저장소에 올림 → GitHub Pages 사이트가 자동 갱신
```

실행할 때마다 Open WebUI 채팅 목록에 **"데일리 브리핑 2026-11-26"** 같은 채팅이 하나씩 남습니다. Open WebUI 안에서도 날짜별 기록을 볼 수 있습니다.

처음 설정은 40분 정도 걸립니다. **1~2단계는 Open WebUI 관리자 권한이 필요**하니, 관리자가 아니면 IT 담당자와 함께 하세요.

---

## 0. 미리 알아둘 점

**사이트 공개 범위**
GitHub 무료 플랜의 Pages 사이트는 주소를 아는 사람은 누구나 볼 수 있습니다. 검색엔진에는 안 잡히게 설정해 두었지만, 회사 내부 정보는 브리핑에 넣지 마세요. 사내 인원만 보게 하려면 GitHub Enterprise Cloud의 비공개 Pages가 필요합니다.

**회사 서버 접속 가능 여부**
GitHub 서버(해외)가 `https://ai.aaarchigroup-ai.com`에 접속할 수 있어야 합니다. 회사 방화벽이나 IP 제한으로 사내망에서만 열리는 서버라면 IT 담당자에게 둘 중 하나를 요청하세요.
- GitHub Actions의 접속 허용
- 회사 서버에 'self-hosted runner'를 설치해서 사내에서 실행 (이 경우 workflow 파일의 `runs-on: ubuntu-latest`를 `runs-on: self-hosted`로 바꿈)

## 1. Open WebUI 관리자 설정 확인 (관리자)

1. **관리자 패널 → 설정 → 일반**에서 **API 키 사용(Enable API Keys)**을 켭니다.
2. 관리자가 아닌 계정으로 돌릴 경우: **관리자 패널 → 사용자 → 그룹(또는 기본 권한)**에서 그 계정에 **API Keys** 권한과 **웹 검색** 권한을 줍니다.
3. **관리자 패널 → 설정 → 웹 검색**이 켜져 있고 검색 엔진(예: Google PSE, Brave, SearXNG, Tavily 등)이 설정돼 있는지 확인합니다.
4. 쓸 모델(예: GPT-6 Luna)의 고급 설정에서 **함수 호출(Function Calling)**이 `Native`(기본값)인지 확인합니다.

**간단한 확인 방법**: 브라우저에서 Open WebUI 채팅을 열고, 웹 검색을 켠 상태로 "오늘 건설 뉴스 3개 찾아줘"라고 물어보세요. 출처 링크가 달린 답이 나오면 준비 완료입니다. 브라우저에서 웹 검색이 안 되면 API로도 안 됩니다.

## 2. 브리핑 전용 API 키 만들기

1. 가능하면 브리핑 전용 계정(예: `briefing-bot@…`)을 하나 만들어 로그인합니다. 개인 계정을 쓰면 매일 생기는 브리핑 채팅이 개인 채팅 목록에 쌓입니다.
2. 오른쪽 위 프로필 → **설정 → 계정 → API 키**에서 **API 키 생성**을 누릅니다.
3. 나온 키(`sk-`로 시작)를 복사해 둡니다. 메신저나 메일로 보내지 마세요.

## 3. 모델 ID 확인

1. **관리자 패널 → 설정 → 모델**(또는 워크스페이스 → 모델)에서 쓸 모델을 엽니다.
2. 모델 이름 아래의 **ID**를 그대로 적어 둡니다. 예: `gpt-6-luna`, `openai/gpt-6-luna` 등. 화면에 보이는 이름과 다를 수 있으니 꼭 ID를 확인하세요.

## 4. GitHub 저장소 만들기

1. https://github.com 에 가입하거나 로그인합니다. 회사 계정이나 회사 Organization을 권장합니다.
2. 오른쪽 위 **+ → New repository**를 누릅니다.
   - Repository name: `aa-briefing` (원하는 이름 가능)
   - **Public** 선택 (무료 플랜에서 Pages를 쓰려면 필요)
   - 나머지는 그대로 두고 **Create repository**를 누릅니다.
3. **uploading an existing file** 링크를 누릅니다.
4. 받은 zip을 풀고 **폴더 안의 내용물 전체**를 끌어다 놓습니다. `index.html`, `README.md`, `data` 폴더, `scripts` 폴더가 들어가야 합니다.
   - 주의: `.github` 폴더와 `.nojekyll` 파일은 이름이 점(.)으로 시작해서 숨김 파일로 안 보일 수 있습니다.
     - Mac: Finder에서 `Cmd + Shift + .`
     - Windows: 탐색기 **보기 → 숨긴 항목** 체크
   - 업로드 목록에 `.github/workflows/daily-briefing.yml`이 꼭 있어야 자동 실행이 됩니다.
5. **Commit changes**를 누릅니다.

> `.github` 폴더가 끌어다 놓기로 안 올라가면: 저장소에서 **Add file → Create new file**을 누르세요. 파일 이름 칸에 `.github/workflows/daily-briefing.yml`을 입력하고, zip 안의 같은 파일 내용을 붙여 넣은 뒤 Commit하면 됩니다.

## 5. 키와 모델 ID를 저장소에 등록하기

저장소 **Settings → Secrets and variables → Actions**로 갑니다.

**Secrets 탭 → New repository secret**

| Name | 값 |
|---|---|
| `OPENWEBUI_API_KEY` | 2단계에서 만든 키 |

**Variables 탭 → New repository variable**

| Name | 값 | 필수 |
|---|---|---|
| `OPENWEBUI_MODEL` | 3단계에서 확인한 모델 ID | 필수 |
| `OPENWEBUI_URL` | 기본값 `https://ai.aaarchigroup-ai.com` (주소가 다를 때만) | 선택 |

Secret은 암호화되어 저장되고, 등록한 사람도 다시 볼 수 없습니다.

## 6. 자동 실행 권한 켜기

1. **Settings → Actions → General**로 갑니다.
2. 맨 아래 **Workflow permissions**에서 **Read and write permissions**를 선택하고 **Save**를 누릅니다.

## 7. 사이트 열기 (GitHub Pages)

1. **Settings → Pages**로 갑니다.
2. **Source**: `Deploy from a branch`
3. **Branch**: `main` / `/ (root)` → **Save**
4. 1~2분 뒤 사이트 주소가 나타납니다. 예: `https://회사계정.github.io/aa-briefing/`
5. 주소로 들어가 11월 25일 자 브리핑이 보이면 성공입니다.

## 8. 첫 자동 발행 테스트

1. 저장소 **Actions** 탭으로 갑니다. 처음이면 활성화 버튼을 눌러 켭니다.
2. 왼쪽 **데일리 브리핑 발행** → 오른쪽 **Run workflow → Run workflow**를 누릅니다.
3. 5~20분 뒤 초록색 체크가 뜨면 완료입니다. 사이트를 새로고침하면 오늘 날짜 브리핑이 올라와 있고, Open WebUI 채팅 목록에도 "데일리 브리핑 날짜" 채팅이 생깁니다.
4. 빨간 X가 뜨면 실행 기록을 눌러 오류 문구를 확인하세요. 아래 '문제 해결'을 참고하세요.

이후로는 매일 07:10에 자동으로 시작합니다. GitHub 서버 사정으로 몇 분~수십 분 늦어질 때가 있습니다.

## 9. 사내 공유

7단계의 사이트 주소 하나만 공유하면 됩니다. 주소는 바뀌지 않고 매일 내용만 바뀝니다. 지난 브리핑은 사이트의 **지난 브리핑** 탭에 날짜별로 쌓입니다.

---

## 문제 해결

| 증상 | 확인할 것 |
|---|---|
| `OPENWEBUI_API_KEY 가 설정되지 않았습니다` | 5단계 Secret 이름이 정확한지 |
| `OPENWEBUI_MODEL 가 설정되지 않았습니다` | 5단계 Variables에 모델 ID를 넣었는지 |
| `서버에 연결하지 못했습니다` | GitHub에서 회사 서버로 접속이 막힘 → 0단계 '회사 서버 접속 가능 여부' |
| `HTTP 401` / `HTTP 403` | 키가 틀렸거나, 관리자 설정에서 API 키 사용이 꺼져 있음 → 1~2단계 |
| `HTTP 404` / `HTTP 400` + model | 모델 ID가 틀림 → 3단계에서 ID 다시 확인 |
| `답변이 비어 있습니다` / `쓸 수 있는 기사가 0건` | 웹 검색이 실제로 안 돌았을 가능성 → 1단계의 '간단한 확인 방법'으로 웹 검색이 되는지 확인 |
| `20분 안에 끝나지 않았습니다` | 모델이나 검색이 느림. Open WebUI 채팅 목록에서 해당 채팅이 어떻게 끝났는지 확인 |
| `브리핑 생성 실패` | 그날은 발행을 건너뛰고 어제 브리핑이 유지됩니다. 다시 하려면 8단계 |
| 실행은 성공했는데 사이트가 안 바뀜 | 6단계 쓰기 권한, 7단계 Pages 설정 확인. 반영까지 1~2분 걸립니다 |

**OpenAI API로 바로 돌리기(예비 방법)**: 회사 서버에 문제가 있을 때는 Variables에 `BRIEFING_BACKEND` = `openai`, Secrets에 `OPENAI_API_KEY`를 넣으면 OpenAI API(GPT-6 Luna)로 직접 실행됩니다.

**지난 날짜 다시 만들기**: Run workflow를 누를 때 date 칸에 `2026-11-27`처럼 날짜를 넣으면 그 날짜 파일을 다시 만듭니다. 다만 실행 시점의 뉴스로 조사합니다.

## 파일 구성

```
index.html                             사이트 화면 (수정할 일 거의 없음)
data/index.json                        날짜 목록 (자동 갱신)
data/YYYY-MM-DD.json                   날짜별 브리핑 (자동 생성)
scripts/make_briefing.py               뉴스 조사·요약 스크립트
.github/workflows/daily-briefing.yml   매일 자동 실행 설정
```

조사 분야, 검색 키워드, 경쟁사 목록을 바꾸려면 `scripts/make_briefing.py` 안의 `build_prompt` 부분 글을 고치면 됩니다.

## 저작권 원칙

브리핑은 기사 제목과 요약을 새로 쓰고 원문 링크를 다는 방식입니다. 기사 본문을 복사해 붙이도록 바꾸지 마세요. 언론사 기사는 대부분 무단 전재와 재배포를 금지하고 있습니다.
