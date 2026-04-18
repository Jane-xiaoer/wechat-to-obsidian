"""Decrypt a WeChat 4.x SQLCipher v4 database using a captured enc_key.

Usage:
  python3 decrypt_db.py --db <encrypted.db> --key <hex32bytes> --out <plain.db>

Auto-matches key from a frida log file:
  python3 decrypt_db.py --db <encrypted.db> --keys-log /tmp/wechat_keys.log --out <plain.db>
"""
import argparse, hashlib, os, re, sys
from Crypto.Cipher import AES

PAGE_SIZE = 4096
RESERVE = 80
IV_LEN = 16
SQLITE_HEADER = b"SQLite format 3\x00"


def find_key_for_salt(keys_log: str, salt_hex: str) -> str:
    """Scan a frida extract_key log for the dk matching the given salt."""
    blocks = open(keys_log).read().split("\n\n")
    for block in blocks:
        if "rounds=256000" not in block:
            continue
        m_salt = re.search(r"salt=([a-f0-9]+)", block)
        m_dk = re.search(r"dk=([a-f0-9]+)", block)
        if m_salt and m_dk and m_salt.group(1) == salt_hex:
            return m_dk.group(1)
    return ""


def decrypt(enc_db: str, out_db: str, enc_key_hex: str) -> None:
    enc_key = bytes.fromhex(enc_key_hex)
    with open(enc_db, "rb") as f:
        data = f.read()
    total_pages = len(data) // PAGE_SIZE
    salt = data[:16]
    print(f"[*] pages={total_pages} salt={salt.hex()}", flush=True)

    out = bytearray()
    out += SQLITE_HEADER

    for i in range(total_pages):
        page = data[i * PAGE_SIZE:(i + 1) * PAGE_SIZE]
        offset = 16 if i == 0 else 0
        enc_data = page[offset:PAGE_SIZE - RESERVE]
        iv = page[PAGE_SIZE - RESERVE: PAGE_SIZE - RESERVE + IV_LEN]
        cipher = AES.new(enc_key, AES.MODE_CBC, iv)
        plain = cipher.decrypt(enc_data)
        out += plain
        pad = PAGE_SIZE - (len(SQLITE_HEADER) if i == 0 else 0) - len(plain)
        if pad > 0:
            out += b"\x00" * pad

    with open(out_db, "wb") as f:
        f.write(bytes(out))
    print(f"[*] wrote {out_db} size={os.path.getsize(out_db)}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True, help="Encrypted WeChat DB path")
    ap.add_argument("--out", required=True, help="Output plaintext SQLite path")
    ap.add_argument("--key", help="enc_key hex (64 chars). If omitted, auto-match from --keys-log")
    ap.add_argument("--keys-log", default="/tmp/wechat_keys.log", help="Path to frida extract_key log")
    args = ap.parse_args()

    if not os.path.exists(args.db):
        sys.exit(f"[!] DB not found: {args.db}")

    salt = open(args.db, "rb").read(16).hex()
    key = args.key
    if not key:
        if not os.path.exists(args.keys_log):
            sys.exit(f"[!] No --key provided and keys log not found: {args.keys_log}")
        print(f"[*] Looking up key for salt={salt} in {args.keys_log}", flush=True)
        key = find_key_for_salt(args.keys_log, salt)
        if not key:
            sys.exit(f"[!] No matching key in log for this DB. Re-run extract_key.py and open this DB's data in WeChat.")
        print(f"[*] Matched key={key[:16]}...", flush=True)

    decrypt(args.db, args.out, key)


if __name__ == "__main__":
    main()
