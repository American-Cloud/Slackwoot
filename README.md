# ⚡ SlackWoot

**A lightweight, open-source bridge between [Chatwoot](https://www.chatwoot.com/) and [Slack](https://slack.com/).**

SlackWoot routes Chatwoot conversations to specific Slack channels based on inbox — and lets your team reply directly from Slack threads back into Chatwoot.

---

## ✨ Features

- 📥 **Per-inbox routing** — map each Chatwoot inbox to its own Slack channel
- 🧵 **Full threading** — each conversation gets its own Slack thread
- ↩️ **Two-way replies** — reply in a Slack thread → message appears in Chatwoot
- 📎 **Attachment support** — file/image attachments shown as links in Slack
- 🔄 **Status updates** — resolved/reopened/pending posted to Slack thread
- 🛡️ **Loop prevention** — bot messages ignored; only real human Slack replies forwarded
- 📡 **Persistent activity log** — DB-backed event log survives restarts
- 🗄️ **DB-driven config** — all settings managed via UI, encrypted at rest
- 🔒 **Session auth** — cookie-based login, no passwords in config files
- 🌐 **IP whitelist** — restrict `/webhook/*` to specific IPs or CIDR ranges
- 🐳 **Docker ready** — multi-stage build, non-root user, one env var to deploy

---

## 🏗️ Project Structure

```
slackwoot/
├── src/
│   └── app/
│       ├── __init__.py
│       ├── main.py               # FastAPI app, middleware, startup validation
│       ├── config.py             # Bootstrap config (reads SECRET_KEY, DATABASE_URL, LOG_LEVEL)
│       ├── crypto.py             # Fernet encryption + bcrypt password hashing
│       ├── middleware.py         # IP whitelist + session auth middleware
│       ├── database.py           # SQLAlchemy async engine + session factory
│       ├── models.py             # ORM models: AppConfig, InboxMapping, ThreadMapping, ActivityLogEntry
│       ├── db_config.py          # Encrypted key/value config store
│       ├── db_inbox_mappings.py  # Inbox mapping CRUD
│       ├── db_thread_store.py    # Thread mapping store
│       ├── db_activity_log.py    # Activity log store
│       ├── slack_client.py       # Slack API wrapper
│       ├── chatwoot_client.py    # Chatwoot API wrapper
│       ├── routes/
│       │   ├── ui.py             # All page routes (setup, login, main, config, inbox detail)
│       │   ├── api.py            # Internal AJAX API routes (/api/*)
│       │   ├── chatwoot.py       # Chatwoot webhook handler
│       │   └── slack.py          # Slack Events API handler
│       ├── templates/            # Jinja2 HTML templates
│       │   ├── base.html
│       │   ├── setup.html        # First-run setup wizard
│       │   ├── login.html
│       │   ├── index.html        # Main page
│       │   ├── config.html       # Settings/credentials page
│       │   ├── inbox_detail.html # Per-inbox activity + threads
│       │   └── 404.html
│       └── static/               # CSS/JS assets
├── data/                         # Runtime data (auto-created, gitignored)
│   └── slackwoot.db              # SQLite database (default)
├── config.example.yaml           # Reference only — no longer used at runtime
├── pyproject.toml
├── Makefile
├── Dockerfile
├── docker-compose.yml
├── entrypoint.sh
├── requirements.txt
└── run.py
```

---

## 🚀 Quick Start

### Docker (recommended)

```bash
# 1. Clone
git clone https://github.com/your-org/slackwoot.git
cd slackwoot

# 2. Generate a secret key
openssl rand -hex 32

# 3. Set it in docker-compose.yml
#    Edit the SECRET_KEY value under environment:

# 4. Start
docker compose up -d

# 5. Open http://localhost:8000 — you'll be redirected to /setup
```

### Local development

```bash
git clone https://github.com/your-org/slackwoot.git
cd slackwoot

python -m venv .venv
source .venv/bin/activate

export SECRET_KEY=$(openssl rand -hex 32)

make run
# Open http://localhost:8000
```

---

## ⚙️ First-Run Setup

On a fresh deployment the app detects that no configuration exists and redirects to `/setup`.

The setup wizard collects:
- Chatwoot URL, API token, Account ID
- Slack bot token and signing secret
- Admin password (minimum 8 characters)

All sensitive values are **encrypted at rest** using `SECRET_KEY` before being written to the database. After setup completes you are automatically logged in and redirected to the main page.

Subsequent credential changes are made at `/config`.

---

## 🔑 Environment Variables

Only three env vars are used. Everything else is configured via the UI.

| Variable | Required | Description |
|---|---|---|
| `SECRET_KEY` | ✅ Yes | Encrypts all sensitive DB values. Generate with `openssl rand -hex 32`. **Never change after setup.** |
| `DATABASE_URL` | No | SQLAlchemy async URL. Default: `sqlite+aiosqlite:///data/slackwoot.db` |
| `LOG_LEVEL` | No | `INFO` (default), `DEBUG`, `WARNING` |

> ⚠️ If `SECRET_KEY` is lost or changed, stored credentials become unreadable and you will need to re-enter them at `/config`. Back up your `SECRET_KEY` in a secrets manager.

---

## 🐳 Docker

```bash
# Build and start
docker compose up -d

# View logs
docker compose logs -f

# Rebuild after code changes
docker compose up -d --build
```

The SQLite database is persisted in the `slackwoot_data` Docker volume.

### PostgreSQL (production)

Set `DATABASE_URL` in `docker-compose.yml` and uncomment the `postgres` service:
```yaml
DATABASE_URL: postgresql+asyncpg://slackwoot:password@postgres:5432/slackwoot
```

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
3. Slack sends a challenge — SlackWoot responds automatically
4. Subscribe to **Bot Events**: `message.channels`, `message.groups`

### 4. Install & Configure
1. **OAuth & Permissions** → Install to Workspace → copy the `xoxb-` bot token
2. **Basic Information** → App Credentials → copy the Signing Secret
3. Enter both in the SlackWoot setup wizard or `/config` page
4. Invite the bot to each mapped channel: `/invite @SlackWoot`

> **Note:** Reinstalling the Slack app regenerates the Signing Secret. Always update it in `/config` after any reinstall.

---

## 🔧 Chatwoot Setup

1. Go to **Settings → Integrations → Webhooks → Add new webhook**
2. URL: shown on the SlackWoot main page under "Chatwoot Webhook URL"
3. Enable events: `message_created`, `conversation_status_changed`
4. Save

The main page also has an **Add Mapping** button that fetches your available Chatwoot inboxes so you can pick one without leaving the browser.

---

## 🔒 Security

### Encryption at rest
All API tokens, signing secrets, and credentials are encrypted in the database using [Fernet](https://cryptography.io/en/latest/fernet/) symmetric encryption. The `SECRET_KEY` env var is the sole key — it never enters the database.

### Admin password
Stored as a bcrypt hash — never reversible even with the `SECRET_KEY`.

### Session authentication
All UI pages and `/api/*` routes require a valid signed session cookie. Sessions expire after 8 hours. Login at `/login`, logout at `/logout`.

### Webhook IP whitelist
Restrict `/webhook/chatwoot` to your Chatwoot server's IP — configurable at `/config` under "Webhook IP Whitelist" (comma-separated IPs or CIDR ranges).

### Docker
- Multi-stage build — only runtime dependencies in the final image
- Runs as non-root `slackwoot` user
- Healthcheck at `/health`

---

## 🔄 How It Works

### Chatwoot → Slack
1. Contact sends message → Chatwoot fires webhook to `/webhook/chatwoot`
2. SlackWoot looks up the Slack channel mapped to that inbox (from DB)
3. First message: rich card posted to Slack, thread `ts` saved to DB
4. Subsequent messages: posted as Slack thread replies

### Slack → Chatwoot
1. Team member replies in a Slack thread
2. SlackWoot verifies it's a real human (anti-loop checks)
3. Looks up the Chatwoot conversation for that thread in the DB
4. Posts reply as an outgoing agent message in Chatwoot

### Loop Prevention
Two layers stop echo loops when SlackWoot posts to Chatwoot:
1. Chatwoot sets `sender_type: "api"` on API-created messages — checked first
2. SlackWoot registers each posted message ID and ignores webhooks with that ID

---

## 🗄️ Database

SQLAlchemy async with SQLite (default) or PostgreSQL. Tables are created automatically on first startup.

**Tables:**
- `app_config` — encrypted key/value settings
- `inbox_mappings` — Chatwoot inbox → Slack channel mappings
- `thread_mappings` — active Chatwoot conversation ↔ Slack thread
- `activity_log` — webhook event history

---

## 🗺️ Roadmap

- [ ] Helm chart for Kubernetes deployment
- [ ] Slack message markdown formatting preservation
- [ ] True inline image forwarding (upload to Slack)
- [ ] Multiple Chatwoot account support

---

## 🤝 Contributing

PRs welcome! Please open an issue first to discuss changes.

---

## 📄 License

MIT
