# wechat-to-obsidian

> Turn your WeChat Mac 4.x favorites, filehelper, and any chat into a searchable Obsidian vault.

A Claude Code skill that pulls any WeChat conversation out of the encrypted local SQLCipher DB and into your Obsidian vault as daily markdown files with attachments preserved.

**Inspired by and built on top of** [zhuyansen/wx-favorites-report](https://github.com/zhuyansen/wx-favorites-report) — the original key-extraction methodology (frida hook of `CCKeyDerivationPBKDF`) comes from their work. This project extends it from favorites-only to arbitrary conversations, adds Obsidian export, and documents a few extra gotchas encountered in WeChat 4.1.8.

## Why

WeChat is where most of my learning ends up — links, PDFs, voice notes, screenshots, half-formed ideas. Ten years of data locked in an encrypted database with no export. This tool moves it into Obsidian where the rest of my knowledge lives.

## Features

- ✅ Decrypts SQLCipher v4 databases (favorites, messages, contacts, moments cache, etc.)
- ✅ Exports any conversation — self-chat, friends, groups — not just favorites
- ✅ Decodes zstd-compressed payloads (WeChat 4.x format)
- ✅ Extracts URLs, share cards, quoted messages, and location markers
- ✅ Copies original image/video/file attachments month-by-month
- ✅ Auto-detects WeChat data root and auto-matches keys by salt
- ✅ Works as a Claude Code skill OR a standalone CLI

## Requirements

- macOS (Intel or Apple Silicon)
- WeChat Mac **4.x**, logged in
- Python 3.9+
- `frida-tools`, `pycryptodome`, `zstandard` (see `requirements.txt`)

## Quick start

### 1. Install

```bash
git clone https://github.com/Jane-xiaoer/wechat-to-obsidian
cd wechat-to-obsidian
pip install -r requirements.txt
```

### 2. Prepare an ad-hoc signed WeChat copy

```bash
cp -R /Applications/WeChat.app ~/Desktop/WeChat.app
xattr -rc ~/Desktop/WeChat.app
codesign --force --deep --sign - ~/Desktop/WeChat.app
```

> If `/Applications/WeChat.app` doesn't exist on your Mac (some installers put it in `~/Applications/`), adjust the source path accordingly.

### 3. Capture the key

```bash
killall WeChat 2>/dev/null; sleep 2

# Start frida in one terminal
python3 scripts/extract_key.py --wait 300

# Launch the signed copy BY ABSOLUTE PATH (don't use `open` — LaunchServices may redirect)
~/Desktop/WeChat.app/Contents/MacOS/WeChat &

# In WeChat: log in, then open the conversation(s) you want to export
# (the corresponding SQLCipher DB is loaded on-demand — that's when the key gets derived)
```

### 4. Decrypt

```bash
WXDIR="$HOME/Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files"
USER_DIR=$(ls -d "$WXDIR"/wxid_*/ | head -1)

python3 scripts/decrypt_db.py \
  --db "$USER_DIR/db_storage/message/message_0.db" \
  --out /tmp/message_0_decrypted.db
```

### 5. Export a conversation to Obsidian

```bash
# "文件传输助手" (self-chat) — the most common use case
python3 scripts/export_chat.py \
  --db /tmp/message_0_decrypted.db \
  --target filehelper \
  --vault ~/Documents/Obsidian\ Vault \
  --folder "微信渠道"
```

You'll get:

```
~/Documents/Obsidian Vault/微信渠道/filehelper/
├── 2025-08/
│   ├── 2025-08-21.md
│   ├── 2025-08-22.md
│   └── attachments/   # original images, files, videos
├── 2025-09/
│   └── ...
```

Each markdown file has one `## HH:MM:SS · type` heading per message, followed by the decoded body.

### Export other conversations

```bash
# A specific friend
python3 scripts/export_chat.py --db ... --target wxid_abc123 --vault ...

# A chatroom
python3 scripts/export_chat.py --db ... --target "12345678@chatroom" --vault ...
```

## How it works

1. **Key extraction** — frida hooks macOS's `CCKeyDerivationPBKDF` system function. When WeChat opens any SQLCipher DB, it calls this function with the password, salt, and 256000 iterations. The hook captures the derived key the moment it's generated in memory.
2. **Decryption** — WeChat 4.x uses SQLCipher v4: AES-256-CBC per-page, 16-byte IV at end of each page, 64-byte HMAC-SHA512 reserve. The first page starts with a 16-byte salt that identifies the DB. We skip HMAC verification (it's for integrity, not confidentiality) and just AES-decrypt each page.
3. **Content decoding** — WeChat 4.x `message_content` is zstd-compressed for messages longer than ~40 bytes (magic `28 B5 2F FD`). Each message is a union of: raw text, XML (share cards, images, videos, locations), or protobuf.
4. **Per-conversation tables** — each chat gets its own table `Msg_<md5(target_id)>`. For "文件传输助手", that's `md5("filehelper") = 9e20f478...`. The `Name2Id` table maps user_name → is_session.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for more.

## Limitations

- macOS only (iOS and Windows use different encryption).
- Ad-hoc signed WeChat copy must be re-signed after each major version upgrade.
- The frida hook must be running *while you open the conversation* — WeChat loads DBs lazily.
- Video-号 / 小程序 / 朋友圈 pure-cloud content cannot be extracted (it's not in the local DB).
- Original photos may be stored in WeChat-CDN encrypted format; this tool copies what's plaintext in `msg/attach/`.

## Credits

- Key extraction methodology inspired by [zhuyansen/wx-favorites-report](https://github.com/zhuyansen/wx-favorites-report) — their 6-round iteration log made this possible.
- Built as part of [PAI (Personal AI Infrastructure)](https://github.com/danielmiessler/PAI).

## License

MIT

## ⚠️ Legal

Use this only on your own WeChat data. Do not use to extract data from devices or accounts you don't own. The authors assume no liability for misuse.
