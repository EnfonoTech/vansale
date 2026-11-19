"""Web Push for approvals: a phone or browser that opted in gets a notification
when a new PM Workflow Action reaches its user, even with the app closed.

The browser subscribes through the PWA's service worker and hands its push
endpoint and keys to `push_subscribe`; the rows live in "Vansale Push
Subscription", one per endpoint, always owned by the signed-in user. When
Permission Manager (PM) inserts an Open action, `notify_new_action` (a
`doc_events` hook) queues `send_for_action`, which sends one VAPID-signed push
per subscription of each subscribed user PM lets act on that action. Only the
document type and name leave the server, and only to someone who may read the
document; everyone else gets a generic line.

Keys: `bench --site X execute vansale.steelforce.approvals_push.setup_keys`
writes `vansale_vapid_private_key` / `vansale_vapid_public_key` to the site
config. Push stays off until both are there, `pywebpush` imports and PM is
installed (`approvals.is_available()`).
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Optional
from urllib.parse import quote, urlparse

import frappe
from frappe import STANDARD_USERS, _
from frappe.utils import cint, cstr, get_url, now_datetime

from vansale.steelforce import approvals
from vansale.steelforce.approvals import PM_ACTION

SUBSCRIPTION = "Vansale Push Subscription"
PRIVATE_KEY_CONF = "vansale_vapid_private_key"
PUBLIC_KEY_CONF = "vansale_vapid_public_key"

MAX_SUBSCRIPTIONS = 10
"""The most subscriptions one user keeps; the oldest beyond that are deleted."""
MAX_FAILURES = 5
"""Consecutive failed sends after which a subscription is deleted."""
ENDPOINT_LIMIT = 1000
KEY_LIMIT = 255
PUSH_TTL = 86400
PUSH_TIMEOUT = 10
GONE_STATUSES = (404, 410)
"""What a push service answers for a subscription that no longer exists."""

PUSH_HOST_SUFFIXES = (
    "fcm.googleapis.com",
    "android.googleapis.com",
    "push.services.mozilla.com",
    "push.apple.com",
    "notify.windows.com",
)
"""The push services browsers use (Chrome/Edge-Chromium/Samsung/Opera/Brave on
FCM, Firefox, Safari and iOS PWAs, legacy Edge). An endpoint on any other host
is refused, so the server never POSTs to an address a user made up."""

_KEY_PATTERN = re.compile(r"^[A-Za-z0-9_\-+/=]+$")

INBOX_URL = "/vansale/approvals"


# ─── Pure helpers (tested without a site) ─────────────────────────────────────


def endpoint_hash(endpoint: str) -> str:
    """The subscription's name: sha256 (hex) of its endpoint."""
    return hashlib.sha256(cstr(endpoint).encode("utf-8")).hexdigest()


def subscription_problem(endpoint: str, p256dh: str, auth: str) -> Optional[str]:
    """Why a subscription cannot be stored ("endpoint", "service" or "keys"),
    or None when it is fine."""
    if not endpoint.startswith("https://") or len(endpoint) > ENDPOINT_LIMIT or any(c.isspace() for c in endpoint):
        return "endpoint"
    host = (urlparse(endpoint).hostname or "").lower()
    if not any(host == suffix or host.endswith("." + suffix) for suffix in PUSH_HOST_SUFFIXES):
        return "service"
    for key in (p256dh, auth):
        if not key or len(key) > KEY_LIMIT or not _KEY_PATTERN.match(key):
            return "keys"
    return None


def _problem_text(problem: str) -> str:
    return {
        "endpoint": _("The notification address from this browser is not valid"),
        "service": _("This browser's notification service is not supported"),
        "keys": _("The notification keys from this browser are not valid"),
    }[problem]


def build_payload(doctype: str, docname: str, action_name: str, can_read: bool) -> dict:
    """The push for one recipient, in the current language: the document type
    and name with a link to its approval screen when the recipient may read the
    document, else a generic line pointing at the inbox."""
    if can_read:
        return {
            "title": _("Approval needed"),
            "body": f"{_(doctype)} {docname}",
            "url": f"{INBOX_URL}/{quote(cstr(doctype), safe='')}/{quote(cstr(docname), safe='')}",
            "tag": action_name,
        }
    return {
        "title": _("Approval needed"),
        "body": _("A document is waiting for your decision"),
        "url": INBOX_URL,
        "tag": action_name,
    }


