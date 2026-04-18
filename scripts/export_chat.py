"""Export a WeChat 4.x conversation from decrypted message_0.db into a structured Obsidian folder.

Usage:
  # Export filehelper (self-chat) to Obsidian
  python3 export_chat.py --db <decrypted.db> \
                         --target filehelper \
                         --vault ~/Obsidian\ Vault/ \
                         --folder "微信渠道"

  # Export by raw wxid (friend or chatroom)
  python3 export_chat.py --db <decrypted.db> --target wxid_abc123 --vault <path>

Target is converted to MD5 to locate the Msg_<hash> table.
"""
import argparse, hashlib, html, os, re, sqlite3, shutil, sys
import datetime as dt
from pathlib import Path

try:
    import zstandard as zstd
except ImportError:
    sys.exit("[!] zstandard not installed. Run: pip install zstandard")


TYPE_MAP = {
    1: "text", 3: "image", 34: "voice", 43: "video",
    47: "emoji", 48: "location", 49: "share",
    10000: "system", 65537: "system_notice",
}


def decode_content(raw: bytes) -> bytes:
    if not raw:
        return b""
    if raw[:4] == b"\x28\xB5\x2F\xFD":
        try:
            return zstd.ZstdDecompressor().decompress(raw, max_output_size=100 * 1024 * 1024)
        except Exception:
            return raw
    return raw


def xml_field(s: str, tag: str) -> str:
    m = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", s, re.DOTALL)
    return html.unescape(m.group(1).strip()) if m else ""


def xml_attr(s: str, tag: str, attr: str) -> str:
    m = re.search(rf'<{tag}[^>]*\b{attr}="([^"]+)"', s, re.DOTALL)
    return html.unescape(m.group(1)) if m else ""


def render_text(plain: str) -> str:
    m = re.search(
        r"([\x20-\x7e\u4e00-\u9fff\u3000-\u303f\uff00-\uffef][^\x00-\x08\x0b-\x1f]{2,}.*)",
        plain, re.DOTALL,
    )
    return m.group(1).strip() if m else plain.strip()


def format_msg(local_type: int, raw: bytes) -> str:
    decoded = decode_content(raw)
    text = decoded.decode("utf-8", errors="replace") if decoded else ""

    if local_type == 1:
        return render_text(text)
    if local_type == 3:
        md5 = xml_attr(text, "img", "md5") or xml_attr(text, "img", "aeskey")
        return f"[图片] md5={md5[:12]}..." if md5 else "[图片]"
    if local_type == 34:
        vl = xml_attr(text, "voicemsg", "voicelength")
        return f"[语音 {vl}ms]" if vl else "[语音]"
    if local_type == 43:
        pl = xml_attr(text, "videomsg", "playlength")
        return f"[视频 {pl}s]" if pl else "[视频]"
    if local_type == 48:
        return f"[位置] {xml_attr(text, 'location', 'poiname') or xml_attr(text, 'location', 'label')}"
    if local_type == 49 or local_type > 100:
        title = xml_field(text, "title")
        desc = xml_field(text, "des") or xml_field(text, "desc")
        url = xml_field(text, "url")
        source = xml_field(text, "sourcedisplayname")
        if url and title:
            s = f"**[{title}]({url})**"
            if source:
                s += f" — _{source}_"
            if desc:
                s += f"\n> {desc}"
            return s
        if title:
            return f"**{title}**" + (f"\n> {desc}" if desc else "")
        m = re.search(r"https?://[^\s\"'<>]+", text)
        if m:
            return m.group(0)
        return f"[类型{local_type}]"
    m = re.search(r"https?://[^\s\"'<>]+", text)
    if m:
        return m.group(0)
    return f"[类型{local_type}]"


