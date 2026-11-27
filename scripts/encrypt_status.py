#!/usr/bin/env python3
"""data/status.json → data/status.enc.json (PBKDF2-HMAC-SHA256 + AES-256-GCM)

평문 현황판은 로컬에만 두고, 저장소에는 암호문만 올린다.
비밀번호는 이 스크립트가 읽기만 하고 **어떤 파일에도 쓰지 않는다**
(커밋되는 산출물에 평문 비밀번호가 남지 않도록).

비밀번호를 읽는 순서
  1) 환경변수  PICKLE_OFFICE_SECRET
  2) 로컬 파일  .office-secret   (한 줄, .gitignore 에 등록됨)
  3) 터미널 입력 (getpass)

사용:
    python3 scripts/encrypt_status.py            # 조용히 암호화
    python3 scripts/encrypt_status.py --quiet    # 한 줄 요약만
    python3 scripts/encrypt_status.py --new-salt # salt 새로 만들기 (기억된 키 무효화)
종료 코드: 0 = 성공, 1 = 실패
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import getpass
import json
import os
import pathlib
import re
import sys

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "status.json"
OUT = ROOT / "data" / "status.enc.json"
SECRET_FILE = ROOT / ".office-secret"

ENV_NAME = "PICKLE_OFFICE_SECRET"
ITERATIONS = 600_000          # OWASP 권장(PBKDF2-HMAC-SHA256)
SALT_BYTES = 16
IV_BYTES = 12
VERSION = 1


def b64e(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def b64d(text: str) -> bytes:
    return base64.b64decode(text.encode("ascii"), validate=True)


def read_password() -> str:
    """비밀번호를 읽는다. 어떤 경로로 읽었는지는 밝히지 않고 값도 출력하지 않는다."""
    env = os.environ.get(ENV_NAME)
    if env:
        return env.strip("\r\n")
    if SECRET_FILE.exists():
        return SECRET_FILE.read_text(encoding="utf-8").strip("\r\n")
    if not sys.stdin.isatty():
        print(f"✗ 비밀번호가 없습니다. 환경변수 {ENV_NAME} 또는 {SECRET_FILE.name} 파일을 쓰세요.")
        raise SystemExit(1)
    return getpass.getpass("현황판 비밀번호: ")


def derive_key(password: str, salt: bytes, iterations: int) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=iterations)
    return kdf.derive(password.encode("utf-8"))


def existing_salt() -> tuple[bytes, int] | None:
    """기존 암호문의 salt/iterations 를 재사용해 '이 기기에서 기억하기'를 살려 둔다."""
    if not OUT.exists():
        return None
    try:
        meta = json.loads(OUT.read_text(encoding="utf-8"))
        salt = b64d(meta["salt"])
        iterations = int(meta.get("iterations") or ITERATIONS)
    except Exception:
        return None
    if len(salt) < 16 or iterations < 10_000:
        return None
    return salt, iterations


def main() -> int:
    ap = argparse.ArgumentParser(description="현황판 암호화")
    ap.add_argument("--quiet", action="store_true", help="요약 한 줄만 출력")
    ap.add_argument("--new-salt", action="store_true", help="salt 를 새로 만든다")
    args = ap.parse_args()

    if not SRC.exists():
        print(f"✗ 평문 데이터가 없습니다: {SRC.relative_to(ROOT)}")
        return 1

    raw = SRC.read_bytes()
    try:
        json.loads(raw.decode("utf-8"))
    except Exception as e:
        print(f"✗ data/status.json 이 올바른 JSON 이 아닙니다: {e}")
        return 1

    password = read_password()
    if len(password) < 4:
        print("✗ 비밀번호가 너무 짧습니다 (4자 이상).")
        return 1

    reused = None if args.new_salt else existing_salt()
    if reused:
        salt, iterations = reused
    else:
        salt, iterations = os.urandom(SALT_BYTES), ITERATIONS

    key = derive_key(password, salt, iterations)
    iv = os.urandom(IV_BYTES)
    ciphertext = AESGCM(key).encrypt(iv, raw, None)

    meta = {
        "v": VERSION,
        "kdf": "PBKDF2-HMAC-SHA256",
        "cipher": "AES-256-GCM",
        "iterations": iterations,
        "salt": b64e(salt),
        "iv": b64e(iv),
        "ciphertext": b64e(ciphertext),
        "plaintext_bytes": len(raw),
        "encrypted_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    text = json.dumps(meta, ensure_ascii=False, indent=2) + "\n"

    # ── 안전 검사: 산출물에 비밀번호 평문이 섞이지 않았는지 ─────────────────
    if password in text:
        print("✗ 암호문에 비밀번호 문자열이 그대로 들어갔습니다. 중단합니다.")
        return 1
    if re.search(r'"(password|passwd|secret)"\s*:', text, re.I):
        print("✗ 비밀번호 필드가 산출물에 생겼습니다. 중단합니다.")
        return 1

    # ── 왕복 검증: 같은 키로 풀어 원문과 같은지 ────────────────────────────
    check = AESGCM(derive_key(password, b64d(meta["salt"]), iterations)).decrypt(b64d(meta["iv"]), b64d(meta["ciphertext"]), None)
    if check != raw:
        print("✗ 복호화 검증 실패 — 파일을 쓰지 않습니다.")
        return 1

    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".json.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(OUT)

    if args.quiet:
        print(f"✓ 암호화 완료 {OUT.relative_to(ROOT)} ({len(text)} bytes, PBKDF2 {iterations:,})")
    else:
        print("✓ 암호화 완료")
        print(f"   원문  data/status.json ({len(raw):,} bytes, 저장소에는 올리지 않음)")
        print(f"   암호문 {OUT.relative_to(ROOT)} ({len(text):,} bytes)")
        print(f"   방식  PBKDF2-HMAC-SHA256 {iterations:,}회 → AES-256-GCM (salt 재사용: {'예' if reused else '아니오'})")
        print("   비밀번호는 이 파일에 기록되지 않았습니다 (왕복 복호화 검증 통과)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
