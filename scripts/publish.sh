#!/usr/bin/env bash
# 현황을 올리고 배포하는 한 줄짜리 스크립트.
#   ./scripts/publish.sh "status: 11/27 18시 6편 공개 확인"
#
# 동작: 검사 → 커밋 → main 푸시 → gh-pages(배포 브랜치)를 main과 같은 내용으로 밀기
# GitHub Pages가 `gh-pages` 브랜치에서 빌드되므로 두 브랜치가 항상 같은 커밋을 가리키게 한다.
set -euo pipefail

cd "$(dirname "$0")/.."

MSG="${1:-status: 현황 갱신}"

python3 scripts/validate_status.py

if [ -z "$(git status --porcelain)" ]; then
  echo "→ 바뀐 내용이 없습니다. 커밋은 건너뜁니다."
else
  git add -A
  git commit -m "$MSG"
fi

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
[ "$BRANCH" = "main" ] || { echo "✗ main 브랜치에서 실행하세요 (지금: $BRANCH)"; exit 1; }

git push origin main
git push -f origin main:gh-pages

echo "→ 푸시 완료. 1~2분 뒤 https://dmstjr9706-crypto.github.io/Pickle-office/ 에 반영됩니다."
echo "  빌드 상태 확인: gh api repos/dmstjr9706-crypto/Pickle-office/pages --jq .status"
