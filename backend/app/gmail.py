"""Send email from the user's own Gmail through the official Gmail API (HTTPS, not SMTP).

Setup once (see README): a Google Cloud OAuth client + `python -m app.gmail_auth`, which
prints a refresh token for GMAIL_REFRESH_TOKEN. Only the `gmail.send` scope is requested:
JobPilot can send mail as you but cannot read your inbox.
"""
from __future__ import annotations

import base64
import re
import time
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

import httpx

from .config import settings

TOKEN_URL = "https://oauth2.googleapis.com/token"
SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
PROFILE_URL = "https://gmail.googleapis.com/gmail/v1/users/me/profile"
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+'-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")

_cache: dict = {"token": None, "exp": 0.0, "address": None}


class GmailError(RuntimeError):
    pass


def configured() -> bool:
    return settings.gmail_mock or bool(settings.google_client_id and settings.google_client_secret
                                       and settings.gmail_refresh_token)


async def _access_token(client: httpx.AsyncClient) -> str:
    if _cache["token"] and time.time() < _cache["exp"] - 60:
        return _cache["token"]
    r = await client.post(TOKEN_URL, data={
        "client_id": settings.google_client_id, "client_secret": settings.google_client_secret,
        "refresh_token": settings.gmail_refresh_token, "grant_type": "refresh_token"})
    if r.status_code != 200:
        raise GmailError("Gmail sign-in expired or was revoked. Run `python -m app.gmail_auth` again "
                         "and update GMAIL_REFRESH_TOKEN.")
    data = r.json()
    _cache.update(token=data["access_token"], exp=time.time() + int(data.get("expires_in", 3600)))
    return _cache["token"]


async def sender_address(client: httpx.AsyncClient | None = None) -> str | None:
    if settings.gmail_mock:
        return "you@example.com"
    if not configured():
        return None
    if _cache["address"]:
        return _cache["address"]
    own = client is None
    client = client or httpx.AsyncClient(timeout=20)
    try:
        r = await client.get(PROFILE_URL, headers={"Authorization": f"Bearer {await _access_token(client)}"})
        _cache["address"] = r.json().get("emailAddress") if r.status_code == 200 else None
        return _cache["address"]
    except GmailError:
        return None
    finally:
        if own:
            await client.aclose()


def build_message(sender: str, to: str, subject: str, body: str,
                  attachment: bytes | None, filename: str) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = formataddr((settings.gmail_sender_name, sender)) if settings.gmail_sender_name else sender
    msg["To"] = to
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid(domain=sender.split("@")[-1])
    msg.set_content(body)
    if attachment:
        msg.add_attachment(attachment, maintype="application", subtype="pdf", filename=filename)
    return msg


async def send(to: str, subject: str, body: str, attachment: bytes | None, filename: str,
               client: httpx.AsyncClient | None = None) -> dict:
    to, subject = to.strip(), subject.strip()
    if not EMAIL_RE.match(to):
        raise GmailError(f"'{to}' is not a valid email address.")
    if not subject or not body.strip():
        raise GmailError("Subject and message can't be empty.")
    if "\n" in subject or "\r" in subject:
        raise GmailError("Subject must be one line.")
    if settings.gmail_mock:
        return {"id": "mock-" + str(int(time.time())), "to": to, "mock": True}
    if not configured():
        raise GmailError("Gmail isn't connected. Set GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET and "
                         "GMAIL_REFRESH_TOKEN in Render (see README).")
    own = client is None
    client = client or httpx.AsyncClient(timeout=30)
    try:
        sender = await sender_address(client) or "me"
        raw = build_message(sender, to, subject, body, attachment, filename).as_bytes()
        r = await client.post(SEND_URL, headers={"Authorization": f"Bearer {await _access_token(client)}"},
                              json={"raw": base64.urlsafe_b64encode(raw).decode()})
        if r.status_code != 200:
            raise GmailError(f"Gmail refused the message ({r.status_code}): {r.text[:200]}")
        return {"id": r.json().get("id"), "to": to}
    finally:
        if own:
            await client.aclose()