def failure_outcome(status: Optional[int], failures: int) -> str:
    """What to do with a subscription after a failed send: "delete" when the
    push service says it is gone or it has now failed `MAX_FAILURES` times in a
    row, else "count". `failures` is the count before this failure."""
    if status in GONE_STATUSES:
        return "delete"
    return "delete" if cint(failures) + 1 >= MAX_FAILURES else "count"


def wants_push(user: str, for_submitter: str, is_adhoc: bool) -> bool:
    """False for the person who submitted the document, unless the action is an
    ad hoc one (a forward may land back with them)."""
    return bool(is_adhoc) or user != cstr(for_submitter)


def vapid_subject(url: str) -> str:
    """The VAPID `sub` claim: the site's base URL over https (a site behind a
    proxy may report http). Never a person's email."""
    base = cstr(url).strip().rstrip("/")
    if base.startswith("http://"):
        base = "https://" + base[len("http://") :]
    return base


# ─── Site checks ──────────────────────────────────────────────────────────────


def _webpush():
    """The `pywebpush` module, imported on use (tests replace this)."""
    import pywebpush

    return pywebpush


def _has_webpush() -> bool:
    try:
        _webpush()
    except ImportError:
        return False
    return True


def is_enabled() -> bool:
    """Approvals are available, both VAPID keys are in the site config, the
    subscription table exists (a pull without migrate keeps push off) and
    `pywebpush` imports."""
    return bool(
        approvals.is_available()
        and frappe.conf.get(PRIVATE_KEY_CONF)
        and frappe.conf.get(PUBLIC_KEY_CONF)
        and frappe.db.table_exists(SUBSCRIPTION)
        and _has_webpush()
    )


def _session_user() -> str:
    user = cstr(frappe.session.user)
    if not user or user == "Guest":
        frappe.throw(_("Sign in to manage notifications"), frappe.PermissionError)
    return user


# ─── Endpoints ────────────────────────────────────────────────────────────────


@frappe.whitelist(methods=["GET"])
def push_config(endpoint: str = "") -> dict:
    """Whether push can be used here (`enabled`), the VAPID public key the
    browser subscribes with ("" when not enabled) and whether this `endpoint`
    is subscribed for the signed-in user."""
    user = _session_user()
    endpoint = cstr(endpoint).strip()
    enabled = is_enabled()
    subscribed = bool(
        enabled and endpoint and frappe.db.exists(SUBSCRIPTION, {"name": endpoint_hash(endpoint), "user": user})
    )
    return {
        "enabled": enabled,
        "public_key": cstr(frappe.conf.get(PUBLIC_KEY_CONF)) if enabled else "",
        "subscribed": subscribed,
    }


@frappe.whitelist(methods=["POST"])
def push_subscribe(endpoint: str, p256dh: str, auth: str, user_agent: str = "") -> dict:
    """Store this browser's subscription for the signed-in user. An endpoint
    already stored for someone else moves to the signed-in user (same device,
    another person signed in). Keeps the user's newest 10."""
    user = _session_user()
    if not is_enabled():
        frappe.throw(_("Notifications are not available on this site"))
    endpoint, p256dh, auth = cstr(endpoint).strip(), cstr(p256dh).strip(), cstr(auth).strip()
    problem = subscription_problem(endpoint, p256dh, auth)
    if problem:
        frappe.throw(_problem_text(problem))
    values = {
        "user": user,
        "endpoint": endpoint,
        "p256dh": p256dh,
        "auth": auth,
        "user_agent": cstr(user_agent)[:KEY_LIMIT],
        "failures": 0,
    }

    name = endpoint_hash(endpoint)
    if frappe.db.exists(SUBSCRIPTION, name):
        doc = frappe.get_doc(SUBSCRIPTION, name)
        doc.update(values)
        doc.save(ignore_permissions=True)
    else:
        frappe.get_doc({"doctype": SUBSCRIPTION, "endpoint_hash": name, **values}).insert(ignore_permissions=True)

    _trim(user, keep=name)
    return {"ok": True}


