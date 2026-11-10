# apps/vansale/vansale/sf_trading/api/overdue_notifications.py
"""Overdue-invoice alerts — three channels, only the first two are guaranteed.

1. **Chime + toast + desktop notification** — realtime event ``sf_invoice_overdue_alert``,
   handled by ``vansale/public/sf_trading/js/sf_overdue_alert.js``.
2. **System notification (bell)** — one ``Notification Log`` of type "Alert" per user;
   Frappe's ``after_insert`` publishes the ``notification`` event so the bell badge
   updates live.
3. **Email digest — best effort, never mandatory.** Sent only when the site actually has
   an Email Account with outgoing enabled AND the user has not switched email
   notifications off. With no outgoing account nothing is sent and nothing raises.

   Frappe's own Notification-Log email path cannot serve this: in
   ``frappe/desk/doctype/notification_settings/notification_settings.py``,
   ``is_email_notifications_enabled_for_type()`` returns False when
   ``notification_type == "Alert"``, so an Alert log never emails. Hence the explicit,
   guarded ``frappe.sendmail`` below.

Recipients are resolved by role, each user notified once, scoped to what they own:
sales-only, purchase-only, or both.

No SQL is built here — every read goes through frappe.get_all with dict filters.
"""

import frappe
from frappe import _
from frappe.desk.doctype.notification_log.notification_log import enqueue_create_notification
from frappe.desk.doctype.notification_settings.notification_settings import (
    is_email_notifications_enabled,
    is_notifications_enabled,
)
from frappe.utils import (
    date_diff,
    escape_html,
    flt,
    fmt_money,
    formatdate,
    get_url,
    getdate,
    nowdate,
)

EVENT = "sf_invoice_overdue_alert"
REPORT = "Invoice Due and Overdue Report"
REPORT_ROUTE = "/app/query-report/Invoice%20Due%20and%20Overdue%20Report"
EMAIL_ROW_LIMIT = 15

# role -> what that role should be told about
ROLE_SCOPE = {
    "Accounts Manager": "both",
    "Accountant": "both",
    "Finance Manager": "both",
    "HO Accounts": "both",
    "Branch Head": "both",
    "Purchase Manager": "purchase",
    "Purchase Assistant": "purchase",
    "Sales Manager": "sales",
}

SCOPE_DOCTYPES = {
    "sales": ("Sales Invoice",),
    "purchase": ("Purchase Invoice",),
    "both": ("Sales Invoice", "Purchase Invoice"),
}

PARTY_NAME_FIELD = {"Sales Invoice": "customer_name", "Purchase Invoice": "supplier_name"}

SKIP_USERS = ("Administrator", "Guest")


# ── Data ──────────────────────────────────────────────────────────────────────────

def _overdue_filters(company=None, as_on=None):
    filters = {
        "docstatus": 1,
        "outstanding_amount": [">", 0],
        "due_date": ["<", getdate(as_on or nowdate())],
    }
    if company:
        filters["company"] = company
    return filters


def _overdue_summary(company=None, as_on=None):
    """Count + outstanding total of overdue Sales / Purchase Invoices.

    ``outstanding_amount`` is already in company currency (party_account_currency),
    so it is summed as-is — never multiplied by conversion_rate.
    """
    summary = {}
    for scope, doctype in (("sales", "Sales Invoice"), ("purchase", "Purchase Invoice")):
        rows = frappe.get_all(
            doctype,
            filters=_overdue_filters(company, as_on),
            fields=["name", "outstanding_amount"],
            ignore_permissions=True,
        )
        summary[scope] = {
            "count": len(rows),
            "outstanding": flt(sum(flt(r.outstanding_amount) for r in rows), 3),
        }
    return summary


def _top_overdue(scope, company=None, as_on=None, limit=EMAIL_ROW_LIMIT):
    """Oldest overdue invoices for the email digest (worst first)."""
    as_on_date = getdate(as_on or nowdate())
    rows = []

    for doctype in SCOPE_DOCTYPES.get(scope, SCOPE_DOCTYPES["both"]):
        for row in frappe.get_all(
            doctype,
            filters=_overdue_filters(company, as_on_date),
            fields=[
                "name",
                "due_date",
                "outstanding_amount",
                PARTY_NAME_FIELD[doctype] + " as party_name",
            ],
            order_by="due_date asc",
            limit=limit,
            ignore_permissions=True,
        ):
            rows.append(
                {
                    "kind": _("Sales") if doctype == "Sales Invoice" else _("Purchase"),
                    "invoice": row.name,
                    "party_name": row.party_name or "",
                    "due_date": row.due_date,
                    "overdue_days": date_diff(as_on_date, getdate(row.due_date)),
                    "outstanding": flt(row.outstanding_amount),
                }
            )

    rows.sort(key=lambda r: (-r["overdue_days"], -r["outstanding"]))
    return rows[:limit]


