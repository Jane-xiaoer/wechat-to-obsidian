---
name: wechat-to-obsidian
description: |
  Export any WeChat 4.x (macOS) conversation — favorites, filehelper (文件传输助手), friends, or chatrooms — into an Obsidian vault as structured markdown + attachments.
  Triggers: /wechat-to-obsidian, 微信→Obsidian, 微信备份, 文件传输助手导出
  Prerequisites: macOS, WeChat 4.x logged in, frida, pycryptodome, zstandard
---

# WeChat → Obsidian

End-to-end pipeline: extract the SQLCipher key via frida hook, decrypt WeChat's local DBs, then export any conversation into your Obsidian vault as daily markdown files grouped by month, with attachments preserved in their original format.

> **Based on** [zhuyansen/wx-favorites-report](https://github.com/zhuyansen/wx-favorites-report). Original frida-hook methodology is theirs; this skill extends it to any conversation + Obsidian export.

## What it does

- Unlocks `favorite.db`, `message_0.db`, `contact.db`, `biz_message_0.db`, `media_0.db`, and any other per-user SQLCipher v4 DB that WeChat Mac 4.x creates.
- Exports per-conversation tables (`Msg_<md5(target)>`) to timestamped markdown.
- Copies attachments (images, files, videos) from `msg/attach/<hash>/<YYYY-MM>/` into the same folder structure.
- Decodes zstd-compressed message payloads (WeChat 4.x compresses messages > ~40 bytes).

## Execution flow

### Step 1 — Ad-hoc sign a WeChat copy (once per major version)

```bash
cp -R "$(mdfind 'kMDItemCFBundleIdentifier == "com.tencent.xinWeChat"' | head -1)" ~/Desktop/WeChat.app
xattr -rc ~/Desktop/WeChat.app
codesign --force --deep --sign - ~/Desktop/WeChat.app
```

### Step 2 — Install dependencies

```bash
pip install -r requirements.txt
```

### Step 3 — Hook frida to capture the PBKDF2 key

```bash
# Close running WeChat first
killall WeChat; sleep 2

# Start the hook (waits for you to launch WeChat)
python3 scripts/extract_key.py --out /tmp/wechat_keys.log --wait 300 &

# Launch the signed copy directly (NOT via `open` — LaunchServices may redirect to /Applications)
~/Desktop/WeChat.app/Contents/MacOS/WeChat &

# Inside WeChat: log in if needed, then open the conversation you want to export
#   (e.g. click "收藏" to load favorite.db, or click "文件传输助手" to load its messages).
# Each conversation's DB is loaded lazily — the frida hook captures its key the moment you open it.
```

All captured keys land in `/tmp/wechat_keys.log` as `rounds=256000 / salt=... / dk=...` blocks. Each DB's salt is its first 16 bytes.

### Step 4 — Decrypt the target DB

```bash
WXDIR="$HOME/Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files"
USER_DIR=$(ls -d "$WXDIR"/wxid_*/ | head -1)

# Decrypt auto-matches the key by salt
python3 scripts/decrypt_db.py \
  --db "$USER_DIR/db_storage/message/message_0.db" \
  --keys-log /tmp/wechat_keys.log \
  --out /tmp/message_0_decrypted.db
```

### Step 5 — Export a conversation

```bash
# Export "文件传输助手" (self-chat) to Obsidian
python3 scripts/export_chat.py \
  --db /tmp/message_0_decrypted.db \
  --target filehelper \
  --vault ~/Documents/Obsidian\ Vault \
  --folder "微信渠道" \
  --subfolder "文件传输助手"

# Export a specific friend / chatroom
python3 scripts/export_chat.py \
  --db /tmp/message_0_decrypted.db \
  --target wxid_abc123 \
  --vault ~/Documents/Obsidian\ Vault
```

Output layout:

```
<vault>/<folder>/<subfolder>/
├── 2025-08/
│   ├── 2025-08-21.md
│   ├── 2025-08-22.md
│   └── attachments/      # original files sent that month
├── 2025-09/
│   └── ...
```

## Supported conversation targets

| target | meaning |
|---|---|
| `filehelper` | WeChat "文件传输助手" (self chat) |
| `wxid_xxx` | A specific friend |
| `12345@chatroom` | A group chat |

The script computes `MD5(target)` to locate the `Msg_<hash>` table inside the decrypted DB.

## Known limitations

- macOS only. iOS / Windows have different encryption schemes.
- You must manually open each conversation in WeChat while `extract_key.py` is running, so the frida hook captures its key. WeChat loads each DB lazily on first access.
- Images/videos/files are copied as-is from `msg/attach/`. WeChat-CDN only content (video-号 thumbnails, some large file types) is not fully local.
- After each WeChat major version upgrade, re-sign the Desktop copy.
- The HMAC page-integrity check is skipped; AES-CBC decryption still produces valid SQLite output.

## Why this exists

WeChat's "收藏" and "文件传输助手" are where many people dump decade-long knowledge — links, notes, files — but the client has no real export. This skill moves that into Obsidian where it becomes searchable, linkable, and composable with the rest of your knowledge graph.

## Credit

Key extraction methodology inspired by [zhuyansen/wx-favorites-report](https://github.com/zhuyansen/wx-favorites-report). This skill extends it to arbitrary conversations + Obsidian export.
