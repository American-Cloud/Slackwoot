"""
UI page routes for SlackWoot.

  GET  /          — Main page: mappings overview + stats
  GET  /setup     — First-run setup wizard (only accessible when unconfigured)
  POST /setup     — Save initial config
  GET  /login     — Login page
  POST /login     — Authenticate, set session cookie
  GET  /logout    — Clear session cookie
  GET  /config    — Edit configuration (Chatwoot + Slack credentials)
  POST /config    — Save updated configuration
  GET  /inbox/{id} — Inbox detail: activity log + threads for one inbox
"""

import os
import logging
from app.main import __version__

from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.db_config import get_setting, set_setting, is_configured, verify_admin_password, get_all_settings
from app import db_inbox_mappings, db_thread_store, db_activity_log
from app.middleware import create_session_token, SESSION_COOKIE, SESSION_TTL

logger = logging.getLogger(__name__)
router = APIRouter()

_templates_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates")
templates = Jinja2Templates(directory=_templates_dir)


# ── Setup (first-run) ─────────────────────────────────────────────────────────

@router.get("/setup", response_class=HTMLResponse)
async def setup_page(request: Request, db: AsyncSession = Depends(get_db)):
    # If already configured, redirect to main page
    if await is_configured(db):
        return RedirectResponse(url="/", status_code=302)
    return templates.TemplateResponse("setup.html", {"request": request, "error": None})


@router.post("/setup", response_class=HTMLResponse)
async def setup_submit(
    request: Request,
    db: AsyncSession = Depends(get_db),
    chatwoot_base_url: str = Form(...),
    chatwoot_api_token: str = Form(...),
    chatwoot_account_id: str = Form(...),
    slack_bot_token: str = Form(...),
    slack_signing_secret: str = Form(...),
    admin_password: str = Form(...),
    admin_password_confirm: str = Form(...),
):
    if await is_configured(db):
        return RedirectResponse(url="/", status_code=302)

    error = None
    if admin_password != admin_password_confirm:
        error = "Passwords do not match."
    elif len(admin_password) < 8:
        error = "Password must be at least 8 characters."

    if error:
        return templates.TemplateResponse("setup.html", {"request": request, "error": error})

    # Save all settings to DB (crypto.py handles encryption automatically)
    await set_setting(db, "chatwoot_base_url", chatwoot_base_url.rstrip("/"))
    await set_setting(db, "chatwoot_api_token", chatwoot_api_token)
    await set_setting(db, "chatwoot_account_id", chatwoot_account_id)
    await set_setting(db, "slack_bot_token", slack_bot_token)
    await set_setting(db, "slack_signing_secret", slack_signing_secret)
    await set_setting(db, "admin_password", admin_password)  # hashed in db_config

    await db.commit()
    logger.info("Initial setup completed — configuration saved to database.")

    # Auto-login after setup
    response = RedirectResponse(url="/", status_code=302)
    token = create_session_token()
    response.set_cookie(SESSION_COOKIE, token, max_age=SESSION_TTL, httponly=True, samesite="lax")
    return response


# ── Login / Logout ────────────────────────────────────────────────────────────

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, db: AsyncSession = Depends(get_db)):
    # If not configured, redirect to setup
    if not await is_configured(db):
        return RedirectResponse(url="/setup", status_code=302)
    next_url = request.query_params.get("next", "/")
    return templates.TemplateResponse("login.html", {"request": request, "next": next_url, "error": None})


@router.post("/login", response_class=HTMLResponse)
async def login_submit(
    request: Request,
    db: AsyncSession = Depends(get_db),
    password: str = Form(...),
    next: str = Form(default="/"),
):
    if await verify_admin_password(db, password):
        response = RedirectResponse(url=next or "/", status_code=302)
        token = create_session_token()
        response.set_cookie(SESSION_COOKIE, token, max_age=SESSION_TTL, httponly=True, samesite="lax")
        return response

    return templates.TemplateResponse("login.html", {
        "request": request,
        "next": next,
        "error": "Incorrect password.",
    })


