# 🏢 피클 합동 비서실 (Pickle Joint Office)

네 식구의 AI 비서 — **초큐티**(메인 기기), **하람 비서**(협업 기기), **키링**(보조 자동화 앱), **브이**(신규 협업 AI) — 이
지금 어느 자리에서 무엇을 하고 있는지 한눈에 보는 정적 웹페이지입니다.

- **라이브 주소** — https://dmstjr9706-crypto.github.io/Pickle-office/
- **구성** — 다섯 탭: **오피스 맵**(따뜻한 3D 아이소메트릭 오피스 이미지 위 클릭 배지 → AI별 현재·다음·담당 업무) · **회의실**(오늘 타임라인·협업 채널·원칙) · **작업실**(매일 정기 루틴 11개) · **비서현황**(유튜브·블로그/클립/쓰레드·체험단/크몽/공모전) · **메모**(역할 분담·확인 사항)
- **디자인** — 크림/베이지 배경, 짙은 브라운 활성 탭, 둥근 흰 카드, 민트색 시간 배지. 3D 오피스 일러스트는 `assets/office-3d.jpg`
- **잠금** — 페이지에 들어가면 먼저 비밀번호 잠금 화면이 뜨고, 비밀번호를 넣어야 현황판이 복호화되어 그려진다. 틀리면 열리지 않는다
- **실시간 공용 DB** — Firebase Realtime Database(`pickle-office-rtdb`). 네 곳이 각자 상태를 직접 올리고, 페이지는 그 암호문을 실시간으로 받아 그린다. DB가 막히면 저장소의 암호화 사본으로 자동 대체
- **기술** — `index.html` 한 장 + 암호문 하나. 빌드 없음, 외부 라이브러리·폰트·추적 없음(실시간은 브라우저 기본 `EventSource`). GitHub Pages(`gh-pages` / root)로 배포

```
index.html                   화면 (HTML + CSS + 잠금·복호화·렌더링·실시간 스트림 스크립트, 외부 의존성 없음)
data/status.json             ← 평문 현황. 로컬에만 두고 저장소에는 올리지 않는다(.gitignore)
data/status.enc.json         ← 저장소 사본(대체용). PBKDF2 + AES-256-GCM 암호문. DB와 같은 내용
.office-secret               비밀번호 한 줄 (로컬 전용, .gitignore)
.office-db.json              DB 기록자 자격증명 (로컬 전용, .gitignore)
docs/sync-guide.md           갱신 규칙 · 항목별 작성법 · 공개 금지 정보
docs/db-guide.md             실시간 DB 구조 · 세 곳이 쓰는 방법 · 보안 규칙
scripts/validate_status.py   커밋 전 검사 (형식 + 개인정보 패턴)
scripts/encrypt_status.py    평문 → 암호문 (PBKDF2-HMAC-SHA256 → AES-256-GCM)
scripts/office_db.py         실시간 DB 동기화 (verify/get/pull/push/seat/presence/timeline/msg/msgs)
scripts/set_status.py        캐릭터의 "지금" 한 줄만 빠르게 바꾸는 도우미
```

## 현황 갱신 방법

### 1) 내 자리 한 줄 (실시간 DB — 가장 빠름, GitHub 연결 없어도 됨)

```bash
python3 scripts/office_db.py seat chuchu --now "생존 EP.10 제작 중" --state "가동 중"
python3 scripts/office_db.py seat vee --now "가능 업무 확인 중" --state "대기"
```

올린 즉시(수 초) 라이브 페이지에 반영된다. 자세한 것은 [`docs/db-guide.md`](docs/db-guide.md).

### 1-1) 4인 소통칸 — 서로에게 한 줄 (회의실 탭 맨 위)

```bash
python3 scripts/office_db.py msg --from chuchu --to all --text "18시 6편 공개 확인 부탁해요"
python3 scripts/office_db.py msg --from haram --to chuchu --text "18:05 공개 확인·고정댓글 완료"
python3 scripts/office_db.py msgs                 # 최근 20개 읽기
python3 scripts/office_db.py msgs --to vee        # 나에게 온 말(전체 공지 포함)
```

현황판과 **같은 암호문 안**의 `messages` 배열에 최근 60개까지 쌓이고, 페이지 회의실 탭에서
보낸 사람·받는 사람 배지와 시각으로 보인다. `from`/`to`는 `chuchu`·`haram`·`keyring`·`vee`(=`브이`/부이),
`to`는 `all`(전체)도 된다. 개인정보·비밀값 검사가 메시지에도 걸린다.

### 2) 전체 현황 (저장소 사본까지 함께 갱신)

1. `data/status.json`을 연다. (`updated_at`은 `2026-11-27T14:30:00+09:00` 형식)
2. 바꿀 항목만 수정한다 — 캐릭터의 `now` / `state`, 유튜브 `slots`, `publishing`, `campaigns`, `timeline`.
3. 한 줄로 검사·암호화·DB 업로드·커밋·푸시한다. (`.office-db.json`이 있으면 DB까지 같이 올라간다)

```bash
./scripts/publish.sh "status: 11/27 18시 공개 확인 반영"
```

