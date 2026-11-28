#!/usr/bin/env python3
"""합동 비서실 실시간 DB 동기화 (Firebase Realtime Database)

네 곳(초큐티·하람 비서·키링·브이)이 **같은 현황판을 직접** 갱신한다.

- DB에는 **암호문만** 오간다. `data/status.enc.json`과 똑같은 형식
  (PBKDF2-HMAC-SHA256 60만 회 → AES-256-GCM). 비밀번호 없이는 못 읽는다.
- 읽기: 누구나 가능 (암호문이라 안전)
- 쓰기: DB에 등록된 **기록자 계정**(이메일+비밀번호 → 토큰)만 가능

준비물 (모두 로컬 전용, `.gitignore`에 있어 저장소에 올라가지 않는다)
    .office-secret      현황판 비밀번호 한 줄 (기존과 동일)
    .office-db.json     {"url": "...", "apiKey": "...", "email": "...", "password": "..."}
  환경변수로도 된다: OFFICE_DB_URL · OFFICE_DB_API_KEY · OFFICE_DB_EMAIL · OFFICE_DB_PASSWORD
  또는 한 줄로: OFFICE_DB_WRITER="url|apiKey|email|password"

사용
    python3 scripts/office_db.py verify
    python3 scripts/office_db.py get
    python3 scripts/office_db.py pull
    python3 scripts/office_db.py seat haram --now "18:05 공개 확인 대기" --state "가동 중"
    python3 scripts/office_db.py seat keyring --now "내일 07:30 수집 대기" --state "대기"
    python3 scripts/office_db.py seat vee --now "가능 업무 확인 중" --state "대기"
    python3 scripts/office_db.py push -m "손으로 고친 status.json 올리기"
    python3 scripts/office_db.py presence chuchu
    python3 scripts/office_db.py timeline 18:00 --done true

    # 4인 소통칸 (암호문 안 messages 배열, 최근 60개 유지)
    python3 scripts/office_db.py msg --from chuchu --to all --text "18시 6편 공개 확인 부탁해요"
    python3 scripts/office_db.py msg --from keyring --to chuchu --text "07:30 보고 완료"
    python3 scripts/office_db.py msgs              # 최근 20개
    python3 scripts/office_db.py msgs --to vee     # 부이에게 온 말만

종료 코드: 0 = 성공, 1 = 실패, 2 = 설정·인증 문제
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import os
import pathlib
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import encrypt_status as E  # noqa: E402  (같은 폴더의 암호화 규격을 그대로 쓴다)
import validate_status as V  # noqa: E402  (메시지도 같은 공개 범위 검사를 통과해야 한다)

from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: E402

DEFAULT_URL = "https://pickle-office-rtdb-default-rtdb.asia-southeast1.firebasedatabase.app"
CONF_FILE = ROOT / ".office-db.json"
TOKEN_FILE = ROOT / ".office-db-token.json"
LOCAL_JSON = ROOT / "data" / "status.json"
LOCAL_ENC = ROOT / "data" / "status.enc.json"
VALIDATE = HERE / "validate_status.py"

SEATS = {"chuchu": "초큐티", "haram": "하람 비서", "keyring": "키링", "vee": "브이"}
KST = dt.timezone(dt.timedelta(hours=9))

# ── 4인 소통칸 규격 ─────────────────────────────────────────────────────────
MSG_FROM = ("chuchu", "haram", "keyring", "vee")
MSG_TO = MSG_FROM + ("all",)
MSG_MAX = 60          # 암호문이 커지지 않게 최근 60개만 보관
MSG_TEXT_LIMIT = 400  # 한 줄 길이 상한


# ── 설정 ────────────────────────────────────────────────────────────────────
def config() -> dict:
    url = os.environ.get("OFFICE_DB_URL")
    api = os.environ.get("OFFICE_DB_API_KEY")
    email = os.environ.get("OFFICE_DB_EMAIL")
    pw = os.environ.get("OFFICE_DB_PASSWORD")

    inline = (os.environ.get("OFFICE_DB_WRITER") or "").strip()
    if inline:
        try:
            if inline.startswith("{"):
                d = json.loads(inline)
            elif "|" in inline:
                d = dict(zip(("url", "apiKey", "email", "password"), inline.split("|")))
            else:
                d = json.loads(base64.b64decode(inline).decode("utf-8"))
        except Exception:
            die("OFFICE_DB_WRITER 형식이 올바르지 않습니다.", 2)
        url = url or d.get("url")
        api = api or d.get("apiKey")
        email = email or d.get("email")
        pw = pw or d.get("password")

    if CONF_FILE.exists() and not (url and api and email and pw):
        try:
            d = json.loads(CONF_FILE.read_text(encoding="utf-8"))
        except Exception:
            die(f"{CONF_FILE.name} 를 읽을 수 없습니다 (JSON 형식 확인).", 2)
        url = url or d.get("url")
        api = api or d.get("apiKey")
        email = email or d.get("email")
        pw = pw or d.get("password")

    return {"url": (url or DEFAULT_URL).rstrip("/"), "apiKey": api, "email": email, "password": pw}


def office_password() -> str:
    for name in ("OFFICE_DB_SECRET", E.ENV_NAME):
        v = os.environ.get(name)
        if v:
            return v.strip("\r\n")
    if E.SECRET_FILE.exists():
        return E.SECRET_FILE.read_text(encoding="utf-8").strip("\r\n")
    if sys.stdin.isatty():
        import getpass
        return getpass.getpass("현황판 비밀번호: ")
    die("현황판 비밀번호가 없습니다 (.office-secret 또는 PICKLE_OFFICE_SECRET).", 1)


def die(msg: str, code: int = 1) -> None:
    print(f"✗ {msg}")
    raise SystemExit(code)


# ── HTTP ────────────────────────────────────────────────────────────────────
def http(url: str, method: str = "GET", data=None, timeout: int = 30):
    body = None
    headers = {"Content-Type": "application/json"}
    if data is not None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8")
            return r.status, (json.loads(raw) if raw.strip() else None)
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, raw
    except urllib.error.URLError as e:
        die(f"네트워크 오류: {e.reason}", 2)


def sign_in(cfg: dict, force: bool = False) -> str:
    if not (cfg["apiKey"] and cfg["email"] and cfg["password"]):
        die(
            "기록자 계정 설정이 없습니다. .office-db.json 에 apiKey·email·password 를 넣어 주세요\n"
            "  (또는 OFFICE_DB_API_KEY / OFFICE_DB_EMAIL / OFFICE_DB_PASSWORD 환경변수)",
            2,
        )
    if not force and TOKEN_FILE.exists():
        try:
            t = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
            if t.get("email") == cfg["email"] and float(t.get("exp", 0)) - time.time() > 300:
                return t["token"]
        except Exception:
            pass
    url = "https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key=" + urllib.parse.quote(cfg["apiKey"])
    code, out = http(url, "POST", {"email": cfg["email"], "password": cfg["password"], "returnSecureToken": True})
    if code != 200:
        msg = ""
        if isinstance(out, dict):
            msg = str(((out.get("error") or {}).get("message")) or out)
        die(f"기록자 로그인 실패 ({code}) {msg}", 2)
    token = out["idToken"]
    try:
        TOKEN_FILE.write_text(
            json.dumps({"token": token, "email": cfg["email"], "exp": time.time() + float(out.get("expiresIn", 3600))}),
            encoding="utf-8",
        )
        os.chmod(TOKEN_FILE, 0o600)
    except Exception:
        pass
    return token


def db(cfg: dict, path: str, method: str = "GET", data=None, authed: bool = False):
    url = f"{cfg['url']}/{path.strip('/')}.json"
    if authed:
        url += "?auth=" + urllib.parse.quote(sign_in(cfg))
    code, out = http(url, method, data)
    if code == 401 or code == 403:
        if authed:
            # 토큰이 만료됐을 수 있다 — 한 번만 새로 받아 재시도
            url = f"{cfg['url']}/{path.strip('/')}.json?auth=" + urllib.parse.quote(sign_in(cfg, force=True))
            code, out = http(url, method, data)
    if code not in (200, 204):
        die(f"DB {method} /{path} 실패 ({code}) {out if isinstance(out, str) else json.dumps(out, ensure_ascii=False)[:200]}", 1)
    return out


# ── 암호 ────────────────────────────────────────────────────────────────────
def valid_meta(meta) -> bool:
    return isinstance(meta, dict) and all(k in meta for k in ("salt", "iv", "ciphertext"))


def decrypt(meta: dict, pw: str) -> dict:
    salt = E.b64d(meta["salt"])
    iterations = int(meta.get("iterations") or E.ITERATIONS)
    key = E.derive_key(pw, salt, iterations)
    raw = AESGCM(key).decrypt(E.b64d(meta["iv"]), E.b64d(meta["ciphertext"]), None)
    return json.loads(raw.decode("utf-8"))


def encrypt(payload: dict, pw: str, hint: dict | None = None, new_salt: bool = False) -> dict:
    raw = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    salt, iterations = None, E.ITERATIONS
    if hint and not new_salt:
        try:
            decrypt(hint, pw)  # 같은 비밀번호로 열리면 salt 재사용 → 기기 기억 열쇠 유지
            salt, iterations = E.b64d(hint["salt"]), int(hint.get("iterations") or E.ITERATIONS)
        except Exception:
            salt = None
    if not salt:
        salt = os.urandom(E.SALT_BYTES)
    key = E.derive_key(pw, salt, iterations)
    iv = os.urandom(E.IV_BYTES)
    ct = AESGCM(key).encrypt(iv, raw, None)
    return {
        "v": E.VERSION,
        "kdf": "PBKDF2-HMAC-SHA256",
        "cipher": "AES-256-GCM",
        "iterations": iterations,
        "salt": E.b64e(salt),
        "iv": E.b64e(iv),
        "ciphertext": E.b64e(ct),
        "plaintext_bytes": len(raw),
        "encrypted_at": dt.datetime.now(KST).isoformat(timespec="seconds"),
    }


# ── 파일 ────────────────────────────────────────────────────────────────────
def write_local(payload: dict, meta: dict) -> None:
    LOCAL_JSON.parent.mkdir(parents=True, exist_ok=True)
    tmp = LOCAL_JSON.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(LOCAL_JSON)
    LOCAL_ENC.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def validate_local() -> None:
    if not VALIDATE.exists():
        return
    r = subprocess.run([sys.executable, str(VALIDATE), "--quiet"], cwd=str(ROOT), capture_output=True, text=True)
    out = (r.stdout or "").strip()
    if r.returncode != 0:
        print(out or "✗ 형식 검사 실패")
        die("data/status.json 검사를 통과하지 못해 올리지 않습니다.", 1)


def now_iso() -> str:
    return dt.datetime.now(KST).isoformat(timespec="seconds")


# ── 소통칸 도우미 ───────────────────────────────────────────────────────────
def msg_people(mid: str) -> str:
    return "전체" if mid == "all" else SEATS.get(mid, mid)


def msg_when(iso) -> str:
    """at 값을 한국 시간 MM/DD HH:MM 으로 짧게."""
    try:
        d = dt.datetime.fromisoformat(str(iso))
        if d.tzinfo is None:
            d = d.replace(tzinfo=KST)
        return d.astimezone(KST).strftime("%m/%d %H:%M")
    except Exception:
        return str(iso)[:16]


def msg_line(m: dict) -> str:
    return f"{msg_when(m.get('at'))} · {msg_people(str(m.get('from')))} → {msg_people(str(m.get('to')))} · {m.get('text','')}"


def sort_messages(msgs) -> list:
    """at(시각) 오름차순, 같은 시각이면 id 순 — 화면과 CLI가 같은 순서로 본다."""
    items = [m for m in (msgs or []) if isinstance(m, dict)]
    return sorted(items, key=lambda m: (str(m.get("at") or ""), str(m.get("id") or "")))


def clean_msg_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()[:MSG_TEXT_LIMIT]


def print_messages(payload: dict, limit: int = 5, indent: str = "  ") -> None:
    msgs = sort_messages(payload.get("messages"))
    if not msgs:
        return
    print(f"{indent}소통칸 최근 {min(limit, len(msgs))}개 (전체 {len(msgs)}개)")
    for m in msgs[-limit:]:
        print(f"{indent}  {msg_line(m)}")


def audit(cfg: dict, by: str, note: str) -> None:
    try:
        db(cfg, "office/log", "POST", {"at": now_iso(), "by": by, "note": note[:160]}, authed=True)
    except SystemExit:
        pass


def heartbeat(cfg: dict, seat: str) -> None:
    if seat not in SEATS:
        return
    try:
        db(cfg, f"office/presence/{seat}", "PUT", {"at": int(time.time() * 1000), "by": seat}, authed=True)
    except SystemExit:
        pass


# ── 명령 ────────────────────────────────────────────────────────────────────
def cmd_verify(args) -> int:
    cfg = config()
    pw = office_password()
    token = sign_in(cfg)
    me = json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "==").decode("utf-8"))
    print(f"✓ DB       {cfg['url']}")
    print(f"✓ 기록자   {me.get('email')} (uid {me.get('user_id')})")
    meta = db(cfg, "office/status")
    if not valid_meta(meta):
        print("· 아직 DB에 현황이 없습니다. `python3 scripts/office_db.py push` 로 올리세요.")
        return 0
    try:
        payload = decrypt(meta, pw)
    except Exception:
        die("DB 암호문을 이 비밀번호로 열 수 없습니다 — DB와 .office-secret 의 비밀번호가 다릅니다.", 2)
    print(f"✓ 현황     {payload.get('updated_at')} · {payload.get('updated_by')} 기록 · {payload.get('headline','')[:40]}")
    print(f"✓ 암호화   {meta.get('encrypted_at')} · {meta.get('cipher')} · PBKDF2 {int(meta.get('iterations', 0)):,}회")
    pres = db(cfg, "office/presence") or {}
    for seat in SEATS:
        p = pres.get(seat)
        if isinstance(p, dict) and p.get("at"):
            ago = int((time.time() * 1000 - float(p["at"])) / 60000)
            print(f"· 접속     {SEATS[seat]:<8} {ago}분 전")
    return 0


def cmd_get(args) -> int:
    cfg = config()
    pw = office_password()
    meta = db(cfg, "office/status")
    if not valid_meta(meta):
        die("DB에 현황이 없습니다.", 1)
    payload = decrypt(meta, pw)
    print(f"현황판 {payload.get('updated_at')} · {payload.get('updated_by')} 기록")
    print(f"  {payload.get('headline','')}")
    for c in payload.get("characters", []):
        print(f"  [{c.get('id')}] {c.get('state')} · {c.get('now')}")
    print_messages(payload)
    return 0


def cmd_pull(args) -> int:
    cfg = config()
    pw = office_password()
    meta = db(cfg, "office/status")
    if not valid_meta(meta):
        die("DB에 현황이 없습니다.", 1)
    payload = decrypt(meta, pw)
    write_local(payload, meta)
    print(f"✓ DB → 로컬  {payload.get('updated_at')} · {payload.get('updated_by')} 기록")
    for c in payload.get("characters", []):
        print(f"  [{c.get('id')}] {c.get('state')} · {c.get('now')}")
    print_messages(payload)
    return 0


def cmd_push(args) -> int:
    cfg = config()
    pw = office_password()
    if not LOCAL_JSON.exists():
        die("data/status.json 이 없습니다. 먼저 `pull` 하세요.", 1)
    validate_local()
    payload = json.loads(LOCAL_JSON.read_text(encoding="utf-8"))
    if args.by:
        payload["updated_by"] = args.by
    payload["updated_at"] = now_iso()
    old = db(cfg, "office/status")
    meta = encrypt(payload, pw, hint=old if valid_meta(old) else None)
    db(cfg, "office/status", "PUT", meta, authed=True)
    write_local(payload, meta)
    seat = args.by or ""
    for sid, name in SEATS.items():
        if name == seat:
            heartbeat(cfg, sid)
    if args.message:
        audit(cfg, payload.get("updated_by", ""), args.message)
    print(f"✓ 로컬 → DB  {payload['updated_at']} · {payload['updated_by']} · {len(meta['ciphertext'])} bytes")
    print("  웹페이지는 몇 초 안에 자동 반영됩니다.")
    print("  저장소(암호문)도 함께 맞추려면: ./scripts/publish.sh \"status: …\"")
    return 0


def cmd_seat(args) -> int:
    if args.seat not in SEATS:
        die(f"자리 이름은 {', '.join(SEATS)} 중 하나입니다.", 1)
    cfg = config()
    pw = office_password()
    old = db(cfg, "office/status")
    if not valid_meta(old):
        die("DB에 현황이 없습니다. 먼저 초큐티 쪽에서 `push` 해 주세요.", 1)
    payload = decrypt(old, pw)
    target = next((c for c in payload.get("characters", []) if c.get("id") == args.seat), None)
    if target is None:
        die(f"현황판에 '{args.seat}' 자리가 없습니다.", 1)
    before = {k: target.get(k) for k in ("state", "now", "next")}
    if args.now:
        target["now"] = args.now
    if args.state:
        target["state"] = args.state
    if args.next:
        target["next"] = args.next
    if args.duties:
        target["duties"] = [d.strip() for d in args.duties.split(";") if d.strip()]
    payload["updated_at"] = now_iso()
    payload["updated_by"] = SEATS[args.seat]

    # 비밀번호 평문이 payload 에 섞이지 않았는지 (공개 저장소 규칙)
    if pw in json.dumps(payload, ensure_ascii=False):
        die("현황에 비밀번호 문자열이 들어갑니다. 중단합니다.", 1)

    meta = encrypt(payload, pw, hint=old)
    db(cfg, "office/status", "PUT", meta, authed=True)
    write_local(payload, meta)
    heartbeat(cfg, args.seat)
    note = args.note or f"{SEATS[args.seat]}: {target.get('now','')}"[:150]
    audit(cfg, SEATS[args.seat], note)
    print(f"✓ {SEATS[args.seat]} 자리 갱신  {payload['updated_at']}")
    for k in ("state", "now", "next"):
        if before.get(k) != target.get(k):
            print(f"  {k}: {before.get(k)!s} → {target.get(k)!s}")
    print("  웹페이지는 몇 초 안에 자동 반영됩니다 (실시간 연결).")
    return 0


def cmd_presence(args) -> int:
    if args.seat not in SEATS:
        die(f"자리 이름은 {', '.join(SEATS)} 중 하나입니다.", 1)
    cfg = config()
    heartbeat(cfg, args.seat)
    print(f"✓ {SEATS[args.seat]} 접속 표시 갱신")
    return 0


def cmd_timeline(args) -> int:
    cfg = config()
    pw = office_password()
    old = db(cfg, "office/status")
    if not valid_meta(old):
        die("DB에 현황이 없습니다.", 1)
    payload = decrypt(old, pw)
    hit = [t for t in payload.get("timeline", []) if str(t.get("time")) == args.time]
    if not hit:
        die(f"타임라인에 {args.time} 항목이 없습니다.", 1)
    for t in hit:
        t["done"] = args.done
    payload["updated_at"] = now_iso()
    payload["updated_by"] = args.by
    meta = encrypt(payload, pw, hint=old)
    db(cfg, "office/status", "PUT", meta, authed=True)
    write_local(payload, meta)
    audit(cfg, args.by, f"타임라인 {args.time} {'완료' if args.done else '미완료'}")
    print(f"✓ 타임라인 {args.time} → {'완료' if args.done else '미완료'}")
    return 0


def cmd_msg(args) -> int:
    """소통칸에 한 줄 남기기 — 현재 DB를 받아 messages 배열에만 더하고 바로 올린다."""
    if args.sender not in MSG_FROM:
        die(f"보내는 사람은 {', '.join(MSG_FROM)} 중 하나입니다.", 1)
    to = (args.to or "all").strip()
    if to not in MSG_TO:
        die(f"받는 사람은 {', '.join(MSG_TO)} 중 하나입니다.", 1)
    text = clean_msg_text(args.text)
    if not text:
        die("보낼 내용이 비어 있습니다. --text 로 한 줄을 넣어 주세요.", 1)
    at = args.at or now_iso()
    try:
        parsed = dt.datetime.fromisoformat(at)
        if parsed.tzinfo is None:
            raise ValueError
    except ValueError:
        die("--at 은 시간대가 붙은 ISO 8601 형식이어야 합니다 (예: 2026-11-28T14:16:00+09:00).", 1)

    cfg = config()
    pw = office_password()
    old = db(cfg, "office/status")
    if not valid_meta(old):
        die("DB에 현황이 없습니다. 먼저 초큐티 쪽에서 `push` 해 주세요.", 1)
    payload = decrypt(old, pw)

    # 공개 저장소 규칙 — 비밀번호와 개인정보 패턴은 메시지에도 남기지 않는다
    if pw in text:
        die("메시지에 현황판 비밀번호가 들어갑니다. 중단합니다.", 1)
    privacy = V.check_privacy({"text": text})
    if privacy:
        print("✗ 공개하면 안 되는 정보가 메시지에 들어 있습니다.")
        for e in privacy:
            print("   -", e)
        die("개인정보·비밀값을 빼고 다시 보내 주세요.", 1)

    msgs = sort_messages(payload.get("messages"))
    mid = dt.datetime.now(KST).strftime("%Y%m%dT%H%M%S") + "-" + os.urandom(2).hex()
    msgs.append({"id": mid, "at": at, "from": args.sender, "to": to, "text": text})
    msgs = sort_messages(msgs)[-MSG_MAX:]
    payload["messages"] = msgs

    meta = encrypt(payload, pw, hint=old)
    db(cfg, "office/status", "PUT", meta, authed=True)
    write_local(payload, meta)
    heartbeat(cfg, args.sender)
    audit(cfg, SEATS[args.sender], f"소통칸 → {msg_people(to)}: {text}"[:150])
    print(f"✓ {SEATS[args.sender]} → {msg_people(to)}  ({msg_when(at)})")
    print(f"  {text}")
    print(f"  소통칸 전체 {len(msgs)}개 (최근 {MSG_MAX}개 보관)")
    print("  웹페이지 회의실 소통칸은 몇 초 안에 자동 반영됩니다.")
    print("  저장소(암호문)도 함께 맞추려면: ./scripts/publish.sh \"msg: …\"")
    return 0


def cmd_msgs(args) -> int:
    cfg = config()
    pw = office_password()
    meta = db(cfg, "office/status")
    if not valid_meta(meta):
        die("DB에 현황이 없습니다.", 1)
    payload = decrypt(meta, pw)
    msgs = sort_messages(payload.get("messages"))
    if args.sender:
        msgs = [m for m in msgs if m.get("from") == args.sender]
    if args.to:
        msgs = [m for m in msgs if m.get("to") in (args.to, "all") and m.get("from") != args.to]
    if not msgs:
        print("· 소통칸에 해당하는 메시지가 없습니다.")
        return 0
    limit = max(1, int(args.limit))
    print(f"소통칸 {len(msgs)}개 중 최근 {min(limit, len(msgs))}개")
    for m in msgs[-limit:]:
        print("  " + msg_line(m))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="합동 비서실 실시간 DB 동기화")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("verify", help="연결·인증·암호 확인").set_defaults(func=cmd_verify)
    sub.add_parser("get", help="DB 현황 요약").set_defaults(func=cmd_get)
    sub.add_parser("pull", help="DB → 로컬(data/status.json)").set_defaults(func=cmd_pull)

    p = sub.add_parser("push", help="로컬(data/status.json) → DB")
    p.add_argument("-m", "--message", default="", help="기록 메모")
    p.add_argument("--by", default="", help="기록자 이름 (기본: status.json 값 유지)")
    p.set_defaults(func=cmd_push)

    p = sub.add_parser("seat", help="내 자리 한 줄 갱신 (가장 흔한 쓰기)")
    p.add_argument("seat", choices=list(SEATS))
    p.add_argument("--now", help="지금 하는 일 한 줄")
    p.add_argument("--state", help="'가동 중' 또는 '대기'")
    p.add_argument("--next", help="다음 예정 한 줄")
    p.add_argument("--duties", help="상시 담당 (세미콜론으로 구분)")
    p.add_argument("--note", default="", help="기록 메모")
    p.set_defaults(func=cmd_seat)

    p = sub.add_parser("presence", help="접속 표시만 갱신")
    p.add_argument("seat", choices=list(SEATS))
    p.set_defaults(func=cmd_presence)

    p = sub.add_parser("timeline", help="타임라인 항목 완료 표시")
    p.add_argument("time", help="예: 18:00")
    p.add_argument("--done", type=lambda v: v.lower() in ("1", "true", "y", "yes", "완료"), default=True)
    p.add_argument("--by", default="초큐티")
    p.set_defaults(func=cmd_timeline)

    p = sub.add_parser("msg", help="소통칸에 한 줄 남기기 (4인 공용)")
    p.add_argument("--from", dest="sender", required=True, choices=list(MSG_FROM), help="보내는 자리")
    p.add_argument("--to", default="all", choices=list(MSG_TO), help="받는 자리 또는 all(전체)")
    p.add_argument("--text", required=True, help="한 줄 내용 (최대 400자)")
    p.add_argument("--at", default="", help="시각 지정 (기본: 지금, ISO 8601)")
    p.set_defaults(func=cmd_msg)

    p = sub.add_parser("msgs", help="소통칸 읽기")
    p.add_argument("--sender", "--from", dest="sender", choices=list(MSG_FROM), help="보낸 사람으로 거르기")
    p.add_argument("--to", choices=list(MSG_FROM), help="받는 사람으로 거르기 (all 포함)")
    p.add_argument("--limit", default=20, type=int, help="최근 N개 (기본 20)")
    p.set_defaults(func=cmd_msgs)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