# ── Recipients ────────────────────────────────────────────────────────────────────

def _users_by_scope():
    """Map user -> scope ("both" / "sales" / "purchase") from enabled role holders."""
    scopes = {}
    rank = {"sales": 1, "purchase": 1, "both": 2}

    for role, scope in ROLE_SCOPE.items():
        holders = frappe.get_all(
            "Has Role",
            filters={"role": role, "parenttype": "User"},
            pluck="parent",
        )
        if not holders:
            continue

        enabled = frappe.get_all(
            "User",
            filters={"name": ["in", holders], "enabled": 1, "user_type": "System User"},
            pluck="name",
        )
        for user in enabled:
            if user in SKIP_USERS:
                continue
            current = scopes.get(user)
            # a user holding both a sales and a purchase role sees both
            if current and current != scope:
                scopes[user] = "both"
            elif not current or rank[scope] > rank[current]:
                scopes[user] = scope

    return scopes


# ── Message building ──────────────────────────────────────────────────────────────

def _company_currency(company=None):
    """Company currency where a company is known, else the system default."""
    if company:
        currency = frappe.get_cached_value("Company", company, "default_currency")
        if currency:
            return currency
    return frappe.db.get_default("currency") or ""


def _payload(summary, scope, company=None):
    """Build the realtime payload for one scope, or None when nothing is overdue."""
    parts = []
    count = 0
    outstanding = 0.0

    for key, label in (("sales", _("sales")), ("purchase", _("purchase"))):
        if scope not in ("both", key):
            continue
        bucket = summary.get(key) or {}
        if not bucket.get("count"):
            continue
        count += bucket["count"]
        outstanding += flt(bucket["outstanding"])
        parts.append("%s %s" % (bucket["count"], label))

    if not count:
        return None

    currency = _company_currency(company)
    message = _("%(count)s overdue (%(detail)s) — %(amount)s outstanding") % {
        "count": count,
        "detail": " + ".join(parts),
        "amount": fmt_money(outstanding, precision=3, currency=currency),
    }

    return {
        "title": _("Overdue invoices"),
        "message": message,
        "count": count,
        "outstanding": flt(outstanding, 3),
        "currency": currency,
        "report": REPORT,
        "route": REPORT_ROUTE,
    }


def _digest_html(payload, rows):
    """Email body: headline + worst-offenders table + a link into the report."""
    currency = payload.get("currency") or ""
    html = [
        "<p><b>", escape_html(payload["message"]), "</b></p>",
        "<p>", escape_html(_("Oldest %s listed below.") % len(rows)), "</p>",
        '<table border="1" cellpadding="6" cellspacing="0" ',
        'style="border-collapse:collapse;font-size:13px">',
        '<tr style="background:#f4f5f6">',
        "<th>", escape_html(_("Type")), "</th>",
        "<th>", escape_html(_("Invoice")), "</th>",
        "<th>", escape_html(_("Party")), "</th>",
        "<th>", escape_html(_("Due Date")), "</th>",
        "<th>", escape_html(_("Overdue Days")), "</th>",
        "<th>", escape_html(_("Outstanding")), "</th>",
        "</tr>",
    ]

    for row in rows:
        html += [
            "<tr>",
            "<td>", escape_html(row["kind"]), "</td>",
            "<td>", escape_html(row["invoice"]), "</td>",
            "<td>", escape_html(row["party_name"]), "</td>",
            "<td>", escape_html(formatdate(row["due_date"])), "</td>",
            '<td align="right">', escape_html(str(row["overdue_days"])), "</td>",
            '<td align="right">',
            escape_html(fmt_money(row["outstanding"], precision=3, currency=currency)),
            "</td>",
            "</tr>",
        ]

    html += [
        "</table>",
        '<p><a href="', get_url(REPORT_ROUTE), '">',
        escape_html(_("Open the full report")),
        "</a></p>",
    ]
    return "".join(html)


