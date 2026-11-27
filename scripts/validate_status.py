#!/usr/bin/env python3
"""data/status.json 검사기.

1) 형식 검사  — 화면이 읽는 키와 타입이 맞는지
2) 공개 금지 검사 — 공개 저장소에 올리면 안 되는 개인정보 패턴

사용:
    python3 scripts/validate_status.py
    python3 scripts/validate_status.py --quiet   # 문제 없으면 요약만
종료 코드: 0 = 통과, 1 = 커밋하면 안 됨
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "status.json"

CHAR_IDS = {"chuchu", "haram", "keyring", "vee"}
STATUS_WORDS = {"발행 완료", "예약", "예정", "진행 중", "공개 완료", "대기"}

# 공개 저장소에 올리면 안 되는 패턴 -------------------------------------------------
FORBIDDEN = [
    ("휴대전화번호", re.compile(r"(?<![\d-])01[016789][-.\s]?\d{3,4}[-.\s]?\d{4}(?![\d-])")),
    ("유선전화번호", re.compile(r"(?<![\d-])0(?:2|3[1-3]|4[1-4]|5[1-5]|6[1-4]|70)[-.\s]?\d{3,4}[-.\s]?\d{4}(?![\d-])")),
    ("이메일 주소", re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]{2,}")),
    ("주민등록번호", re.compile(r"(?<!\d)\d{6}-\d{7}(?!\d)")),
    ("계좌·카드번호", re.compile(r"(?<![/\d])\d{10,}(?![\d/])")),
    ("비밀번호 표기", re.compile(r"(?i)(password|passwd|비밀번호|pw)\s*[:=]\s*\S+")),
]

FORBIDDEN_WORDS = ["주민등록", "계좌번호", "카드번호", "api key", "api_key", "secret", "token"]


def walk(node, path="$"):
    """(경로, 문자열) 쌍을 모두 돌려준다."""
    if isinstance(node, dict):
        for k, v in node.items():
            yield from walk(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from walk(v, f"{path}[{i}]")
    elif isinstance(node, str):
        yield path, node


def check_schema(d: dict) -> list[str]:
    errs: list[str] = []
    for key in ("schema", "updated_at", "characters", "youtube", "publishing", "campaigns", "timeline"):
        if key not in d:
            errs.append(f"필수 키 없음: {key}")
    if errs:
        return errs

    try:
        dt.datetime.fromisoformat(str(d["updated_at"]))
    except ValueError:
        errs.append("updated_at 이 ISO 8601 형식이 아님 (예: 2026-11-27T14:30:00+09:00)")

    chars = d["characters"]
    if not isinstance(chars, list) or len(chars) != 4:
        errs.append("characters 는 4개여야 함 (chuchu·haram·keyring·vee)")
    else:
        seen = set()
        for i, c in enumerate(chars):
            for k in ("id", "name", "mark", "color", "device", "role", "state", "now", "duties"):
                if k not in c:
                    errs.append(f"characters[{i}] 에 '{k}' 없음")
            if c.get("id") not in CHAR_IDS:
                errs.append(f"characters[{i}].id '{c.get('id')}' 는 chuchu/haram/keyring/vee 중 하나여야 함")
            if c.get("id") in seen:
                errs.append(f"characters[{i}].id 중복: {c.get('id')}")
            seen.add(c.get("id"))
            for k in ("color", "deep"):
                v = c.get(k, "")
                if v and not re.fullmatch(r"#[0-9A-Fa-f]{6}", v):
                    errs.append(f"characters[{i}].{k} 는 #RRGGBB 형식이어야 함")

    for i, day in enumerate(d.get("youtube") or []):
        for k in ("date", "label", "time", "state", "slots"):
            if k not in day:
                errs.append(f"youtube[{i}] 에 '{k}' 없음")
        for j, s in enumerate(day.get("slots") or []):
            for k in ("channel", "type", "title", "url"):
                if k not in s:
                    errs.append(f"youtube[{i}].slots[{j}] 에 '{k}' 없음")
            u = str(s.get("url", ""))
            if u and not u.startswith("https://"):
                errs.append(f"youtube[{i}].slots[{j}].url 은 https 여야 함")

    for i, p in enumerate(d.get("publishing") or []):
        for k in ("platform", "name", "account", "owner", "slot", "title", "status"):
            if k not in p:
                errs.append(f"publishing[{i}] 에 '{k}' 없음")
        if p.get("status") not in STATUS_WORDS:
            errs.append(f"publishing[{i}].status '{p.get('status')}' 는 {sorted(STATUS_WORDS)} 중 하나여야 함")

    for i, t in enumerate(d.get("timeline") or []):
        for k in ("time", "label", "owner", "done"):
            if k not in t:
                errs.append(f"timeline[{i}] 에 '{k}' 없음")
        if not re.fullmatch(r"\d{2}:\d{2}", str(t.get("time", ""))):
            errs.append(f"timeline[{i}].time 은 HH:MM 이어야 함")
        if not isinstance(t.get("done"), bool):
            errs.append(f"timeline[{i}].done 은 true/false 여야 함")

    for i, b in enumerate((d.get("campaigns") or [])):
        for k in ("id", "icon", "title", "headline"):
            if k not in b:
                errs.append(f"campaigns[{i}] 에 '{k}' 없음")
    return errs


def check_privacy(d: dict) -> list[str]:
    errs: list[str] = []
    for path, text in walk(d):
        for name, rx in FORBIDDEN:
            for m in rx.finditer(text):
                snippet = text[max(0, m.start() - 12): m.end() + 12].replace("\n", " ")
                errs.append(f"[{name}] {path} … {snippet} …")
        low = text.lower()
        for w in FORBIDDEN_WORDS:
            if w in low:
                errs.append(f"[금지어 '{w}'] {path} … {text[:60]}")
    return errs


def summary(d: dict) -> str:
    lines = []
    lines.append(f"갱신 {d['updated_at']}  ·  기록 {d.get('updated_by', '-')}")
    lines.append(f"머리말  {d.get('headline', '')}")
    for c in d["characters"]:
        lines.append(f"  · {c['name']:<6} ({c['device']}) [{c['state']}] {c['now']}")
    for day in d["youtube"]:
        lines.append(f"  · 유튜브 {day['label']} {day['time']} — {len(day['slots'])}편 / {day['state']}")
    for p in d["publishing"]:
        lines.append(f"  · {p['platform']:<7} {p['slot']} {p['name']:<10} {p['status']}  {p['title'][:34]}")
    done = sum(1 for t in d["timeline"] if t["done"])
    lines.append(f"  · 타임라인 {done}/{len(d['timeline'])} 완료")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quiet", action="store_true", help="통과 시 요약만 출력")
    args = ap.parse_args()

    if not DATA.exists():
        print(f"✗ 데이터 파일이 없습니다: {DATA}")
        return 1

    try:
        raw = DATA.read_text(encoding="utf-8")
        d = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"✗ JSON 문법 오류: {e}")
        return 1

    schema_errs = check_schema(d)
    privacy_errs = check_privacy(d)

    if schema_errs:
        print("✗ 형식 오류")
        for e in schema_errs:
            print("   -", e)
    if privacy_errs:
        print("✗ 공개하면 안 되는 정보가 들어 있습니다 (이대로 커밋 금지)")
        for e in privacy_errs:
            print("   -", e)

    if schema_errs or privacy_errs:
        return 1

    if not args.quiet:
        print("✓ 검사 통과 — 형식·공개 범위 모두 문제 없음\n")
        print(summary(d))
        print(f"\n{len(d['characters'])}명 캐릭터 · {sum(len(x['slots']) for x in d['youtube'])}개 예약 슬롯 · "
              f"{len(d['publishing'])}개 발행 항목 · {len(d['timeline'])}개 일정")
    else:
        print("✓ 검사 통과")
    return 0


if __name__ == "__main__":
    sys.exit(main())
