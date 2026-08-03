"""Auth endpoints.

Flow (mirrors fatehhr):

    1. User opens web SPA, logs in with email + password via `login`.
       This is a regular Frappe cookie session — used for `setup_pin`.
    2. `setup_pin(pin)` stores a bcrypt hash of the PIN in the user's
       `Vansale Pin` doc. Server returns a stable `api_key` + `api_secret`.
    3. Capacitor APK stores the key/secret pair in `@capacitor/preferences`
       and uses `login_with_pin(email, pin)` on every app launch. The
       pair is NEVER regenerated (see `frappe-vue-pwa` §3.5 rule 7).

Password field caveats (rule 8):
    `doc.pin_hash` returns 60 asterisks (the field mask), NOT the bcrypt
    hash. `doc.get_password("pin_hash")` returns the real decrypted hash.
    Using the mask sends `bcrypt.checkpw` into `Invalid salt`.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import now_datetime

try:
    import bcrypt
except ImportError:  # pragma: no cover — bench env always has bcrypt via requirements
    bcrypt = None  # type: ignore[assignment]

from vansale.utils.secrets import get_or_create_stable_secret

_PIN_MIN = 4
_PIN_MAX = 4


def _ensure_bcrypt() -> None:
    if bcrypt is None:
        frappe.throw(_("bcrypt is not installed in the bench env"))


def _validate_pin(pin: str) -> str:
    if not isinstance(pin, str):
        frappe.throw(_("PIN must be a string"))
    pin = pin.strip()
    if not pin.isdigit() or not (_PIN_MIN <= len(pin) <= _PIN_MAX):
        # Keep range-style message even when min==max so future expansion stays single-source.
        frappe.throw(
            _("PIN must be {0} digits").format(_PIN_MIN)
            if _PIN_MIN == _PIN_MAX
            else _("PIN must be {0}–{1} digits").format(_PIN_MIN, _PIN_MAX)
        )
    return pin


def _resolve_user(email: str) -> str:
    name = frappe.db.get_value("User", {"email": email}, "name") or frappe.db.get_value(
        "User", {"name": email}, "name"
    )
    if not name:
        frappe.throw(_("Invalid credentials"), frappe.AuthenticationError)
    return name


@frappe.whitelist(allow_guest=True, methods=["POST"])
def login(usr: str, pwd: str):
    """Cookie-based login for the web PWA (also used for initial PIN setup).

    Returns the authenticated user's profile on success. Raises
    ``AuthenticationError`` on failure.
    """
    if not usr or not pwd:
        frappe.throw(_("Email and password required"))

    login_manager = frappe.auth.LoginManager()
    login_manager.authenticate(user=usr, pwd=pwd)
    login_manager.post_login()

    user_doc = frappe.get_doc("User", frappe.session.user)
    # Also mint (or return existing) api_key/api_secret so the APK can
    # transition to token auth for the follow-up `setup_pin` call. On
    # native the WebView does NOT send the Frappe session cookie on
    # subsequent requests (our `fetchOpts` strips `credentials` — see
    # frontend/src/app/frappe.ts), so without a token the next call
    # would run as Guest and trip the whitelist check.
    api_key, api_secret = get_or_create_stable_secret(user_doc)
    return {
        "user": user_doc.name,
        "full_name": user_doc.full_name,
        "language": user_doc.language or "en",
        "has_pin": bool(frappe.db.exists("Vansale Pin", {"user": user_doc.name})),
        # Whether this user is asked for a PIN at all — resolved user → van →
        # global. The client needs it in the login response so it knows
        # whether to route to /pin or straight to Home.
        "require_pin": _require_pin_for(user_doc.name),
        "api_key": api_key,
        "api_secret": api_secret,
    }


@frappe.whitelist(methods=["POST"])
def setup_pin(pin: str):
    """Set or replace the logged-in user's PIN.

    Returns the stable ``api_key``/``api_secret`` pair so the device can
    switch to token auth without going through the cookie flow again.
    """
    _ensure_bcrypt()
    pin = _validate_pin(pin)

    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("Login required"), frappe.AuthenticationError)

    hashed = bcrypt.hashpw(pin.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    existing = frappe.db.get_value("Vansale Pin", {"user": user}, "name")
    if existing:
        doc = frappe.get_doc("Vansale Pin", existing)
        doc.pin_hash = hashed
        doc.save(ignore_permissions=True)
    else:
        doc = frappe.get_doc(
            {
                "doctype": "Vansale Pin",
                "user": user,
                "pin_hash": hashed,
                "created_at": now_datetime(),
            }
        )
        doc.insert(ignore_permissions=True)

    user_doc = frappe.get_doc("User", user)
    api_key, api_secret = get_or_create_stable_secret(user_doc)
    frappe.db.commit()

    return {
        "user": user,
        "full_name": user_doc.full_name,
        "api_key": api_key,
        "api_secret": api_secret,
    }


@frappe.whitelist(allow_guest=True, methods=["POST"])
def login_with_pin(email: str, pin: str):
    """PIN unlock for the native APK.

    Verifies the PIN against the stored bcrypt hash and returns the
    stable token pair. Never regenerates ``api_secret`` (rule 7).
    """
    _ensure_bcrypt()
    if not email or not pin:
        frappe.throw(_("Email and PIN required"))
    pin = _validate_pin(pin)

    user = _resolve_user(email)
    pin_doc_name = frappe.db.get_value("Vansale Pin", {"user": user}, "name")
    if not pin_doc_name:
        frappe.throw(
            _("No PIN set — please log in via the web app first to set a PIN"),
            frappe.AuthenticationError,
        )

    doc = frappe.get_doc("Vansale Pin", pin_doc_name)
    stored_hash = doc.get_password("pin_hash")  # never `doc.pin_hash` — that's the mask
    if not bcrypt.checkpw(pin.encode("utf-8"), stored_hash.encode("utf-8")):
        frappe.throw(_("Invalid credentials"), frappe.AuthenticationError)

    user_doc = frappe.get_doc("User", user)
    if user_doc.enabled == 0:
        frappe.throw(_("User is disabled"), frappe.AuthenticationError)

    api_key, api_secret = get_or_create_stable_secret(user_doc)

    return {
        "user": user,
        "full_name": user_doc.full_name,
        "api_key": api_key,
        "api_secret": api_secret,
        "roles": [r.role for r in user_doc.roles],
        "language": user_doc.language or "en",
    }


@frappe.whitelist(methods=["POST"])
def change_pin(old_pin: str, new_pin: str):
    """Change the logged-in user's PIN. Does NOT rotate api_secret."""
    _ensure_bcrypt()
    old_pin = _validate_pin(old_pin)
    new_pin = _validate_pin(new_pin)

    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("Login required"), frappe.AuthenticationError)

    pin_doc_name = frappe.db.get_value("Vansale Pin", {"user": user}, "name")
    if not pin_doc_name:
        frappe.throw(_("No PIN to change — use setup_pin first"))

    doc = frappe.get_doc("Vansale Pin", pin_doc_name)
    stored_hash = doc.get_password("pin_hash")
    if not bcrypt.checkpw(old_pin.encode("utf-8"), stored_hash.encode("utf-8")):
        frappe.throw(_("Current PIN incorrect"), frappe.AuthenticationError)

    doc.pin_hash = bcrypt.hashpw(new_pin.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    return {"ok": True}


def _require_pin_for(user: str) -> bool:
    """Effective PIN requirement for `user`: user row → van → global.

    Delegates to `me._resolve_mode` so login and `config_defaults` can never
    disagree about whether this driver needs a PIN.
    """
    from vansale.api.me import _resolve_mode
    from vansale.vansale.doctype.vansale_settings.vansale_settings import global_flags

    row = frappe.db.get_value(
        "Vansale Configuration User", {"user": user}, ["parent", "pin_mode"], as_dict=True
    )
    van_mode = None
    if row and row.parent:
        try:
            if frappe.get_meta("Vansale Configuration").has_field("pin_mode"):
                van_mode = frappe.db.get_value("Vansale Configuration", row.parent, "pin_mode")
        except Exception:
            van_mode = None
    return _resolve_mode(
        row.pin_mode if row else None, van_mode, default=global_flags()["require_pin"]
    )


@frappe.whitelist(methods=["POST"])
def reset_pin(user: str):
    """Admin PIN reset — clears the target user's PIN so they set a new one.

    The driver forgets their PIN in the field and cannot be walked through
    bcrypt by phone; the office needs a one-tap fix. Deleting the `Vansale
    Pin` row is the reset: the next login reports `has_pin: false` and the app
    routes to PIN setup.

    Permission is deliberately explicit rather than relying on the DocType's
    DocPerms — this is a whitelisted endpoint, so any logged-in Van User could
    otherwise clear a colleague's PIN. Van Manager or System Manager only, and
    never a self-reset (that is what `change_pin` is for, which proves
    knowledge of the current PIN).
    """
    if not user:
        frappe.throw(_("user is required"))
    roles = set(frappe.get_roles())
    if not roles & {"Van Manager", "System Manager"}:
        frappe.throw(_("Only a Van Manager can reset a PIN"), frappe.PermissionError)
    if user == frappe.session.user:
        frappe.throw(_("Use Change PIN to change your own PIN"))
    if not frappe.db.exists("User", user):
        frappe.throw(_("Unknown user"))

    name = frappe.db.get_value("Vansale Pin", {"user": user}, "name")
    if not name:
        return {"ok": True, "cleared": False}
    frappe.delete_doc("Vansale Pin", name, ignore_permissions=True, force=True)
    frappe.db.commit()
    return {"ok": True, "cleared": True}


@frappe.whitelist(allow_guest=True, methods=["GET"])
def site_info():
    """Pre-login connectivity probe for the APK's site-URL setup screen.

    `allow_guest` justification: the app must confirm a user-typed URL is
    reachable AND is a Frappe site with `vansale` installed BEFORE anyone
    can log in — there is no session to authenticate with yet. The response
    carries no site, user or tenant data, only "yes, this app is here and
    which version", so it leaks nothing an unauthenticated visitor cannot
    already infer from the login page.
    """
    from vansale import __version__

    return {"ok": True, "app": "vansale", "app_version": __version__}


@frappe.whitelist()
def ping():
    """Liveness probe used by the client to verify a cached token still works."""
    return {
        "user": frappe.session.user,
        "full_name": frappe.db.get_value("User", frappe.session.user, "full_name"),
        "timestamp": str(now_datetime()),
    }


@frappe.whitelist(methods=["POST"])
def logout():
    """Explicit logout — clears the session cookie. Token auth on the APK
    is cleared client-side by wiping Preferences; no server rotation needed."""
    frappe.local.login_manager.logout()
    frappe.db.commit()
    return {"ok": True}
