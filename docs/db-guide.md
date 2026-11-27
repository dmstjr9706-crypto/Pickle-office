# 실시간 공용 DB 가이드 (Realtime Database)

네 곳 — **초큐티**(메인 기기) · **하람 비서**(협업 기기) · **키링**(보조 자동화 앱) · **브이**(신규 협업 AI) — 이
**같은 현황판을 각자 직접** 갱신하기 위한 실시간 DB입니다.
GitHub 연결이 없는 기기도 여기로 쓰면 라이브 페이지에 수 초 안에 반영됩니다.

---

## 1. 한눈에

| 항목 | 값 |
|---|---|
| 서비스 | Firebase Realtime Database (Google, **Spark 무료**) |
| 프로젝트 | `pickle-office-rtdb` (계정 `dmstjr9706@gmail.com`) |
| DB 주소 | `https://pickle-office-rtdb-default-rtdb.asia-southeast1.firebasedatabase.app` |
| 위치 | 싱가포르(asia-southeast1) |
| 저장 내용 | `data/status.enc.json`과 **같은 암호문 봉투** 하나 + 접속 표시 + 기록 로그 |
| 읽기 | 누구나 (암호문이라 비밀번호 없이는 못 읽음) |
| 쓰기 | 등록된 **기록자 계정**의 로그인 토큰만 |

DB에 오가는 것은 전부 암호문이거나, 암호문이 아니어도 공개해도 되는 값(접속 시각·기록자 이름)입니다.
**평문 현황은 DB에도 저장소에도 남지 않습니다.**

## 2. 구조

```
office/
  status/                     ← 페이지가 읽는 유일한 현황. 암호문 봉투(JSON 한 덩어리)
    v, kdf, cipher, iterations, salt, iv, ciphertext, plaintext_bytes, encrypted_at
  presence/
    chuchu | haram | keyring | vee  ← { "at": 1795..., "by": "chuchu" }  (마지막 접속 시각, 평문)
  log/
    <자동 키>                 ← { "at": "...", "by": "키링", "note": "..." }  (누가 언제 무엇을)
```

- `status`의 평문(복호화 결과)은 `data/status.json`과 **완전히 같은 형식**입니다(`schema` 1).
- 암호화 규격: PBKDF2-HMAC-SHA256 60만 회 → AES-256-GCM, salt·iv 매번 새로. salt는 재사용해서
  브라우저의 "이 기기에서 기억하기" 열쇠가 계속 살아 있습니다.
- `presence`는 페이지의 캐릭터 카드에 "지금 연결 / N분 전 연결"로 표시됩니다.

## 3. 쓰기 규칙 (보안)

DB 규칙은 다음 한 줄로 요약됩니다.

```
office/status   .read = 누구나        .write = 기록자 uid 만
office/presence .read = 누구나        .write = 기록자 uid 만
office/log      .read = 기록자만       .write = 기록자 uid 만
```

- `status`는 암호문이라 공개돼도 안전하고, `presence`는 자리 이름과 시각만 있어 공개해도 된다.
- `log`(기록 메모)는 공개하지 않는다. 기록자로 로그인해야 볼 수 있다.

- 익명·비로그인 쓰기는 **거부**됩니다(401 Permission denied). 공개 저장소에 DB 주소가 보여도
  남이 현황을 지우거나 바꿀 수 없습니다.
- 기록자 계정은 하나이고, 네 곳이 같은 계정을 씁니다. 누가 썼는지는 `by`(초큐티/하람 비서/키링/브이)와
  `office/log`로 남습니다.
- **기록자 자격증명과 현황판 비밀번호는 저장소·페이지 코드에 절대 넣지 않습니다.** 로컬 파일
  (`.office-secret`, `.office-db.json`)이나 환경변수로만 씁니다. 둘 다 `.gitignore`에 있습니다.

## 4. 네 곳이 상태를 바꾸는 방법

준비물 두 개를 그 기기의 클론 폴더에 둡니다(클론 대화·메일 같은 **비공개 경로**로 전달).

```
.office-secret     현황판 비밀번호 (한 줄)
.office-db.json    {
                     "url": "https://pickle-office-rtdb-default-rtdb.asia-southeast1.firebasedatabase.app",
                     "apiKey": "…",
                     "email": "…",
                     "password": "…"
                   }
```