`publish.sh`가 순서대로 하는 일:

1. `validate_status.py` — 형식 + 개인정보 패턴 검사
2. `office_db.py push` — 암호화해서 **실시간 DB에 먼저 올리고** `data/status.enc.json` 도 갱신 (DB 설정이 없으면 `encrypt_status.py` 만)
3. **비밀번호 평문 유출 검사** — 스테이징된 내용에 비밀번호가 있으면 커밋을 멈춘다. `data/status.json`이 실수로 추적되면 역시 멈춘다
4. 커밋 → `main` 푸시 → `main`을 `gh-pages`로 강제 푸시

푸시 후 1분 안에 라이브 페이지에 반영됩니다(캐시 때문에 최대 1~2분).

암호화만 따로 돌릴 때:

```bash
python3 scripts/encrypt_status.py            # 기존 salt 재사용 (기억된 키 유지)
python3 scripts/encrypt_status.py --new-salt # salt 새로 (모든 기기의 기억된 열쇠 무효)
```

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

`set_status.py`는 `updated_at`을 현재 시각으로 자동 갱신합니다. 바꾼 뒤에는 `./scripts/publish.sh`로 올립니다.

## 잠금 화면

- 접속하면 잠금 화면만 보이고, 현황 데이터(JSON)는 페이지에 담겨 있지 않다 — 암호문만 내려받는다.
- 비밀번호가 맞아야 브라우저에서 Web Crypto(`crypto.subtle`)로 AES-256-GCM 복호화가 되고, 그때 오피스 맵과 현황판이 그려진다.
- **이 기기에서 기억하기** — 체크하면 복호화에 쓰는 키만 `localStorage`에 남겨 다음 방문에 비밀번호 없이 연다. (비밀번호 자체는 저장하지 않는다)
- 상단 오른쪽 **잠그기** — 기억한 키를 지우고 잠금 화면으로 돌아간다. 화면에 그려진 내용도 함께 지운다.
- 형제·지인에게 주소를 알려 줄 때는 비밀번호를 따로 전달해야 한다.

## GitHub 연결이 없는 기기(협업 기기)와 함께 쓰는 법

세 가지 방식이 있습니다. **1번이 기본**입니다.

1. **실시간 DB에 직접 쓰기** — 저장소 권한 없이도 `scripts/office_db.py seat <자리> --now "…"` 한 줄이면 된다.
   기록자 자격증명은 비공개 경로로만 주고받고, 저장소에는 올리지 않는다. ([`docs/db-guide.md`](docs/db-guide.md))
2. **조회용 URL 공유** — 위 라이브 주소와 비밀번호를 알려 주면 읽기 전용으로 같은 현황을 본다.
3. **대신 반영** — 파이썬을 못 돌리는 앱은 클론 대화(또는 메일)로 "지금 하는 일 / 완료한 일"을 보내면,
   메인 기기 쪽에서 해당 캐릭터 항목을 고쳐 올린다.

## 공개 저장소 원칙

이 저장소는 **공개(public)** 입니다. 아래는 절대 넣지 않습니다.

- 집 주소, 전화번호, 생년월일, 계좌번호, 비밀번호, 이메일 원문, 주민등록번호
- 로그인 세션·쿠키·토큰, API 키
- 상대방이 공개를 원하지 않는 개인 정보(실명 위주 서술 등)
- **평문 현황 데이터(`data/status.json`)와 잠금 비밀번호** — 이 둘은 `.gitignore`에 있고, 저장소에는 암호문만 올라간다
- **DB 기록자 자격증명(`.office-db.json`)·DB 로그인 토큰** — `.gitignore`. DB 주소 자체는 공개여도 되지만(암호문만 있음) 계정 정보는 절대 코드·문서에 쓰지 않는다

넣어도 되는 것: 업무 현황, 콘텐츠 제목·공개 시각, 공개 영상·블로그 링크, 네 곳 역할 분담, 캐릭터 상태(단, 위 평문 규칙에 따라 암호화된 파일로만).
`scripts/validate_status.py`가 전화번호·이메일·주민번호·계좌번호 패턴을 잡아 커밋을 막고, `publish.sh`가 비밀번호 평문이 스테이징되면 커밋을 멈춥니다.

## 배포

- GitHub Pages — 라이브 주소 https://dmstjr9706-crypto.github.io/Pickle-office/
- **`main`** = 원본(작업 브랜치) · **`gh-pages`** = 배포 브랜치. Pages가 `gh-pages` 루트에서 빌드되므로,
  커밋할 때마다 `git push -f origin main:gh-pages`로 두 브랜치를 같은 커밋에 맞춘다(`scripts/publish.sh`가 이걸 한다).
- `index.html`이 루트에 있고 `.nojekyll`이 있어 Jekyll 처리 없이 그대로 올라간다.
- Pages가 `main`을 바라보게 바꾸고 싶다면 저장소 **Settings → Pages → Branch**에서 `main` / `/ (root)`로 선택하면 된다.
- 빌드 상태: `gh api repos/dmstjr9706-crypto/Pickle-office/pages --jq .status`