@frappe.whitelist(methods=["POST"])
def push_unsubscribe(endpoint: str) -> dict:
    """Forget this browser's subscription for the signed-in user (nothing
    happens when there is none, or it belongs to someone else)."""
    user = _session_user()
    name = endpoint_hash(cstr(endpoint).strip())
    if frappe.db.exists(SUBSCRIPTION, {"name": name, "user": user}):
        frappe.delete_doc(SUBSCRIPTION, name, ignore_permissions=True, force=True)
    return {"ok": True}


def _trim(user: str, keep: str) -> None:
    """Delete the user's subscriptions beyond the newest `MAX_SUBSCRIPTIONS`;
    the one just stored always stays."""
    names = frappe.get_all(
        SUBSCRIPTION, filters={"user": user}, pluck="name", order_by="modified desc, creation desc"
    )
    kept = [keep] + [name for name in names if name != keep]
    for name in kept[MAX_SUBSCRIPTIONS:]:
        frappe.delete_doc(SUBSCRIPTION, name, ignore_permissions=True, force=True)


# ─── Keys ─────────────────────────────────────────────────────────────────────


def generate_vapid_keys() -> tuple[str, str]:
    """A new VAPID key pair as `(private, public)`: the private key is the
    base64url raw 32-byte value pywebpush accepts, the public key base64url of
    the uncompressed point (the browser's `applicationServerKey`)."""
    from cryptography.hazmat.primitives import serialization
    from py_vapid import Vapid
    from py_vapid.utils import b64urlencode, num_to_bytes

    vapid = Vapid()
    vapid.generate_keys()
    private = b64urlencode(num_to_bytes(vapid.private_key.private_numbers().private_value, 32))
    public = b64urlencode(
        vapid.public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    )
    return private, public


def setup_keys(force: int = 0) -> str:
    """Write a VAPID key pair to the site config when it is missing (or
    `force`), and return the public key. Run with
    `bench --site X execute vansale.steelforce.approvals_push.setup_keys`.
    The private key is never returned or logged. A forced new pair makes every
    stored subscription useless (they were made with the old public key), so
    they are deleted and each device subscribes again."""
    from frappe.installer import update_site_config

    private, public = frappe.conf.get(PRIVATE_KEY_CONF), frappe.conf.get(PUBLIC_KEY_CONF)
    if private and public and not cint(force):
        return cstr(public)

    private, public = generate_vapid_keys()
    update_site_config(PRIVATE_KEY_CONF, private)
    update_site_config(PUBLIC_KEY_CONF, public)
    frappe.conf[PRIVATE_KEY_CONF] = private
    frappe.conf[PUBLIC_KEY_CONF] = public
    if cint(force) and frappe.db.table_exists(SUBSCRIPTION):
        frappe.db.delete(SUBSCRIPTION)
        frappe.db.commit()
    return public


# ─── Trigger and worker ───────────────────────────────────────────────────────


def notify_new_action(doc, method=None) -> None:
    """`after_insert` of PM Workflow Action: queue the pushes for an Open action
    on a type the approvals handle, when push is on and anyone subscribed.
    Never raises into PM's save."""
    try:
        if cstr(doc.get("status")) != "Open":
            return
        if not is_enabled():
            return
        if not frappe.db.exists(SUBSCRIPTION, {"name": ("is", "set")}):
            return
        if approvals._is_hidden(doc.get("reference_doctype"), approvals._hidden_types()):
            return
        frappe.enqueue(
            "vansale.steelforce.approvals_push.send_for_action",
            queue="short",
            action_name=doc.name,
            enqueue_after_commit=True,
            job_name=f"vansale_push_{doc.name}",
        )
    except Exception:
        frappe.log_error(title="vansale push: queue failed", defer_insert=True)


