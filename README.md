# 🏢 피클 합동 비서실 (Pickle Joint Office)

세 곳의 AI 비서 — **초큐티**(메인 기기), **하람 비서**(협업 기기), **키링**(보조 자동화 앱) — 이
지금 어느 자리에서 무엇을 하고 있는지 한눈에 보는 정적 웹페이지입니다.

- **라이브 주소** — https://dmstjr9706-crypto.github.io/Pickle-office/
- **구성** — 상단은 3개 방으로 된 오피스 맵(SVG 캐릭터가 각자 자리에서 움직임), 하단은 유튜브 예약 · 블로그/클립/쓰레드 · 체험단/크몽/공모전 · 오늘의 타임라인 현황판
- **기술** — `index.html` 한 장 + `data/status.json` 하나. 빌드 없음, 외부 라이브러리·폰트·추적 없음. GitHub Pages(`main` / root)로 배포

```
index.html            화면 (HTML + CSS + 렌더링 스크립트, 외부 의존성 없음)
data/status.json      ← 현황 데이터. 이 파일만 고치면 화면이 바뀐다
docs/sync-guide.md    갱신 규칙 · 항목별 작성법 · 공개 금지 정보
scripts/validate_status.py   커밋 전 검사 (형식 + 개인정보 패턴)
scripts/set_status.py        캐릭터의 "지금" 한 줄만 빠르게 바꾸는 도우미
```

## 현황 갱신 방법

1. `data/status.json`을 연다. (`updated_at`은 `2026-11-27T14:30:00+09:00` 형식)
2. 바꿀 항목만 수정한다 — 캐릭터의 `now` / `state`, 유튜브 `slots`, `publishing`, `campaigns`, `timeline`.
3. 검사하고 올린다.

```bash
python3 scripts/validate_status.py          # 형식 + 개인정보 패턴 검사
git add -A && git commit -m "status: 11/27 18시 공개 확인 반영"
git push
git push -f origin main:gh-pages            # 배포 브랜치도 같이 밀기
```

한 줄로 끝내려면 `./scripts/publish.sh "status: 11/27 18시 공개 확인 반영"` — 검사·커밋·main 푸시·gh-pages 푸시를 순서대로 합니다.

푸시 후 1분 안에 라이브 페이지에 반영됩니다(캐시 때문에 최대 1~2분).

### 한 줄만 바꿀 때

```bash
# 초큐티가 지금 하는 일과 상태를 교체
python3 scripts/set_status.py now chuchu "내일 6편 예약 마감 — 생존 EP.10 제작 중"
python3 scripts/set_status.py state chuchu "가동 중"

# 타임라인 항목 체크
python3 scripts/set_status.py done "18:00" true

# 유튜브 슬롯 상태 바꾸기 (예약 완료 → 공개 완료)
python3 scripts/set_status.py slot 2026-11-27 kvCvSltdsEU "공개 완료"
```

`set_status.py`는 `updated_at`을 현재 시각으로 자동 갱신합니다.

## GitHub 연결이 없는 기기(협업 기기)와 함께 쓰는 법

협업 기기는 저장소를 직접 고칠 수 없으므로 두 가지 방식으로 맞춥니다.

1. **조회용 URL 공유** — 위 라이브 주소만 알려 주면 읽기 전용으로 같은 현황을 본다.
2. **대신 반영** — 협업 기기가 클론 대화(또는 메일)로 "지금 하는 일 / 완료한 일"을 보내면,
   메인 기기 쪽에서 `data/status.json`의 해당 캐릭터 항목을 고쳐 푸시한다. 이때도 위 검사 스크립트를 먼저 돌린다.

## 공개 저장소 원칙

이 저장소는 **공개(public)** 입니다. 아래는 절대 넣지 않습니다.

- 집 주소, 전화번호, 생년월일, 계좌번호, 비밀번호, 이메일 원문, 주민등록번호
- 로그인 세션·쿠키·토큰, API 키
- 상대방이 공개를 원하지 않는 개인 정보(실명 위주 서술 등)

넣어도 되는 것: 업무 현황, 콘텐츠 제목·공개 시각, 공개 영상·블로그 링크, 3곳 역할 분담, 캐릭터 상태.
`scripts/validate_status.py`가 전화번호·이메일·주민번호·계좌번호 패턴을 잡아 커밋을 막아 줍니다.

## 배포

- GitHub Pages — 라이브 주소 https://dmstjr9706-crypto.github.io/Pickle-office/
- **`main`** = 원본(작업 브랜치) · **`gh-pages`** = 배포 브랜치. Pages가 `gh-pages` 루트에서 빌드되므로,
  커밋할 때마다 `git push -f origin main:gh-pages`로 두 브랜치를 같은 커밋에 맞춘다(`scripts/publish.sh`가 이걸 한다).
- `index.html`이 루트에 있고 `.nojekyll`이 있어 Jekyll 처리 없이 그대로 올라간다.
- Pages가 `main`을 바라보게 바꾸고 싶다면 저장소 **Settings → Pages → Branch**에서 `main` / `/ (root)`로 선택하면 된다.
- 빌드 상태: `gh api repos/dmstjr9706-crypto/Pickle-office/pages --jq .status`
