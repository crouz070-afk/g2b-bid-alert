# 나라장터 공고 알림 (GitHub Actions)

회계·감사·세무·원가·자문 키워드 및 회계법인·원가검토기관 면허제한 공고를 하루 2회
자동 스캔해, 신규 건이 있으면 카카오톡 "나에게 보내기"로 알린다.

PC 전원과 무관하게 GitHub 서버에서 실행된다.

| | |
|---|---|
| 실행 시각 | 매일 **08:00 / 18:00 KST** (GitHub cron 특성상 5~15분 지연될 수 있음) |
| 데이터 출처 | 조달청 나라장터 입찰공고정보서비스 (공공데이터포털) |
| 알림 채널 | 카카오톡 나에게 보내기 (REST API) |
| 상태 저장 | `state.json` — 매 실행 후 리포지토리에 커밋 |

## 파일

| 파일 | 역할 |
|---|---|
| `g2b_scan.py` | 스캔·매칭·이력 기록·요약 생성. 진입점 |
| `kakao_notify.py` | 카카오 REST API 발송 + 리프레시 토큰 자동 갱신 |
| `make_html.py` | `docs/index.html` 생성 (GitHub Pages 공개용) |
| `make_table.py` | 표 이미지 PNG 생성 (워크플로 아티팩트로 보관) |
| `config.json` | 키워드·제외어·면허·조회구간 설정. **API 키는 들어있지 않다** |
| `state.json` | 마지막 실행시각 + 이미 알린 공고번호(중복 발송 방지) |
| `history.csv` | 탐지 누적 이력 |

## 최초 설치

### 1. 리포지토리 생성

GitHub에서 새 리포지토리를 만든다 (이름 예: `g2b-bid-alert`).
**Private 권장** — Public이어야 하는 이유는 아래 4번뿐이다.

```bash
git remote add origin https://github.com/<사용자명>/g2b-bid-alert.git
git branch -M main
git push -u origin main
```

### 2. 카카오 앱 준비 (한 번만)

1. [카카오 개발자센터](https://developers.kakao.com) → 내 애플리케이션 → **애플리케이션 추가**
2. **앱 키** 메뉴에서 `REST API 키` 복사 → 나중에 `KAKAO_REST_KEY`로 등록
3. **카카오 로그인** 활성화 ON, Redirect URI에 `https://localhost:3000` 등록
4. **동의항목** → `카카오톡 메시지 전송(talk_message)` 선택 동의로 설정
5. 브라우저에서 아래 주소를 열어 로그인·동의하고, 리디렉션된 주소창의 `code=` 값을 복사한다.

```
https://kauth.kakao.com/oauth/authorize?client_id=<REST_API_키>&redirect_uri=https://localhost:3000&response_type=code&scope=talk_message
```

6. 그 code로 리프레시 토큰을 받는다 (code는 1회용, 몇 분 내 사용).

```bash
curl -X POST "https://kauth.kakao.com/oauth/token" -d "grant_type=authorization_code" -d "client_id=<REST_API_키>" -d "redirect_uri=https://localhost:3000" -d "code=<복사한_code>"
```

응답의 `refresh_token` 값을 `KAKAO_REFRESH_TOKEN`으로 등록한다.

### 3. 시크릿 등록

리포지토리 → Settings → Secrets and variables → Actions → New repository secret

| 이름 | 값 | 필수 |
|---|---|---|
| `G2B_SERVICE_KEY` | 공공데이터포털 서비스키(Decoding 값) | 필수 |
| `KAKAO_REST_KEY` | 카카오 REST API 키 | 필수 |
| `KAKAO_REFRESH_TOKEN` | 위에서 받은 리프레시 토큰 | 필수 |
| `GH_PAT` | Fine-grained PAT, 이 리포지토리에 `Secrets: Read and write` 권한 | 선택 |

`GH_PAT`를 넣으면 카카오가 리프레시 토큰을 재발급할 때(2개월마다) 시크릿이 자동으로
갱신된다. 넣지 않으면 2개월 뒤 발송이 끊기고, 워크플로 로그에 새 토큰이 남으므로
그때 수동으로 교체하면 된다.

### 4. (선택) 공고 목록 웹페이지

`docs/index.html`을 GitHub Pages로 띄우면 카톡 알림의 버튼이 표 형태 목록으로 연결된다.

- Settings → Pages → Source: `Deploy from a branch`, Branch: `main` / `/docs`
- 배포 주소를 `config.json`의 `pages_url`에 넣고 커밋

**Private 리포지토리의 Pages는 GitHub Pro(유료) 이상에서만 동작한다.**
`pages_url`이 비어 있으면 카톡 버튼은 첫 번째 공고의 나라장터 페이지로 바로 연결되므로,
Pages 없이도 알림 기능은 완전하게 동작한다.

### 5. 동작 확인

Actions 탭 → `g2b-bid-scan` → **Run workflow**로 수동 실행.

## 로컬 실행

```bash
export G2B_SERVICE_KEY="..."
python g2b_scan.py --hours 24 --dry    # 상태·발송 없이 테스트
python g2b_scan.py --hours 24          # 상태 갱신, 발송 없음
python g2b_scan.py --notify            # 정상 실행 + 카톡 발송
python kakao_notify.py "테스트"         # 카카오 연결만 확인
```

## 설정 변경

`config.json`을 고치고 커밋하면 다음 실행부터 반영된다.

- `keywords` / `exclude_patterns` — 공고명 매칭. 2글자 키워드는 공백을 허용하지 않아
  "제16회 계룡"이 "회계"로 오매칭되지 않는다.
- `license_keywords` — 참가자격 면허명 매칭. 공고명에 키워드가 없어도 잡힌다.
- `lookback_overlap_minutes` — 직전 실행시각에서 되짚는 여유분(누락 방지).
- `max_lookback_hours` — 오래 멈춰 있었을 때 한 번에 되짚는 최대 범위.

## 알아둘 것

- **60일 무활동 시 스케줄 정지** — GitHub는 활동이 없는 리포지토리의 예약 워크플로를
  자동으로 멈추고 메일로 알린다. 메일의 링크나 Actions 탭에서 한 번 활성화하면 재개된다.
- **중복 발송 방지는 `state.json`이 담당** — 임의로 지우면 과거 공고가 다시 알림으로 나간다.
- **0건이면 아무것도 보내지 않는다** — 조용한 날은 카톡이 오지 않는 것이 정상이다.
