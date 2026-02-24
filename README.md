# ⚡ SlackWoot

**A lightweight, open-source bridge between [Chatwoot](https://www.chatwoot.com/) and [Slack](https://slack.com/).**

SlackWoot routes Chatwoot conversations to specific Slack channels based on inbox — and lets your team reply directly from Slack threads back into Chatwoot. No more every inbox dumping into one Slack channel.

---

## ✨ Features

- 📥 **Per-inbox routing** — map each Chatwoot inbox to its own Slack channel
- 🧵 **Full threading** — each conversation gets its own Slack thread
- ↩️ **Two-way replies** — reply in a Slack thread → message appears in Chatwoot
- 🔄 **Status updates** — resolved/reopened/pending posted to Slack thread
- 🛡️ **Loop prevention** — bot messages ignored; only real human Slack replies forwarded
- 📡 **Live activity log** — dashboard shows real-time webhook events per inbox
- 🗂 **Inbox browser** — see all your Chatwoot inboxes and IDs from the UI
- 🔒 **Basic auth** — protect the `/admin` UI with a username/password
- 🌐 **IP whitelist** — restrict `/webhook/*` to specific IPs (e.g. your Chatwoot server)
- 📖 **Read-only API docs** — Swagger UI with "Try It Out" disabled; ReDoc also available
- ⚙️ **Config-first** — `config.yaml` or environment variables
- 🐳 **Docker ready** — one-command deploy

---

## 🏗️ Project Structure

```
slackwoot/
├── src/
│   └── app/
│       ├── __init__.py
│       ├── main.py              # FastAPI app, middleware registration, docs
│       ├── config.py            # Settings & config loading
│       ├── middleware.py        # IP whitelist + Basic auth middleware
│       ├── thread_store.py      # Conversation → Slack thread persistence
│       ├── activity_log.py      # In-memory activity log for UI
│       ├── slack_client.py      # Slack API wrapper
│       ├── chatwoot_client.py   # Chatwoot API wrapper
│       ├── routes/
│       │   ├── chatwoot.py      # Chatwoot webhook handler
│       │   ├── slack.py         # Slack Events API handler
│       │   └── admin.py         # Admin UI + API routes
│       ├── templates/           # Jinja2 HTML templates
│       │   ├── base.html
│       │   ├── index.html
│       │   └── admin.html
│       └── static/              # CSS/JS assets
├── data/
│   └── threads.json             # Thread mapping store (auto-created)
├── config.example.yaml
├── config.yaml                  # Your config (gitignored)
├── pyproject.toml
├── Makefile
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
└── run.py
```

---

## 🚀 Quick Start

```bash
# 1. Clone
git clone https://github.com/your-org/slackwoot.git
cd slackwoot

# 2. Create virtualenv
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# 3. Copy and edit config
cp config.example.yaml config.yaml
nano config.yaml

# 4. Install and run
make run       # production (no reload)
make dev       # same, alias for development
```

The app runs at `http://localhost:8000`.

---

## ⚙️ Configuration Reference

All values can be set in `config.yaml` **or** as environment variables.

| config.yaml key / Env Var | Description |
|---|---|
| `CHATWOOT_BASE_URL` | Your Chatwoot instance URL |
| `CHATWOOT_API_TOKEN` | User access token (Settings → Profile → Access Token) |
| `CHATWOOT_ACCOUNT_ID` | Numeric account ID (visible in URL when logged in) |
| `CHATWOOT_WEBHOOK_SECRET` | Optional HMAC secret (reserved for future Chatwoot support) |
| `SLACK_BOT_TOKEN` | Bot token starting with `xoxb-` |
| `SLACK_SIGNING_SECRET` | From Slack App → Basic Information |
| `ADMIN_USERNAME` | Basic auth username for `/admin` — leave blank to disable |
| `ADMIN_PASSWORD` | Basic auth password for `/admin` |
| `WEBHOOK_ALLOWED_IPS` | Comma-separated IPs/CIDRs allowed to call `/webhook/*` |
| `LOG_LEVEL` | `INFO` (default), `DEBUG`, `WARNING` |
| `THREAD_STORE_PATH` | Path to thread JSON file (default: `data/threads.json`) |

### Multiple mappings via environment variables

```bash
SLACKWOOT_MAPPING_1=inbox_id:4,inbox_name:Website,slack_channel:#support-web,slack_channel_id:C0AHGAWTHFA
SLACKWOOT_MAPPING_2=inbox_id:1,inbox_name:Email,slack_channel:#support-email,slack_channel_id:C0AHGGDJHGQ
```

---

## 🔧 Chatwoot Setup

1. Go to **Settings → Integrations → Webhooks → Add new webhook**
2. URL: `https://your-slackwoot-domain.com/webhook/chatwoot`
3. Enable events: `message_created`, `conversation_status_changed`
4. Save

> **Tip:** Visit `/admin` and click **Load Inboxes** to see all your inbox IDs without leaving the browser.

> **IP Whitelist:** To restrict the webhook to only your Chatwoot server, add its IP to `webhook_allowed_ips` in `config.yaml`.

---

## 💬 Slack App Setup

### 1. Create a Slack App

Go to [api.slack.com/apps](https://api.slack.com/apps) → **Create New App** → **From scratch**

### 2. OAuth & Permissions — Bot Token Scopes

| Scope | Purpose |
|---|---|
| `chat:write` | Post messages |
| `chat:write.customize` | Custom username/emoji per message |
| `channels:history` | Read channel history |
| `groups:history` | Read private channel history |
| `users:read` | Look up user info (loop prevention) |

### 3. Event Subscriptions

1. Enable Events
2. Request URL: `https://your-slackwoot-domain.com/slack/events`
3. Slack will send a challenge — SlackWoot responds automatically
4. Subscribe to **Bot Events**: `message.channels`, `message.groups`

### 4. Install & Configure

1. **OAuth & Permissions** → Install to Workspace → copy the `xoxb-` token
2. Add token and signing secret to `config.yaml`
3. Invite the bot to each mapped channel: `/invite @SlackWoot`

---

## 🔒 Security

### Admin Basic Auth
Set `admin_username` and `admin_password` in `config.yaml`. The browser will prompt for credentials when accessing `/admin`. Leave blank to disable (open access).

### Webhook IP Whitelist
Restrict `/webhook/chatwoot` to your Chatwoot server's IP:
```yaml
webhook_allowed_ips:
  - "1.2.3.4"        # Your Chatwoot server IP
  - "10.0.0.0/8"     # Or a CIDR range
```
Leave empty to allow all IPs. The signing secret field is also available for future use when Chatwoot adds HMAC support.

### API Docs
- `/docs` — Swagger UI with **Try It Out disabled**
- `/redoc` — Read-only ReDoc

---

## 🔄 How It Works

### Chatwoot → Slack
1. Contact sends a message → Chatwoot fires webhook to SlackWoot
2. SlackWoot looks up the Slack channel mapped to that inbox
3. First message: rich card posted to Slack, thread `ts` saved
4. Subsequent messages: posted as thread replies

### Slack → Chatwoot
1. Team member replies in a Slack thread
2. SlackWoot verifies it's a real human (not a bot — loop prevention)
3. Looks up the Chatwoot conversation for that thread
4. Posts reply as an outgoing agent message in Chatwoot

### Status Changes
Resolved/reopened/pending status changes in Chatwoot are posted to the existing Slack thread automatically.

---

## 🗺️ Roadmap

- [ ] Web UI form to add/edit inbox mappings without editing config
- [ ] SQLite/Redis option for persistent activity log
- [ ] Slack message formatting (preserve markdown)
- [ ] Attachment forwarding (images, files)
- [ ] SSO / multi-user admin authentication

---

## 🤝 Contributing

PRs welcome! Please open an issue first to discuss changes.

---

## 📄 License

MIT
