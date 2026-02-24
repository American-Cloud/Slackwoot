# ⚡ SlackWoot

**A lightweight, open-source bridge between [Chatwoot](https://www.chatwoot.com/) and [Slack](https://slack.com/).**

SlackWoot routes Chatwoot conversations to specific Slack channels based on inbox — and lets your team reply directly from Slack threads back into Chatwoot conversations. No more every inbox dumping into one Slack channel.

![SlackWoot Dashboard](docs/screenshot-placeholder.png)

---

## ✨ Features

- 📥 **Per-inbox routing** — map each Chatwoot inbox to its own Slack channel
- 🧵 **Full threading** — each conversation gets its own Slack thread; all messages stay organized
- ↩️ **Two-way replies** — reply in a Slack thread → message appears in Chatwoot conversation
- 🔄 **Status updates** — resolved/reopened/pending status changes posted to the Slack thread
- 🛡️ **Loop prevention** — bot messages are ignored; only real human Slack users trigger Chatwoot replies
- 🌐 **Simple web UI** — dashboard showing mappings and active threads
- ⚙️ **Config-first** — configure via `config.yaml` or environment variables
- 🐳 **Docker ready** — one-command deploy with Docker Compose
- 💾 **Persistent thread store** — JSON file keeps thread mappings across restarts

---

## 🏗️ Architecture

```
Chatwoot ──webhook──► SlackWoot ──Slack API──► Slack Channel
                          │                        │
                          │◄──Slack Events API──────┘
                          │
                          └──Chatwoot API──► Chatwoot Conversation
```

---

## 🚀 Quick Start

### 1. Clone & configure

```bash
git clone https://github.com/CodeBleu/slackwoot.git
cd slackwoot
cp config.example.yaml config.yaml
```

Edit `config.yaml` with your credentials and inbox mappings:

```yaml
chatwoot_base_url: "https://your-chatwoot.example.com"
chatwoot_api_token: "your-user-access-token"
chatwoot_account_id: 1

slack_bot_token: "xoxb-your-bot-token"
slack_signing_secret: "your-signing-secret"

inbox_mappings:
  - chatwoot_inbox_id: 4
    inbox_name: "Website Chat"
    slack_channel: "#support-website"
    slack_channel_id: "CAAAAAAAAAA"

  - chatwoot_inbox_id: 1
    inbox_name: "Email"
    slack_channel: "#support-email"
    slack_channel_id: "CBBBBBBBBB"
```

### 2. Run with Docker Compose

```bash
docker compose up -d
```

### 3. Run locally (development)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python run.py
```

The app runs at `http://localhost:8000`.

---

## ⚙️ Configuration Reference

All values can be set in `config.yaml` **or** as environment variables.

| Key / Env Var | Description |
|---|---|
| `CHATWOOT_BASE_URL` | Your Chatwoot instance URL |
| `CHATWOOT_API_TOKEN` | User access token (Settings → Profile → Access Token) |
| `CHATWOOT_ACCOUNT_ID` | Numeric account ID (visible in the URL when logged in) |
| `CHATWOOT_WEBHOOK_SECRET` | Optional — HMAC secret for webhook verification |
| `SLACK_BOT_TOKEN` | Bot token starting with `xoxb-` |
| `SLACK_SIGNING_SECRET` | From your Slack app's Basic Information page |
| `LOG_LEVEL` | `INFO` (default), `DEBUG`, `WARNING` |
| `THREAD_STORE_PATH` | Path to the thread mapping JSON file (default: `data/threads.json`) |

### Multiple mappings via environment variables

If you prefer not to use `config.yaml`, define mappings with numbered env vars:

```bash
SLACKWOOT_MAPPING_1=inbox_id:4,inbox_name:Website,slack_channel:#support-web,slack_channel_id:CAAAAAAAA
SLACKWOOT_MAPPING_2=inbox_id:1,inbox_name:Email,slack_channel:#support-email,slack_channel_id:CBBBBBBBB
```

---

## 🔧 Chatwoot Setup

1. Go to **Settings → Integrations → Webhooks → Add new webhook**
2. URL: `https://your-slackwoot-domain.com/webhook/chatwoot`
3. Enable these events:
   - ✅ `message_created`
   - ✅ `conversation_status_changed`
4. Save

---

## 💬 Slack App Setup

### Create a Slack App

1. Go to [api.slack.com/apps](https://api.slack.com/apps) → **Create New App** → **From scratch**
2. Name it something like `SlackWoot Bot`

### OAuth & Permissions — add these Bot Token Scopes:

| Scope | Purpose |
|---|---|
| `chat:write` | Post messages |
| `chat:write.customize` | Custom username/emoji per message |
| `channels:history` | Read channel history |
| `groups:history` | Read private channel history |
| `users:read` | Look up user info (loop prevention) |

### Event Subscriptions

1. Enable Events → Request URL: `https://your-slackwoot-domain.com/slack/events`
2. Subscribe to **Bot Events**:
   - `message.channels`
   - `message.groups`

### Install the App

1. Go to **OAuth & Permissions** → Install to Workspace
2. Copy the **Bot User OAuth Token** (`xoxb-...`) into your config
3. Invite the bot to each channel you mapped: `/invite @SlackWoot`

---

## 🔄 How It Works

### Chatwoot → Slack

1. A contact sends a message to a Chatwoot inbox
2. Chatwoot fires a webhook to SlackWoot
3. SlackWoot looks up which Slack channel is mapped to that inbox
4. If it's the first message: posts a rich card to Slack and saves the thread `ts`
5. Subsequent messages (from contact or agent): posted as thread replies

### Slack → Chatwoot

1. A human team member replies in a Slack thread
2. Slack fires an event to SlackWoot
3. SlackWoot checks: is this a bot? If yes, ignore (prevents loops)
4. Looks up which Chatwoot conversation matches this thread
5. Posts the reply as an outgoing agent message in Chatwoot

### Status Changes

When a conversation is resolved/reopened/set in Chatwoot, a status update is posted to the existing Slack thread.

---

## 🔒 Loop Prevention

SlackWoot uses two layers of protection to prevent infinite reply loops:

1. **Bot ID check** — Slack events with a `bot_id` field are ignored immediately
2. **User info check** — the Slack Users API is called to verify the sender is a real human (`is_bot: false`)

Only messages typed by real team members in Slack threads will be forwarded to Chatwoot.

---

## 🌐 Web UI

Open `http://your-slackwoot-domain.com` in a browser to see:

- **Home** — webhook URLs you need to configure, active mappings
- **Admin** (`/admin`) — live view of tracked threads, with ability to remove stale mappings

---

## 📁 Project Structure

```
slackwoot/
├── app/
│   ├── main.py              # FastAPI app & routing
│   ├── config.py            # Settings & config loading
│   ├── thread_store.py      # Conversation → Slack thread persistence
│   ├── slack_client.py      # Slack API wrapper
│   ├── chatwoot_client.py   # Chatwoot API wrapper
│   ├── routes/
│   │   ├── chatwoot.py      # Chatwoot webhook handler
│   │   ├── slack.py         # Slack Events API handler
│   │   └── admin.py         # Admin UI API routes
│   ├── templates/           # Jinja2 HTML templates
│   └── static/              # CSS/JS assets
├── data/
│   └── threads.json         # Thread mapping store (auto-created)
├── config.example.yaml
├── config.yaml              # Your config (gitignored)
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
└── run.py
```

---

## 🗺️ Roadmap

- [ ] Web UI form to add/edit inbox mappings without editing config
- [ ] SQLite/Redis option for thread store
- [ ] Slack message formatting (preserve markdown)
- [ ] Attachment forwarding (images, files)
- [ ] Multiple Chatwoot account support
- [ ] Webhook signature verification UI toggle
- [ ] Authentication for the admin dashboard

---

## 🤝 Contributing

Pull requests welcome! Please open an issue first to discuss what you'd like to change.

---

## 📄 License

MIT — use it, fork it, ship it.