# ── Channels ──────────────────────────────────────────────────────────────────────

def _outgoing_email_configured():
    """True only when the site has an Email Account with outgoing enabled."""
    return bool(frappe.db.exists("Email Account", {"enable_outgoing": 1}))


def _push_realtime(user, payload):
    """Channel 1 — chime + toast + desktop notification."""
    try:
        frappe.publish_realtime(event=EVENT, message=payload, user=user, after_commit=True)
    except Exception:
        frappe.log_error(frappe.get_traceback(), "sf_trading: overdue realtime push failed")


def _push_system_notification(user, payload):
    """Channel 2 — the desk bell.

    Type "Alert" is deliberate: make_notification_logs() inserts an Alert even when
    for_user == from_user, so the person who clicks "Notify Me Now" still gets it.
    """
    try:
        enqueue_create_notification(
            [user],
            {
                "type": "Alert",
                "subject": payload["message"],
                "document_type": "Report",
                "document_name": REPORT,
                "link": REPORT_ROUTE,
                "from_user": frappe.session.user or "Administrator",
            },
        )
    except Exception:
        frappe.log_error(frappe.get_traceback(), "sf_trading: overdue system notification failed")


def _send_email(user, payload, rows):
    """Channel 3 — best-effort email digest. Returns True only when actually queued."""
    if not is_notifications_enabled(user) or not is_email_notifications_enabled(user):
        return False

    recipient = frappe.db.get_value("User", user, "email") or user
    if not recipient:
        return False

    subject = _("Overdue invoices — %(count)s open, %(amount)s outstanding") % {
        "count": payload["count"],
        "amount": fmt_money(
            payload["outstanding"], precision=3, currency=payload.get("currency") or ""
        ),
    }

    try:
        frappe.sendmail(
            recipients=[recipient],
            subject=subject,
            message=_digest_html(payload, rows),
            reference_doctype="Report",
            reference_name=REPORT,
        )
        return True
    except frappe.OutgoingEmailError:
        # No usable outgoing account — email is explicitly optional, so this is not an error.
        return False
    except Exception:
        frappe.log_error(frappe.get_traceback(), "sf_trading: overdue email failed")
        return False


def _notify(user, scope, summary, company=None, as_on=None, email_allowed=False):
    """Fire every enabled channel for one user. Returns the payload, or None."""
    payload = _payload(summary, scope, company=company)
    if not payload:
        return None

    _push_realtime(user, payload)
    _push_system_notification(user, payload)

    payload["emailed"] = False
    if email_allowed:
        rows = _top_overdue(scope, company=company, as_on=as_on)
        payload["emailed"] = _send_email(user, payload, rows)

    return payload


# ── Entry points ──────────────────────────────────────────────────────────────────

def notify_overdue_invoices(company=None):
    """Daily scheduler entry — alert every AR/AP role holder about overdue invoices."""
    summary = _overdue_summary(company=company)
    if not (summary["sales"]["count"] or summary["purchase"]["count"]):
        return

    email_allowed = _outgoing_email_configured()
    if not email_allowed:
        # Informational only: the desk channels still fire.
        frappe.logger("sf_trading").info(
            "overdue alert: no outgoing Email Account enabled - chime + bell only"
        )

    for user, scope in _users_by_scope().items():
        _notify(user, scope, summary, company=company, email_allowed=email_allowed)


@frappe.whitelist()
def check_overdue_now(company=None):
    """Re-run the check for the calling user only (the report's "Notify Me Now" button).

    Read access to either invoice type is enough — the returned summary is aggregate,
    and the report itself is role-gated.
    """
    if not (
        frappe.has_permission("Sales Invoice", "read")
        or frappe.has_permission("Purchase Invoice", "read")
    ):
        frappe.throw(_("Not permitted to read invoices"), frappe.PermissionError)

    user = frappe.session.user
    summary = _overdue_summary(company=company)
    scope = _users_by_scope().get(user, "both")
    email_configured = _outgoing_email_configured()

    payload = _notify(user, scope, summary, company=company, email_allowed=email_configured)
    if payload:
        payload["email_configured"] = email_configured
        return payload

    return {
        "count": 0,
        "outstanding": 0.0,
        "currency": frappe.db.get_default("currency") or "",
        "emailed": False,
        "email_configured": email_configured,
    }