def autodetect_wechat_root() -> Path:
    base = Path.home() / "Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files"
    if not base.exists():
        sys.exit(f"[!] WeChat data dir not found at {base}")
    users = [d for d in base.iterdir() if d.is_dir() and d.name.startswith("wxid_")]
    if not users:
        sys.exit(f"[!] No wxid_* subdirs found under {base}")
    if len(users) > 1:
        print(f"[!] Multiple wxid dirs: {[u.name for u in users]}; using the largest.", flush=True)
        users.sort(key=lambda p: sum(f.stat().st_size for f in p.rglob('*') if f.is_file()), reverse=True)
    return users[0]


def copy_attachments(wx_root: Path, target_hash: str, month: str, dst: Path) -> int:
    src = wx_root / "msg" / "attach" / target_hash / month
    if not src.exists():
        return 0
    dst.mkdir(parents=True, exist_ok=True)
    n = 0
    for root, _, files in os.walk(src):
        for f in files:
            if f.startswith("."):
                continue
            sp = Path(root) / f
            if sp.stat().st_size > 200 * 1024 * 1024:
                continue
            dp = dst / f
            if not dp.exists():
                try:
                    shutil.copy2(sp, dp)
                    n += 1
                except Exception:
                    pass
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True, help="Decrypted message_0.db path")
    ap.add_argument("--target", required=True, help="Conversation target: 'filehelper' or a wxid / chatroom id")
    ap.add_argument("--vault", required=True, help="Obsidian vault root path")
    ap.add_argument("--folder", default="WeChat", help="Folder inside vault (default: WeChat)")
    ap.add_argument("--subfolder", default=None, help="Subfolder name (default: target)")
    ap.add_argument("--no-attachments", action="store_true", help="Skip copying attachment files")
    ap.add_argument("--wechat-root", default=None, help="Override WeChat data root (auto-detected if omitted)")
    args = ap.parse_args()

    target_hash = hashlib.md5(args.target.encode()).hexdigest()
    wx_root = Path(args.wechat_root) if args.wechat_root else autodetect_wechat_root()
    out_dir = Path(args.vault).expanduser() / args.folder / (args.subfolder or args.target)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[*] target={args.target} hash={target_hash}", flush=True)
    print(f"[*] wx_root={wx_root}", flush=True)
    print(f"[*] output={out_dir}", flush=True)

    con = sqlite3.connect(args.db)
    con.text_factory = bytes
    cur = con.cursor()
    try:
        cur.execute(
            f"SELECT local_id, local_type, create_time, CAST(message_content AS BLOB) "
            f"FROM Msg_{target_hash} ORDER BY create_time ASC"
        )
    except sqlite3.OperationalError:
        sys.exit(f"[!] Table Msg_{target_hash} not found. Is the target correct?")
    rows = cur.fetchall()
    print(f"[*] total messages: {len(rows)}", flush=True)

    by_day = {}
    for lid, lt, ct, raw in rows:
        d = dt.datetime.fromtimestamp(ct)
        by_day.setdefault(d.strftime("%Y-%m-%d"), []).append((d, lt, raw))

    months_done = set()
    for daykey in sorted(by_day.keys()):
        month = daykey[:7]
        mdir = out_dir / month
        mdir.mkdir(parents=True, exist_ok=True)
        if not args.no_attachments and month not in months_done:
            n = copy_attachments(wx_root, target_hash, month, mdir / "attachments")
            if n:
                print(f"[*] {month}: copied {n} attachments", flush=True)
            months_done.add(month)

        lines = [f"# {daykey} · {args.target}", ""]
        for d, lt, raw in by_day[daykey]:
            tag = TYPE_MAP.get(lt, f"type{lt}")
            body = format_msg(lt, raw).replace("\r", "").strip()
            lines.append(f"## {d.strftime('%H:%M:%S')} · {tag}")
            lines.append("")
            lines.append(body if body else "_(空)_")
            lines.append("")
        (mdir / f"{daykey}.md").write_text("\n".join(lines), encoding="utf-8")

    print(f"[*] wrote {len(by_day)} daily files to {out_dir}", flush=True)


if __name__ == "__main__":
    main()
