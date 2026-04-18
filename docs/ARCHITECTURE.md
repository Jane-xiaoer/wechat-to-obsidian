# Architecture

## Pipeline

```
WeChat Mac 4.x
    │
    ▼  frida hooks CCKeyDerivationPBKDF (a macOS system function)
┌────────────────────────────┐
│  /tmp/wechat_keys.log      │  one line-block per DB: rounds/pw/salt/dk
└────────────────────────────┘
    │
    ▼  match by salt (first 16 bytes of each DB)
┌────────────────────────────┐
│  AES-256-CBC per-page      │  SQLCipher v4: 4096-byte page, 80-byte reserve
│  (HMAC skipped)            │  Page 1: [16 salt][4000 enc][16 iv][64 hmac]
└────────────────────────────┘
    │
    ▼  sqlite3 + zstandard
┌────────────────────────────┐
│  Msg_<md5(target)>         │  per-conversation table
│    message_content (BLOB)  │  zstd-compressed if >~40 bytes
└────────────────────────────┘
    │
    ▼  format_msg() routes by local_type
┌────────────────────────────┐
│  <vault>/<folder>/<target> │  YYYY-MM/YYYY-MM-DD.md + attachments/
└────────────────────────────┘
```

## SQLCipher v4 page layout

| Bytes | Content |
|---|---|
| Page 1: `0-15` | Salt (plaintext, unique per DB) |
| Page 1: `16 – 4015` | AES-256-CBC encrypted data (4000 bytes) |
| All pages: `4016 – 4031` | IV (16 bytes) |
| All pages: `4032 – 4095` | HMAC-SHA512 (64 bytes) — skipped during decryption |

Pages 2+ have no salt prefix; the full 4016 bytes before IV are encrypted data.

## WeChat 4.x message schema

Each `Msg_<hash>` table:

```sql
CREATE TABLE Msg_<md5(wxid)> (
  local_id      INTEGER PRIMARY KEY AUTOINCREMENT,
  server_id     INTEGER,
  local_type    INTEGER,          -- 1=text, 3=image, 34=voice, 43=video, 48=location, 49=share, 10000=system, many more
  sort_seq      INTEGER,
  real_sender_id INTEGER,         -- FK to Name2Id rowid
  create_time   INTEGER,          -- unix seconds
  status        INTEGER,
  upload_status INTEGER,
  download_status INTEGER,
  server_seq    INTEGER,
  origin_source INTEGER,
  source        TEXT,             -- often zstd-compressed protobuf
  message_content TEXT,           -- raw UTF-8 or zstd frame; declared TEXT but holds binary
  compress_content TEXT,
  packed_info_data BLOB
);
```

`Name2Id` maps `user_name TEXT PRIMARY KEY → is_session INTEGER` and its `rowid` is the `real_sender_id` foreign key.

## SQLite Python gotcha

`message_content` is declared `TEXT` but actually stores arbitrary bytes (zstd frames, protobuf, UTF-8). Python's `sqlite3` tries to UTF-8-decode TEXT columns by default, which corrupts the binary. Fix:

```python
con.text_factory = bytes
cur.execute("SELECT ... CAST(message_content AS BLOB) ...")
```

## Known types that matter

| local_type | meaning | extraction |
|---|---|---|
| 1 | text | UTF-8 after optional zstd decode |
| 3 | image | XML `<img aeskey md5 cdnurl>`, file in `msg/attach/<hash>/<YYYY-MM>/Img/` |
| 34 | voice | XML `<voicemsg voicelength>`, `.amr` in `msg/file/` |
| 43 | video | XML `<videomsg playlength>`, `.mp4` in `msg/video/` |
| 48 | location | XML `<location poiname label>` |
| 49 | share card | XML `<appmsg><title><url><des></appmsg>` |
| 10000 | system notice | plain text |
| 21474836529 etc. | complex composite | protobuf — extract first URL or fall back to type label |

## Implementation notes (and the pain of getting here)

### Why not `spawn` mode

`frida.device.spawn(path)` plus `device.attach(pid)` hangs with `frida.TransportError: timeout was reached` on recent macOS with ad-hoc signed apps. Switching to `attach` mode — waiting for the process to appear after manual launch — works reliably.

### Why launch WeChat by absolute path

`open ~/Desktop/WeChat.app` routes through macOS LaunchServices, which picks the "canonical" bundle for `com.tencent.xinWeChat` (often still `/Applications/WeChat.app`). The ad-hoc signing only applies to our Desktop copy, so LaunchServices misrouting means frida attaches to an app still covered by Hardened Runtime. Solution: launch the binary directly: `~/Desktop/WeChat.app/Contents/MacOS/WeChat &`.

### Why copy+sign instead of `--allow-unsigned` or entitlements

The `/Applications/` location is SIP-protected — `codesign` fails with permission errors. Copying to `~/Desktop/` + `xattr -rc` + `codesign --force --deep --sign -` strips the Hardened Runtime flag while leaving the bundle runnable.

### Why `xattr -rc` before codesign

`cp -R` preserves extended attributes including Finder metadata and resource forks. `codesign --deep` refuses to sign bundles with these artifacts: `resource fork, Finder information, or similar detritus not allowed`. Stripping xattrs is required.

### Which Python

On Macs with multiple Pythons (Homebrew, Anaconda, Python.framework), `pip install frida-tools` may install into a different interpreter than the one `python3` resolves to. Be explicit:

```bash
which pip3             # e.g. /Library/Frameworks/Python.framework/Versions/3.13/bin/pip3
pip3 install ...
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3.13 scripts/extract_key.py
```

## Security / privacy

- Keys are derived per-session and only live in `/tmp/wechat_keys.log` (excluded from git).
- The decrypted DB contains all messages, contacts, and file references — treat it as sensitive.
- The ad-hoc signed copy is functionally equivalent to the original as far as network/data access is concerned; do not distribute it.
- This tool works entirely offline; no content leaves your machine.