def send_for_action(action_name: str) -> None:
    """Send the pushes for one action (background job). Each subscribed,
    enabled system user PM lets act on the action gets one push per device,
    worded in their language; dead subscriptions are deleted, failing ones
    counted. One bad subscription never stops the others."""
    action_name = cstr(action_name)
    if not is_enabled() or not frappe.db.exists(PM_ACTION, action_name):
        return
    action = frappe.get_doc(PM_ACTION, action_name)
    doctype, docname = cstr(action.get("reference_doctype")), cstr(action.get("reference_name"))
    if action.get("status") != "Open" or not doctype or not docname or approvals._is_hidden(doctype):
        return

    rows = frappe.get_all(SUBSCRIPTION, fields=["name", "user", "endpoint", "p256dh", "auth", "failures"])
    subscribed = list(dict.fromkeys(row.user for row in rows if row.user))
    if not subscribed:
        return
    people = {
        person.name: person
        for person in frappe.get_all(
            "User",
            filters={"name": ("in", subscribed), "enabled": 1, "user_type": "System User"},
            fields=["name", "language"],
        )
        if person.name not in STANDARD_USERS
    }

    payloads: dict[str, str] = {}
    for user in subscribed:
        if user not in people:
            continue
        if not wants_push(user, action.get("for_submitter"), cint(action.get("is_adhoc"))):
            continue
        payload = _payload_for(action, doctype, docname, user, people[user].get("language"))
        if payload is not None:
            payloads[user] = json.dumps(payload)

    failed: list[str] = []
    for row in rows:
        data = payloads.get(row.user)
        if data is not None:
            error = _send_one(row, data)
            if error:
                failed.append(error)

    if failed:
        frappe.log_error(
            title="vansale push: send failed",
            message=f"{len(failed)} push(es) for {action_name} failed: {', '.join(sorted(set(failed)))}",
            defer_insert=True,
        )


def _payload_for(action, doctype: str, docname: str, user: str, language: Optional[str]) -> Optional[dict]:
    """The push for `user`, or None when PM does not let them act on the
    action (or asking failed). Worded in the user's language."""
    previous_lang = getattr(frappe.local, "lang", None)
    try:
        if not approvals._pm().can_act_on(action, user):
            return None
        try:
            can_read = bool(frappe.has_permission(doctype, "read", doc=docname, user=user))
        except Exception:
            can_read = False
        frappe.local.lang = cstr(language) or previous_lang or "en"
        return build_payload(doctype, docname, action.name, can_read)
    except Exception:
        frappe.log_error(title="vansale push: recipient check failed", defer_insert=True)
        return None
    finally:
        frappe.local.lang = previous_lang


def _send_one(row, data: str) -> Optional[str]:
    """Send one push; returns None on success, else a short reason (an
    exception class and status code, never the endpoint or keys)."""
    pywebpush = _webpush()
    try:
        pywebpush.webpush(
            subscription_info={"endpoint": row.endpoint, "keys": {"p256dh": row.p256dh, "auth": row.auth}},
            data=data,
            vapid_private_key=frappe.conf.get(PRIVATE_KEY_CONF),
            # A fresh dict per call: pywebpush writes this endpoint's `aud`
            # and `exp` into it.
            vapid_claims={"sub": vapid_subject(get_url())},
            ttl=PUSH_TTL,
            timeout=PUSH_TIMEOUT,
        )
    except Exception as error:
        status = None
        if isinstance(error, pywebpush.WebPushException):
            status = getattr(getattr(error, "response", None), "status_code", None)
        _record_failure(row, status)
        return f"{type(error).__name__}" + (f" {status}" if status else "")

    frappe.db.set_value(
        SUBSCRIPTION, row.name, {"last_ok": now_datetime(), "failures": 0}, update_modified=False
    )
    return None


def _record_failure(row, status: Optional[int]) -> None:
    if failure_outcome(status, row.failures) == "delete":
        frappe.db.delete(SUBSCRIPTION, {"name": row.name})
    else:
        frappe.db.set_value(SUBSCRIPTION, row.name, "failures", cint(row.failures) + 1, update_modified=False)
