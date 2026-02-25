# ⚡ SlackWoot

**A lightweight, open-source bridge between [Chatwoot](https://www.chatwoot.com/) and [Slack](https://slack.com/).**

SlackWoot routes Chatwoot conversations to specific Slack channels based on inbox — and lets your team reply directly from Slack threads back into Chatwoot. No more every inbox dumping into one Slack channel.

---

## ✨ Features

- 📥 **Per-inbox routing** — map each Chatwoot inbox to its own Slack channel
- 🧵 **Full threading** — each conversation gets its own Slack thread
- ↩️ **Two-way replies** — reply in a Slack thread → message appears in Chatwoot
- 📎 **Attachment support** — file/image attachments shown as links in Slack
- 🔄 **Status updates** — resolved/reopened/pending posted to Slack thread
- 🛡️ **Loop prevention** — bot messages ignored; only real human Slack replies forwarded
- 📡 **Persistent activity log** — DB-backed event log survives restarts
- 🗂 **Inbox browser** — see all Chatwoot inboxes and IDs from the UI
- 🔒 **Basic auth** — protect the `/admin` UI with a username/password
- 🌐 **IP whitelist** — restrict `/webhook/*` to specific IPs or CIDR ranges
- 📖 **Read-only API docs** — Swagger UI with "Try It Out" disabled; ReDoc also available
- 🗄️ **SQLite or PostgreSQL** — SQLite for dev/single-host, Postgres for production/K8s
- ⚙️ **Config-first** — `config.yaml` or environment variables
- 🐳 **Docker ready** — multi-stage build, non-root user, healthcheck included

---

## 🏗️ Project Structure

```
slackwoot/
├── src/
│   └── app/
│       ├── __init__.py
│       ├── main.py              # FastAPI app, middleware, docs setup
│       ├── config.py            # Settings loader (YAML + env vars)
│       ├── middleware.py        # IP whitelist + Basic auth middleware
│       ├── database.py          # SQLAlchemy async engine + session factory
│       ├── models.py            # ORM models: ThreadMapping, ActivityLogEntry
│       ├── db_thread_store.py   # DB-backed thread store
│       ├── db_activity_log.py   # DB-backed activity log
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
├── data/                        # Runtime data (auto-created, gitignored)
│   └── slackwoot.db             # SQLite database (default)
├── config.example.yaml
├── config.yaml                  # Your config (gitignored)
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

```bash
# 1. Clone
git clone https://github.com/your-org/slackwoot.git
cd slackwoot

# 2. Create and activate a virtualenv
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# 3. Copy and edit config
cp config.example.yaml config.yaml
nano config.yaml

# 4. Install dependencies and start
make run
```

The app runs at `http://localhost:8000`. The database is created automatically on first startup at `data/slackwoot.db`.

### Makefile targets

| Command | Description |
|---|---|
| `make install` | Install Python dependencies via `pip install -e .` |
| `make run` | Install deps and start the server |
| `make dev` | Same as `make run` (alias for development) |

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

The SQLite database is persisted in a named Docker volume (`slackwoot_data`) and is created automatically on first startup.

### PostgreSQL (production)

Uncomment the `postgres` service in `docker-compose.yml` and set:
```yaml
environment:
  DATABASE_URL: postgresql+asyncpg://slackwoot:password@postgres:5432/slackwoot
```

---

## ⚙️ Configuration Reference

All values can be set in `config.yaml` **or** as environment variables.

| config.yaml key | Env Var | Description |
|---|---|---|
| `chatwoot_base_url` | `CHATWOOT_BASE_URL` | Your Chatwoot instance URL |
| `chatwoot_api_token` | `CHATWOOT_API_TOKEN` | User access token (Profile → Access Token) |
| `chatwoot_account_id` | `CHATWOOT_ACCOUNT_ID` | Numeric account ID (visible in URL) |
| `chatwoot_webhook_secret` | `CHATWOOT_WEBHOOK_SECRET` | Reserved for future HMAC signing support |
| `slack_bot_token` | `SLACK_BOT_TOKEN` | Bot token starting with `xoxb-` |
| `slack_signing_secret` | `SLACK_SIGNING_SECRET` | From Slack App → Basic Information |
| `admin_username` | `ADMIN_USERNAME` | Basic auth username for `/admin` (blank = disabled) |
| `admin_password` | `ADMIN_PASSWORD` | Basic auth password for `/admin` |
| `webhook_allowed_ips` | `WEBHOOK_ALLOWED_IPS` | Comma-separated IPs/CIDRs for `/webhook/*` |
| `database_url` | `DATABASE_URL` | SQLAlchemy DB URL (default: SQLite) |
| `log_level` | `LOG_LEVEL` | `INFO` (default), `DEBUG`, `WARNING` |

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

> **IP Whitelist:** Add your Chatwoot server's IP to `webhook_allowed_ips` in `config.yaml` to restrict webhook access.

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
2. **Basic Information** → App Credentials → copy the Signing Secret
3. Add both to `config.yaml`
4. Invite the bot to each mapped channel: `/invite @SlackWoot`

> **Note:** Reinstalling the Slack app regenerates the Signing Secret. Always grab it fresh after any reinstall.

---

## 🔒 Security

### Admin Basic Auth
Set `admin_username` and `admin_password` in `config.yaml`. The browser prompts for credentials when accessing `/admin`. Leave blank to disable.

### Webhook IP Whitelist
Restrict `/webhook/chatwoot` to your Chatwoot server's IP:
```yaml
webhook_allowed_ips:
  - "1.2.3.4"        # Your Chatwoot server IP
  - "10.0.0.0/8"     # Or a CIDR range
```

### API Docs
- `/docs` — Swagger UI with **Try It Out disabled**
- `/redoc` — Read-only ReDoc

### Docker Security
- Multi-stage build — only runtime dependencies in the final image
- Runs as a non-root `slackwoot` user
- Config mounted read-only
- Healthcheck endpoint at `/health`

---

## 🔄 How It Works

### Chatwoot → Slack
1. Contact sends a message → Chatwoot fires webhook to SlackWoot
2. SlackWoot looks up the Slack channel mapped to that inbox
3. First message: rich card posted to Slack, thread `ts` saved to DB
4. Subsequent messages: posted as thread replies

### Slack → Chatwoot
1. Team member replies in a Slack thread
2. SlackWoot verifies it's a real human (not a bot — loop prevention)
3. Looks up the Chatwoot conversation for that thread in the DB
4. Posts reply as an outgoing agent message in Chatwoot

### Loop Prevention
When SlackWoot posts to Chatwoot via API, Chatwoot fires a webhook back. This is stopped by two layers:
1. Chatwoot sets `sender_type: "api"` on messages created via API — SlackWoot checks this first
2. SlackWoot registers each message ID it creates and ignores any webhook with that ID

---

## 🗄️ Database

SlackWoot uses SQLAlchemy async. The database is created automatically on first startup — no manual migration steps required.

**Default (SQLite):** Zero-config, file at `data/slackwoot.db`. Good for single-host deployments and development.

**Production (PostgreSQL):**
```yaml
database_url: "postgresql+asyncpg://user:password@host:5432/slackwoot"
```

Tables are created automatically on startup if they don't exist. If you ever need schema migrations in the future (adding columns after upgrading), Alembic can be added at that point.

---

## 🗺️ Roadmap

- [ ] Helm chart for Kubernetes deployment
- [ ] Web UI form to add/edit inbox mappings without editing config
- [ ] Slack message markdown formatting preservation
- [ ] True inline image forwarding (upload to Slack)
- [ ] Multiple Chatwoot account support
- [ ] SSO / OAuth for admin UI

---

## 🤝 Contributing

PRs welcome! Please open an issue first to discuss changes.

---

## 📄 License

MIT
