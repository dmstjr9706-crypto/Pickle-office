#!/usr/bin/env python3
"""data/status.json 의 한 항목만 빠르게 고치는 도우미.

화면 전체를 다시 쓰지 않고, 지금 하는 일·상태·일정 체크·예약 상태만 바꾼다.
고친 뒤 updated_at 을 현재 KST 시각으로 자동 갱신하고 검사를 다시 돌린다.

사용 예:
    python3 scripts/set_status.py now   chuchu "생존 EP.10 렌더 중 (18시 예약 예정)"
    python3 scripts/set_status.py state keyring "대기"
    python3 scripts/set_status.py done  "18:00" true
    python3 scripts/set_status.py slot  2026-11-27 kvCvSltdsEU "공개 완료"
    python3 scripts/set_status.py headline "11/27 18시 6편 공개 완료 · 내일분 준비"
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "status.json"
KST = dt.timezone(dt.timedelta(hours=9))


def load() -> dict:
    return json.loads(DATA.read_text(encoding="utf-8"))


def save(d: dict) -> None:
    d["updated_at"] = dt.datetime.now(KST).replace(microsecond=0).isoformat()
    DATA.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def find_char(d: dict, key: str) -> dict:
    for c in d["characters"]:
        if c["id"] == key or c["name"] == key:
            return c
    raise SystemExit(f"캐릭터를 찾을 수 없습니다: {key} (chuchu/haram/keyring/vee 또는 이름)")


def main() -> int:
    ap = argparse.ArgumentParser(description="status.json 부분 수정")
    ap.add_argument("--by", default="초큐티", help="기록자(updated_by)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("now", help="캐릭터의 '지금' 한 줄")
    p.add_argument("character")
    p.add_argument("text")

    p = sub.add_parser("state", help="캐릭터 상태 (가동 중 / 대기)")
    p.add_argument("character")
    p.add_argument("value")

    p = sub.add_parser("next", help="캐릭터의 '다음' 한 줄")
    p.add_argument("character")
    p.add_argument("text")

    p = sub.add_parser("done", help="타임라인 항목 체크 (HH:MM)")
    p.add_argument("time")
    p.add_argument("value", choices=["true", "false"])

    p = sub.add_parser("slot", help="유튜브 슬롯 상태 변경 (date + 영상ID 또는 인덱스)")
    p.add_argument("date")
    p.add_argument("key")
    p.add_argument("status")

    p = sub.add_parser("headline", help="상단 머리말")
    p.add_argument("text")

    args = ap.parse_args()
    d = load()

    if args.cmd == "now":
        find_char(d, args.character)["now"] = args.text
    elif args.cmd == "state":
        find_char(d, args.character)["state"] = args.value
    elif args.cmd == "next":
        find_char(d, args.character)["next"] = args.text
    elif args.cmd == "done":
        hit = [t for t in d["timeline"] if t["time"] == args.time]
        if not hit:
            raise SystemExit(f"타임라인에 {args.time} 항목이 없습니다")
        for t in hit:
            t["done"] = args.value == "true"
    elif args.cmd == "slot":
        day = [x for x in d["youtube"] if x["date"] == args.date]
        if not day:
            raise SystemExit(f"youtube 에 {args.date} 블록이 없습니다")
        hit = [s for s in day[0]["slots"] if args.key in s.get("url", "") or args.key == s.get("channel")]
        if not hit:
            raise SystemExit(f"{args.date} 에 '{args.key}' 슬롯이 없습니다")
        for s in hit:
            s["status"] = args.status  # 화면은 슬롯 status 가 있으면 표시
    elif args.cmd == "headline":
        d["headline"] = args.text

    d["updated_by"] = args.by
    save(d)

    ok = __import__("subprocess").run(
        [sys.executable, str(ROOT / "scripts" / "validate_status.py"), "--quiet"],
        capture_output=True, text=True,
    )
    print(ok.stdout.strip() or ok.stderr.strip())
    print("→ data/status.json 저장 완료:", args.cmd)
    print("   올리기: ./scripts/publish.sh \"status: …\"  (검사 → 암호화 → 커밋 → 푸시)")
    return ok.returncode


if __name__ == "__main__":
    sys.exit(main())
