#!/usr/bin/env bash
# 현황을 암호화해서 올리고 배포하는 한 줄짜리 스크립트.
#   ./scripts/publish.sh "status: 11/27 18시 6편 공개 확인"
#
# 동작: 평문 검사 → 암호화(status.enc.json) → 비밀번호 유출 검사 → 커밋
#       → main 푸시 → gh-pages(배포 브랜치)를 main과 같은 내용으로 밀기
#
# 비밀번호는 환경변수 PICKLE_OFFICE_SECRET 또는 로컬 파일 .office-secret(한 줄)에서 읽는다.
# 두 파일 모두 .gitignore 에 있어 저장소에는 올라가지 않는다.
set -euo pipefail

cd "$(dirname "$0")/.."

MSG="${1:-status: 현황 갱신}"

# 1) 평문 데이터 검사 (형식 + 개인정보 패턴)
python3 scripts/validate_status.py

# 2) 평문 → 암호문 (data/status.json → data/status.enc.json) → 실시간 DB
#    DB 기록자 설정(.office-db.json 또는 OFFICE_DB_WRITER)이 있으면 DB까지 같이 올린다.
if [ -f .office-db.json ] || [ -n "${OFFICE_DB_WRITER:-}" ] || [ -n "${OFFICE_DB_API_KEY:-}" ]; then
  python3 scripts/office_db.py push -m "$MSG" || {
    echo "✗ DB 업로드에 실패했습니다. (저장소 반영은 보류) 먼저 'python3 scripts/office_db.py verify' 로 연결을 확인하세요."
    exit 1
  }
else
  python3 scripts/encrypt_status.py --quiet
  echo "→ DB 기록자 설정이 없어 저장소(암호문)만 갱신합니다."
fi

# 3) 비밀번호 평문이 스테이징된 내용에 섞였는지 검사 — 값은 절대 출력하지 않는다
SECRET="${PICKLE_OFFICE_SECRET:-}"
if [ -z "$SECRET" ] && [ -f .office-secret ]; then
  SECRET="$(tr -d '\r\n' < .office-secret)"
fi

git add -A

if [ -n "$SECRET" ] && git grep -q --cached -F -- "$SECRET"; then
  echo "✗ 스테이징된 파일에 비밀번호 평문이 들어 있습니다. 커밋을 멈춥니다."
  echo "  해당 파일에서 비밀번호를 지운 뒤 다시 실행하세요 (값은 표시하지 않습니다)."
  git reset -q
  exit 1
fi

if git ls-files --error-unmatch data/status.json >/dev/null 2>&1; then
  echo "✗ data/status.json 이 아직 저장소에 추적되고 있습니다."
  echo "  git rm --cached data/status.json 을 한 번 실행한 뒤 다시 돌리세요."
  git reset -q
  exit 1
fi

if [ -z "$(git status --porcelain)" ]; then
  echo "→ 바뀐 내용이 없습니다. 커밋은 건너뜁니다."
else
  git commit -m "$MSG"
fi

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
[ "$BRANCH" = "main" ] || { echo "✗ main 브랜치에서 실행하세요 (지금: $BRANCH)"; exit 1; }

git push origin main
git push -f origin main:gh-pages

echo "→ 푸시 완료. DB는 이미 반영됐고(라이브 화면 수초 내 갱신), 저장소 사본은 1~2분 뒤 페이지에 반영됩니다."
echo "  빌드 상태 확인: gh api repos/dmstjr9706-crypto/Pickle-office/pages --jq .status"
