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


def _clean(o):
    """NaN・無限大は JSON にできない(ブラウザで読めなくなる)ので null にする。"""
    if isinstance(o, float):
        return o if o == o and o not in (float("inf"), float("-inf")) else None
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if hasattr(o, "item") and not isinstance(o, (str, bytes)):
        try:
            return _clean(o.item())
        except (ValueError, AttributeError):
            return o
    return o


def write_json(path: pathlib.Path, obj, encrypt: bool = True):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(_clean(obj), ensure_ascii=False, separators=(",", ":"), default=_default, allow_nan=False)
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


PRIVATE_LOCAL = ROOT / "out/private"   # 鍵が無い手元で作ったものの置き場(.gitignore 済み。公開リポジトリには出さない)


def save_private(path, obj):
    """記事の本文など、公開リポジトリで読まれたくない JSON を保存する(2026-10-07 パクられ対策)。
    鍵(SITE_PASSWORD)があれば暗号化して path に。無ければ平文を out/private/ の同じ場所に置き、path は触らない。"""
    path = pathlib.Path(path)
    if os.environ.get("SITE_PASSWORD"):
        write_json(path, obj, encrypt=True)
        return path
    try:
        rel = path.resolve().relative_to(ROOT)
    except ValueError:
        rel = pathlib.Path(path.name)
    alt = PRIVATE_LOCAL / rel
    alt.parent.mkdir(parents=True, exist_ok=True)
    alt.write_text(json.dumps(_clean(obj), ensure_ascii=False, indent=1, default=_default), encoding="utf-8")
    print(f"鍵が無いので {rel} は手元(out/private)にだけ保存しました")
    return alt


def load_private(path, default=None):
    """save_private の逆。暗号化・平文どちらでも読む。鍵が無くて読めないときは out/private/ の手元の写しを読む。"""
    path = pathlib.Path(path)
    try:
        rel = path.resolve().relative_to(ROOT)
    except ValueError:
        rel = pathlib.Path(path.name)
    alt = PRIVATE_LOCAL / rel
    if path.exists():
        try:
            return read_json(path)
        except Exception:  # noqa: BLE001  鍵が無い・違う
            pass
    if alt.exists():
        return json.loads(alt.read_text(encoding="utf-8"))
    return default


def private_exists(path) -> bool:
    path = pathlib.Path(path)
    try:
        rel = path.resolve().relative_to(ROOT)
    except ValueError:
        rel = pathlib.Path(path.name)
    return path.exists() or (PRIVATE_LOCAL / rel).exists()


def write_check():
    """パスワード確認用の小さな暗号化ファイル。"""
    write_json(ROOT / "docs/data/check.json", {"ok": True})


def encrypt_file(src, dst):
    """学習済みモデルなどのファイルをパスワードで暗号化する。"""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    pw = os.environ.get("SITE_PASSWORD", "")
    if not pw:
        raise SystemExit("SITE_PASSWORD が未設定です。モデルは保存しません")
    iv = os.urandom(12)
    pathlib.Path(dst).write_bytes(iv + AESGCM(_key(pw)).encrypt(iv, pathlib.Path(src).read_bytes(), None))


def decrypt_file(src, dst):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    b = pathlib.Path(src).read_bytes()
    pathlib.Path(dst).write_bytes(AESGCM(_key(os.environ["SITE_PASSWORD"])).decrypt(b[:12], b[12:], None))


if __name__ == "__main__":
    import sys
    {"encrypt": encrypt_file, "decrypt": decrypt_file}[sys.argv[1]](sys.argv[2], sys.argv[3])
