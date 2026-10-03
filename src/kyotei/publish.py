"""サイト用JSONの書き出し(パスワードで暗号化)。

GitHub Pages は誰でも見られるので、予想データは AES-GCM で暗号化して置く。
鍵はパスワードから PBKDF2(SHA-256, 25万回)で作る。ブラウザ側は WebCrypto で
同じ手順で復号する。パスワードは GitHub の Secret「SITE_PASSWORD」から渡す。
"""
from __future__ import annotations

import base64
import json
import os
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
SALT_PATH = ROOT / "docs/data/salt.txt"
ITER = 250_000


def _default(o):
    return o.item() if hasattr(o, "item") else str(o)


def _key(password: str) -> bytes:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    if not SALT_PATH.exists():
        SALT_PATH.parent.mkdir(parents=True, exist_ok=True)
        SALT_PATH.write_text(base64.b64encode(os.urandom(16)).decode())
    salt = base64.b64decode(SALT_PATH.read_text().strip())
    return PBKDF2HMAC(hashes.SHA256(), 32, salt, ITER).derive(password.encode())


def write_json(path: pathlib.Path, obj, encrypt: bool = True):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=_default)
    pw = os.environ.get("SITE_PASSWORD", "")
    if encrypt and not pw:
        print(f"SITE_PASSWORD が未設定のため {path.name} は公開しません")
        return
    if encrypt:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        iv = os.urandom(12)
        ct = AESGCM(_key(pw)).encrypt(iv, raw.encode(), None)
        raw = json.dumps({"enc": 1, "iv": base64.b64encode(iv).decode(),
                          "ct": base64.b64encode(ct).decode()})
    path.write_text(raw, encoding="utf-8")


def read_json(path: pathlib.Path):
    obj = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    if isinstance(obj, dict) and obj.get("enc") == 1:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        pw = os.environ.get("SITE_PASSWORD", "")
        pt = AESGCM(_key(pw)).decrypt(base64.b64decode(obj["iv"]), base64.b64decode(obj["ct"]), None)
        return json.loads(pt)
    return obj


def write_check():
    """パスワード確認用の小さな暗号化ファイル。"""
    write_json(ROOT / "docs/data/check.json", {"ok": True})