환경변수로 줘도 됩니다: `OFFICE_DB_URL` `OFFICE_DB_API_KEY` `OFFICE_DB_EMAIL` `OFFICE_DB_PASSWORD`,
아니면 한 줄로 `OFFICE_DB_WRITER="url|apiKey|email|password"`.

### 가장 흔한 쓰기 — 내 자리 한 줄

```bash
python3 scripts/office_db.py seat haram --now "18:05 공개 확인 대기 — 고정댓글 준비" --state "가동 중"
python3 scripts/office_db.py seat keyring --now "내일 07:30 수집 대기" --state "대기" --next "07:30 리서치 메일"
python3 scripts/office_db.py seat vee --now "가능 업무 확인 중" --state "대기"
```

- `seat` 값: `chuchu` · `haram` · `keyring` · `vee`
- 옵션: `--now`(지금 하는 일) `--state`('가동 중'/'대기') `--next`(다음 예정)
  `--duties "a;b;c"`(상시 담당 전체 교체) `--note "메모"`
- 자동으로 `updated_at`·`updated_by`를 채우고, 접속 표시와 기록 로그를 남깁니다.

### 나머지 명령

```bash
python3 scripts/office_db.py verify     # 연결·계정·암호 확인 (처음 한 번)
python3 scripts/office_db.py get        # 지금 DB 현황 요약
python3 scripts/office_db.py pull       # DB → 로컬 data/status.json (전체 편집용)
python3 scripts/office_db.py push -m "손으로 고친 status.json 올리기"   # 로컬 → DB
python3 scripts/office_db.py presence chuchu                            # 접속 표시만
python3 scripts/office_db.py timeline 18:00 --done true                 # 타임라인 체크
```

`pull` 로 받아 `data/status.json`을 고친 뒤 `push` 하면 유튜브·블로그·공모전 칸까지 전부 바꿀 수 있습니다.
`push` 는 보내기 전에 `scripts/validate_status.py`(형식 + 개인정보 패턴)를 자동으로 돌립니다.

### 동시에 쓸 때

`seat` 는 "지금 DB 것을 받아 → 내 자리만 고쳐 → 바로 올리기"를 한 번에 합니다.
네 곳이 **서로 다른 자리**를 고치면 충돌하지 않습니다. 같은 순간에 두 곳이 쓰면 나중 것이 이기므로,
같은 자리를 동시에 고치는 일은 피하세요(초큐티가 총괄).

### Python 이 없는 기기

HTTP 만으로도 됩니다. 다만 보내는 본문이 암호문이어야 하므로 암호화를 먼저 해야 합니다
(`scripts/office_db.py`의 `encrypt()` 규격). 키링처럼 파이썬을 못 돌리는 앱은 지금처럼
**초큐티에게 한 줄을 보내면 초큐티가 `seat` 로 대신 반영**합니다.

## 5. 페이지가 읽는 방식

1. 페이지를 열면 **DB에서 암호문 봉투를 먼저** 받습니다. (실패하면 `data/status.enc.json` 으로 자동 대체 — 화면 우측 상단 배지가 `파일 모드`로 바뀝니다)
2. 비밀번호를 넣으면 브라우저에서 복호화해 그립니다. (기존 잠금 방식 그대로)
3. 열린 뒤에는 DB의 실시간 스트림(SSE)을 붙여 두고, `office/status`가 바뀌면 **자동으로 다시 풀어** 화면을 갱신합니다.
4. 접속 표시는 60초마다 다시 읽습니다.

## 6. 점검

```bash
python3 scripts/office_db.py verify
curl -s "https://pickle-office-rtdb-default-rtdb.asia-southeast1.firebasedatabase.app/office/status.json" | head -c 200
```

- `Permission denied` → 기록자 계정/토큰 문제. `.office-db.json` 확인 후 `.office-db-token.json` 삭제하고 다시.
- `log` 를 읽을 때도 `Permission denied` 가 나오는 것은 정상이다(공개 아님).
- 기록자 비밀번호를 바꾸려면 Firebase 콘솔 Authentication 에서 사용자를 새로 만들고, 규칙의 `auth.uid === '…'`
  값을 새 uid 로 바꾼 뒤 네 곳에 새 자격증명을 나눠 준다.
- `DB 암호문을 이 비밀번호로 열 수 없습니다` → `.office-secret` 의 비밀번호가 DB와 다름.
- 콘솔: https://console.firebase.google.com/project/pickle-office-rtdb/database/pickle-office-rtdb-default-rtdb/data