@router.get("/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie(SESSION_COOKIE)
    return response


# ── Main page ─────────────────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
async def main_page(request: Request, db: AsyncSession = Depends(get_db)):
    # First-run check
    if not await is_configured(db):
        return RedirectResponse(url="/setup", status_code=302)

    mappings = await db_inbox_mappings.get_all(db)
    thread_count = await db_thread_store.count_threads(db)
    log_count = await db_activity_log.count(db)
    chatwoot_url = await get_setting(db, "chatwoot_base_url")
    account_id = await get_setting(db, "chatwoot_account_id")

    # Build the webhook URLs to display on the main page
    base = str(request.base_url).rstrip("/")
    chatwoot_webhook_url = f"{base}/webhook/chatwoot"
    slack_events_url = f"{base}/slack/events"

    return templates.TemplateResponse("index.html", {
        "request": request,
        "mappings": [m.to_dict() for m in mappings],
        "thread_count": thread_count,
        "log_count": log_count,
        "chatwoot_url": chatwoot_url,
        "account_id": account_id,
        "chatwoot_webhook_url": chatwoot_webhook_url,
        "slack_events_url": slack_events_url,
        "version": __version__,
    })


# ── Config page ───────────────────────────────────────────────────────────────

@router.get("/config", response_class=HTMLResponse)
async def config_page(request: Request, db: AsyncSession = Depends(get_db)):
    cfg = await get_all_settings(db)
    return templates.TemplateResponse("config.html", {
        "request": request,
        "cfg": cfg,
        "saved": request.query_params.get("saved") == "1",
        "error": None,
    })


@router.post("/config/chatwoot", response_class=HTMLResponse)
async def config_chatwoot(
    request: Request,
    db: AsyncSession = Depends(get_db),
    chatwoot_base_url: str = Form(...),
    chatwoot_account_id: str = Form(...),
    chatwoot_api_token: str = Form(default=""),
):
    await set_setting(db, "chatwoot_base_url", chatwoot_base_url.rstrip("/"))
    await set_setting(db, "chatwoot_account_id", chatwoot_account_id)
    if chatwoot_api_token.strip():
        await set_setting(db, "chatwoot_api_token", chatwoot_api_token)
    logger.info("Chatwoot settings updated.")
    await db.commit()
    return RedirectResponse(url="/config?saved=1", status_code=302)


@router.post("/config/slack", response_class=HTMLResponse)
async def config_slack(
    request: Request,
    db: AsyncSession = Depends(get_db),
    slack_bot_token: str = Form(default=""),
    slack_signing_secret: str = Form(default=""),
):
    if slack_bot_token.strip():
        await set_setting(db, "slack_bot_token", slack_bot_token)
    if slack_signing_secret.strip():
        await set_setting(db, "slack_signing_secret", slack_signing_secret)
    logger.info("Slack settings updated.")
    await db.commit()
    return RedirectResponse(url="/config?saved=1", status_code=302)


@router.post("/config/security", response_class=HTMLResponse)
async def config_security(
    request: Request,
    db: AsyncSession = Depends(get_db),
    webhook_allowed_ips: str = Form(default=""),
):
    await set_setting(db, "webhook_allowed_ips", webhook_allowed_ips)
    logger.info("Security settings updated.")
    await db.commit()
    return RedirectResponse(url="/config?saved=1", status_code=302)


@router.post("/config/password", response_class=HTMLResponse)
async def config_password(
    request: Request,
    db: AsyncSession = Depends(get_db),
    new_password: str = Form(...),
    new_password_confirm: str = Form(...),
):
    if new_password != new_password_confirm:
        cfg = await get_all_settings(db)
        return templates.TemplateResponse("config.html", {
            "request": request, "cfg": cfg,
            "error": "Passwords do not match.", "saved": False,
        })
    if len(new_password) < 8:
        cfg = await get_all_settings(db)
        return templates.TemplateResponse("config.html", {
            "request": request, "cfg": cfg,
            "error": "Password must be at least 8 characters.", "saved": False,
        })
    await set_setting(db, "admin_password", new_password)
    logger.info("Admin password changed.")
    await db.commit()
    return RedirectResponse(url="/config?saved=1", status_code=302)


# ── Inbox detail page ─────────────────────────────────────────────────────────

@router.get("/inbox/{inbox_id}", response_class=HTMLResponse)
async def inbox_detail(
    request: Request,
    inbox_id: int,
    db: AsyncSession = Depends(get_db),
):
    mapping = await db_inbox_mappings.get_by_inbox_id(db, inbox_id)
    if not mapping:
        return templates.TemplateResponse("404.html", {"request": request}, status_code=404)

    chatwoot_url = await get_setting(db, "chatwoot_base_url")
    account_id = await get_setting(db, "chatwoot_account_id")

    # Fetch first page of logs and threads for this inbox on initial load
    logs = await db_activity_log.get_all(db, limit=50, inbox_id=inbox_id)
    log_count = await db_activity_log.count(db, inbox_id=inbox_id)

    return templates.TemplateResponse("inbox_detail.html", {
        "request": request,
        "mapping": mapping.to_dict(),
        "logs": logs,
        "log_count": log_count,
        "chatwoot_url": chatwoot_url,
        "account_id": account_id,
    })
