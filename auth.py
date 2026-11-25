"""
Email-OTP login gate for Streamlit, restricted to an allowed set of email domains.

Drop this file into your Streamlit repo and call `require_auth()` at the very
top of your main script (before you render any real page content). It blocks
execution (via st.stop()) until the visitor has verified a 10-minute code sent
to an address on an allowed domain.

    import auth
    auth.require_auth()
    # ... rest of your app, only reached once logged in ...

Design notes / limitations (read before relying on this for anything sensitive):

- Codes are stored in an in-process dict (`_CODE_STORE`). That's fine for a
  single small Streamlit instance, but it is NOT shared across multiple
  server processes/replicas, and it is wiped whenever the app process
  restarts (e.g. Streamlit Community Cloud puts idle apps to sleep and
  restarts them on the next visit). For an internal tool with light,
  bursty usage this is usually fine -- worst case someone's code goes stale
  and they just request a new one. If you need it to survive restarts /
  scale to multiple instances, swap `_CODE_STORE` for a small SQLite table
  or a Redis/Upstash instance (a few lines to change, flagged below).

- This file gates the *UI*. If your data also needs an API, gate that
  separately -- don't assume the Streamlit session check alone protects
  anything reachable by a direct HTTP request.

- You must configure an SMTP account in `.streamlit/secrets.toml` (see
  secrets.toml.example in this folder). Any SMTP-capable mailbox works,
  including a Microsoft 365 / Google Workspace account with SMTP AUTH
  enabled and an app password.
"""

from __future__ import annotations

import re
import secrets
import smtplib
import ssl
import time
from dataclasses import dataclass
from email.message import EmailMessage

import streamlit as st

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

ALLOWED_DOMAINS = {
    "omnidian.com.au",
    "omnidian.com",
    "solarserviceguys.com.au",
}

CODE_LENGTH = 6
CODE_TTL_SECONDS = 10 * 60          # 10 minutes
RESEND_COOLDOWN_SECONDS = 60        # don't let someone spam "send code"
MAX_VERIFY_ATTEMPTS = 5             # per code, before it's invalidated
SESSION_HOURS = 12                  # how long a verified login lasts in-browser

APP_NAME = "LG RMA"

EMAIL_RE = re.compile(r"^[^@\s]+@([^@\s]+)$")


# ---------------------------------------------------------------------------
# Code store (swap this out for SQLite/Redis if you need persistence across
# restarts or multiple instances -- see module docstring).
# ---------------------------------------------------------------------------

@dataclass
class _Code:
    code: str
    expires_at: float
    attempts: int = 0
    last_sent_at: float = 0.0


_CODE_STORE: dict[str, _Code] = {}


def _domain_of(email: str) -> str | None:
    m = EMAIL_RE.match(email.strip().lower())
    return m.group(1) if m else None


def _is_allowed_email(email: str) -> bool:
    domain = _domain_of(email)
    return domain in ALLOWED_DOMAINS if domain else False


def _generate_code() -> str:
    return "".join(secrets.choice("0123456789") for _ in range(CODE_LENGTH))


def _send_email(to_email: str, code: str) -> None:
    """Send the code via SMTP using credentials from st.secrets.

    Expects a [smtp] table in .streamlit/secrets.toml -- see
    secrets.toml.example. Raises on failure so the caller can show an error
    instead of silently pretending the email went out.
    """
    cfg = st.secrets["smtp"]
    msg = EmailMessage()
    msg["Subject"] = f"Your {APP_NAME} verification code"
    msg["From"] = cfg["from_address"]
    msg["To"] = to_email
    msg.set_content(
        f"Your {APP_NAME} verification code is: {code}\n\n"
        f"This code expires in {CODE_TTL_SECONDS // 60} minutes. "
        "If you didn't request this, you can ignore this email."
    )

    context = ssl.create_default_context()
    with smtplib.SMTP(cfg["host"], int(cfg.get("port", 587))) as server:
        server.starttls(context=context)
        server.login(cfg["username"], cfg["password"])
        server.send_message(msg)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def require_auth() -> str:
    """Render a login gate if needed and halt the script until verified.

    Returns the verified email address once logged in (so the rest of your
    app can use it, e.g. for an audit log of who looked something up).
    """
    if st.session_state.get("auth_email") and st.session_state.get(
        "auth_expires_at", 0
    ) > time.time():
        return st.session_state["auth_email"]

    # Expired or never logged in -- clear stale session state and show the gate.
    st.session_state.pop("auth_email", None)
    st.session_state.pop("auth_expires_at", None)

    _render_login_gate()
    st.stop()  # never reached once logged in; halts the rest of the script


def _render_login_gate() -> None:
    st.title(f"🔒 {APP_NAME} login")
    st.caption(
        "Access is limited to omnidian.com.au, omnidian.com and "
        "solarserviceguys.com.au email addresses."
    )

    stage = st.session_state.get("auth_stage", "request")

    if stage == "request":
        email = st.text_input("Work email address", key="auth_email_input")
        if st.button("Send verification code", type="primary"):
            email = (email or "").strip().lower()
            if not _is_allowed_email(email):
                st.error(
                    "That email domain isn't allowed. Use an omnidian.com.au, "
                    "omnidian.com or solarserviceguys.com.au address."
                )
                return

            existing = _CODE_STORE.get(email)
            now = time.time()
            if existing and now - existing.last_sent_at < RESEND_COOLDOWN_SECONDS:
                wait = int(RESEND_COOLDOWN_SECONDS - (now - existing.last_sent_at))
                st.warning(f"A code was just sent. Try again in {wait}s.")
                return

            code = _generate_code()
            _CODE_STORE[email] = _Code(
                code=code, expires_at=now + CODE_TTL_SECONDS, last_sent_at=now
            )
            try:
                _send_email(email, code)
            except Exception as exc:  # noqa: BLE001 -- show the real error to the admin
                st.error(f"Couldn't send the email: {exc}")
                return

            st.session_state["auth_stage"] = "verify"
            st.session_state["auth_pending_email"] = email
            st.rerun()

    elif stage == "verify":
        email = st.session_state.get("auth_pending_email", "")
        st.info(f"Enter the code sent to {email}. It expires in 10 minutes.")
        code_input = st.text_input("Verification code", max_chars=CODE_LENGTH)

        col1, col2 = st.columns(2)
        with col1:
            verify_clicked = st.button("Verify", type="primary")
        with col2:
            resend_clicked = st.button("Use a different email / resend")

        if resend_clicked:
            st.session_state["auth_stage"] = "request"
            st.rerun()

        if verify_clicked:
            record = _CODE_STORE.get(email)
            now = time.time()
            if not record or now > record.expires_at:
                st.error("That code has expired. Request a new one.")
                st.session_state["auth_stage"] = "request"
                return

            record.attempts += 1
            if secrets.compare_digest(code_input.strip(), record.code):
                del _CODE_STORE[email]  # single-use
                st.session_state["auth_email"] = email
                st.session_state["auth_expires_at"] = now + SESSION_HOURS * 3600
                st.session_state["auth_stage"] = "request"
                st.rerun()
            else:
                remaining = MAX_VERIFY_ATTEMPTS - record.attempts
                if remaining <= 0:
                    del _CODE_STORE[email]
                    st.session_state["auth_stage"] = "request"
                    st.error("Too many attempts. Request a new code.")
                else:
                    st.error(f"Incorrect code. {remaining} attempt(s) left.")
