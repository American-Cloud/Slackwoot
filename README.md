# ⚡ SlackWoot

**A lightweight, open-source bridge between [Chatwoot](https://www.chatwoot.com/) and [Slack](https://slack.com/).**

SlackWoot routes Chatwoot conversations to specific Slack channels based on inbox — and lets your team reply directly from Slack threads back into Chatwoot.

> ⚠️ **Early Development**
> SlackWoot is under active development and may contain bugs. It is functional and in use, but APIs, config structure, and DB schema may change between versions without a formal migration path. Use in production at your own discretion — feedback and bug reports are welcome.

---

## 🤔 Why SlackWoot?

You could wire this up in n8n, Zapier, or Make. Most people who try quickly run into the same wall: getting a message *into* Slack is easy — getting a reply *back* into the right Chatwoot conversation, threaded correctly, without echo loops, is the part that requires real state management. General-purpose automation tools don't know enough about Chatwoot's data model to handle it cleanly without a lot of custom logic on your end.

SlackWoot is purpose-built for this one job.

**No per-message cost.** n8n Cloud, Zapier, and Make all charge by operation volume. A busy support team burns through a free tier fast. SlackWoot is self-hosted with no usage fees — run it alongside your existing Chatwoot instance.

**Slack threads are first-class.** Each Chatwoot conversation maps to exactly one Slack thread, automatically. Replies in that thread route back to the right conversation without any workflow configuration or conversation ID lookups.

**Your data stays in your infrastructure.** Chatwoot credentials, Slack tokens, and conversation data never pass through a third-party automation platform. Everything is encrypted at rest in your own database.

**It knows when to stay quiet.** Bot message filtering, loop prevention, per-inbox pause, and inactive mapping detection are all built in. These edge cases require custom logic in a general-purpose tool — here they're handled by default.

**Zero ongoing maintenance.** No workflow canvas to keep updated, no credentials to re-authenticate every 30 days, no nodes to fix when an API changes. Configure it once through the web UI and it runs.

The honest take: if your entire use case is Chatwoot ↔ Slack, SlackWoot does it better out of the box. If you need Chatwoot connected to ten other services, use n8n.

---

## ✨ Features

- 📥 **Per-inbox routing** — map each Chatwoot inbox to its own Slack channel
- 🧵 **Full threading** — each conversation gets its own Slack thread
- ↩️ **Two-way replies** — reply in a Slack thread → message appears in Chatwoot
- 📎 **Attachment support** — file/image attachments shown as links in Slack
- 🔄 **Status updates** — resolved/reopened/pending posted to Slack thread
- 🛡️ **Loop prevention** — bot messages ignored; only real human Slack replies forwarded
- ⏸️ **Pause per inbox** — disable a mapping without deleting it; blocks both directions
- 📡 **Persistent activity log** — DB-backed event log with per-inbox drill-down
- 🗄️ **DB-driven config** — all settings managed via UI, encrypted at rest
- 🔒 **Session auth** — cookie-based login protects all UI and API routes
- 🌐 **Webhook IP whitelist** — restrict `/webhook/chatwoot` to your Chatwoot server IP
- 🐳 **Docker ready** — multi-stage build, non-root user, one env var to deploy

---

## 📸 Screenshots

![Main Page](screenshots/main.png)

<details>
<summary>More screenshots</summary>

### Inbox Detail
![Inbox Detail](screenshots/inbox_detail.png)

### Config Page
![Config](screenshots/config.png)

### First-Run Setup
![Setup Wizard](screenshots/setup.png)

</details>

---

## 🏗️ Project Structure

```
slackwoot/
├── src/
│   └── app/
│       ├── __init__.py
│       ├── main.py               # FastAPI app, middleware registration, exception handlers
│       ├── config.py             # Bootstrap config (SECRET_KEY, DATABASE_URL, LOG_LEVEL env vars)
│       ├── crypto.py             # Fernet encryption + bcrypt password hashing
│       ├── middleware.py         # SessionAuthMiddleware + IPWhitelistMiddleware
│       ├── database.py           # SQLAlchemy async engine + session factory
│       ├── models.py             # ORM models: AppConfig, InboxMapping, ThreadMapping, ActivityLogEntry
│       ├── db_config.py          # Encrypted key/value config store
│       ├── db_inbox_mappings.py  # Inbox mapping CRUD
│       ├── db_thread_store.py    # Thread mapping store
│       ├── db_activity_log.py    # Activity log store (capped at 10,000 rows)
│       ├── slack_client.py       # Slack API wrapper (reads token from DB)
│       ├── chatwoot_client.py    # Chatwoot API wrapper (reads credentials from DB)
│       ├── routes/
│       │   ├── ui.py             # Page routes: setup, login, logout, main, config, inbox detail
│       │   ├── api.py            # AJAX API routes (/api/*) — session auth required
│       │   ├── chatwoot.py       # Chatwoot webhook handler (/webhook/chatwoot)
│       │   └── slack.py          # Slack Events API handler (/slack/events)
│       └── templates/
│           ├── base.html         # Shared layout, nav, CSS, alert auto-dismiss
│           ├── setup.html        # First-run setup wizard
│           ├── login.html        # Login page
│           ├── index.html        # Main page — unified inbox/mapping table + activity log
│           ├── config.html       # Settings: Chatwoot, Slack, Security, Password (separate forms)
│           ├── inbox_detail.html # Per-inbox thread mappings + activity log
│           └── 404.html          # Custom not-found page
├── screenshots/                  # Drop PNGs here for README screenshots
├── data/                         # Runtime data (auto-created, gitignored)
│   └── slackwoot.db              # SQLite database (default)
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
git clone https://github.com/CodeBleu/slackwoot.git
cd slackwoot

# 2. Generate a secret key
openssl rand -hex 32

# 3. Set it in docker-compose.yml under environment: SECRET_KEY

# 4. Start
docker compose up -d

# 5. Open http://localhost:8000 — redirects to /setup on first run
```

### Local development

```bash
git clone https://github.com/CodeBleu/slackwoot.git
cd slackwoot

python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

export SECRET_KEY=$(openssl rand -hex 32)

make run
# Open http://localhost:8000
```

---

## ⚙️ First-Run Setup

On a fresh deployment the app detects no configuration exists and redirects to `/setup`.

The setup wizard collects:
- Chatwoot URL, API token, Account ID
- Slack bot token and signing secret
- Admin password (minimum 8 characters)

All sensitive values are **encrypted at rest** using `SECRET_KEY` before being written to the database. After setup completes you are automatically logged in and redirected to the main page.

Subsequent changes are made at `/config`.

---

## 🔑 Environment Variables

Only three env vars are needed at deploy time. Everything else is configured through the UI.

| Variable | Required | Description |
|---|---|---|
| `SECRET_KEY` | ✅ Yes | Encrypts all sensitive DB values. Generate with `openssl rand -hex 32`. **Never change after setup.** |
| `DATABASE_URL` | No | SQLAlchemy async URL. Default: `sqlite+aiosqlite:///data/slackwoot.db` |
| `LOG_LEVEL` | No | `INFO` (default), `DEBUG`, `WARNING`, `ERROR` — set in docker-compose env, not the UI |

> ⚠️ If `SECRET_KEY` is lost or changed, stored credentials become unreadable and must be re-entered at `/config`. Back it up in a secrets manager.

---

## 🐳 Docker

```bash
# Build and start
docker compose up -d

# View logs
docker compose logs -f

# Rebuild after code changes
docker compose up -d --build

# Temporarily enable debug logging without changing code
# Edit docker-compose.yml: LOG_LEVEL: DEBUG
docker compose up -d
```

The SQLite database is persisted in the `slackwoot_data` Docker volume.

### PostgreSQL (production)

Set `DATABASE_URL` in `docker-compose.yml` and uncomment the `postgres` service:
```yaml
DATABASE_URL: postgresql+asyncpg://slackwoot:password@postgres:5432/slackwoot
```

---

## 🖥️ Using the UI

### Main page (`/`)
- **Stat tiles** — live counts of mappings, tracked threads, and activity events
- **Webhook URLs** — copy/paste into Chatwoot and Slack app settings
- **Unified Inbox Table** — all Chatwoot inboxes in one view; mapped ones show their Slack channel with Edit/Pause/Delete; unmapped ones show a `+ Map` button to configure inline
- **Activity Log** — paginated, filterable event log; auto-refreshes every 5 seconds

### Inbox detail (`/inbox/{id}`)
- Per-inbox view of active thread mappings and activity log
- Delete individual thread mappings to force new conversations to open a fresh Slack thread
- Activity log filtered to that inbox — shows `message_created`, `slack_reply`, and `status_changed` events

### Config page (`/config`)
Four independent sections, each with its own Save button — change one thing without touching others:
- **Chatwoot** — URL, Account ID, API token (leave token blank to keep current)
- **Slack** — Bot token, Signing secret (leave blank to keep current)
- **Security** — Webhook IP whitelist for `/webhook/chatwoot`
- **Password** — Change admin password

All secret fields have a show/hide toggle (👁). Success alerts auto-dismiss after 4 seconds.

### Pausing a mapping
Clicking **Pause** disables the mapping in both directions:
- Incoming Chatwoot messages for that inbox are logged as `ignored`
- Slack replies to existing threads for that inbox are dropped and logged as `ignored` with the attempted message text

Click **Enable** to resume.

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

---

## 🔒 Security

### Encryption at rest
All API tokens, signing secrets, and credentials are encrypted using [Fernet](https://cryptography.io/en/latest/fernet/) symmetric encryption. `SECRET_KEY` is the sole encryption key — it never enters the database.

### Admin password
Stored as a bcrypt hash — never reversible even with `SECRET_KEY`.

### Session authentication
`SessionAuthMiddleware` protects **all** routes except `/setup`, `/login`, `/health`, and the webhook endpoints. Sessions expire after 8 hours and use HMAC-signed cookies.

- Browser requests without a session → redirect to `/login`
- AJAX `/api/*` requests without a session → `401 JSON`
- `/docs` and `/redoc` are also behind auth — no API surface exposed to unauthenticated users

### Webhook IP whitelist
Optionally restrict `/webhook/chatwoot` to your Chatwoot server's IP — configurable in `/config` → Security. Since Chatwoot does not currently send HMAC signatures on webhooks, the IP whitelist is the primary protection for that endpoint.

`/slack/events` is protected by Slack's HMAC signing secret verification — no IP whitelist needed since Slack sends from a broad, changing range of IPs.

### Docker
- Multi-stage build — only runtime dependencies in the final image
- Runs as non-root `slackwoot` user
- Healthcheck at `/health`

---

## 🔄 How It Works

### Chatwoot → Slack
1. Contact sends message → Chatwoot fires webhook to `/webhook/chatwoot`
2. SlackWoot checks if the inbox has an active mapping
3. Content is extracted from `processed_message_content` (plain text) — falls back to stripping HTML tags from `content` for compatibility with Chatwoot 4.11+ rich text editor
4. First message: rich card posted to Slack, thread `ts` saved to DB
5. Subsequent messages: posted as Slack thread replies

### Slack → Chatwoot
1. Team member replies in a Slack thread
2. SlackWoot verifies the user is a real human (anti-loop checks)
3. Looks up the Chatwoot conversation and inbox mapping for that thread
4. Checks the mapping is still active — drops the reply if paused
5. Posts reply as an outgoing agent message in Chatwoot

### Loop Prevention
Two layers stop echo loops:
1. Chatwoot sets `sender_type: "api"` on API-created messages — checked first
2. SlackWoot tracks each posted message ID and ignores webhooks with that ID

---

## 🗄️ Database

SQLAlchemy async with SQLite (default) or PostgreSQL. Tables are created automatically on startup — no migration steps required.

| Table | Purpose |
|---|---|
| `app_config` | Encrypted key/value settings |
| `inbox_mappings` | Chatwoot inbox → Slack channel mappings (with active flag) |
| `thread_mappings` | Chatwoot conversation ↔ Slack thread (with inbox_id) |
| `activity_log` | Webhook event history — auto-pruned at 10,000 rows |

---

## 🧪 Tested On

| Component | Version | Status |
|---|---|---|
| Chatwoot | 4.8.0 | ✅ Tested |
| Chatwoot | 4.11.1 | ✅ Tested — HTML stripping handles rich text editor output |

> If you test on a version not listed here, please open an issue or PR to update this table.

---

## 🗺️ Roadmap

- [ ] Configurable pagination size for activity log and thread mapping tables
- [ ] Multi-user support — admin and read-only roles
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
