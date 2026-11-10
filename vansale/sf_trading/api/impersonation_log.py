# apps/vansale/vansale/sf_trading/api/impersonation_log.py
"""Keep the impersonation reason in the audit trail.

Frappe's ``frappe.core.doctype.user.user.impersonate`` writes an Activity Log row
for every impersonation, but the reason the admin typed in the confirm dialog goes
only into the Notification Log sent to the impersonated user — the audit trail
itself never carries it. Anyone auditing the Activity Log later sees *who*
impersonated *whom*, never *why*.

This ``before_insert`` hook closes that gap. The reason travels in the same request
that creates the row (``frappe.form_dict``), so it can be read off the request and
stamped onto the log: full text into the custom field and the Message body, a
trimmed copy appended to the subject so the list view shows it without a drill-in.

Reading the request rather than overriding ``impersonate`` keeps this upgrade-safe:
no core signature is duplicated, and the hook stays inert for every other Activity
Log row (Login, Logout, and anything an app writes itself).
"""

import frappe
from frappe import _
from frappe.utils import cstr, escape_html, strip_html_tags

REASON_FIELD = "custom_impersonation_reason"

# Small Text on the form, but the subject also drives the list view — keep the
# appended copy short and leave the full reason in the field and the Message body.
SUBJECT_REASON_LIMIT = 120


def capture_impersonation_reason(doc, method=None):
    """Activity Log ``before_insert``: record the reason given for an impersonation."""
    if doc.get("operation") != "Impersonate":
        return

    reason = _reason_from_request()
    if not reason:
        return

    doc.set(REASON_FIELD, reason)

    if not doc.get("content"):
        doc.content = _("Reason for impersonating: %s") % escape_html(reason)

    doc.subject = _("%(subject)s. Reason: %(reason)s") % {
        "subject": cstr(doc.subject).rstrip("."),
        "reason": _trim(reason),
    }


def _reason_from_request() -> str:
    """Read ``reason`` off the impersonate call that is creating this row.

    ``frappe.core.doctype.user.user.impersonate`` is a whitelisted POST, so its
    arguments sit in ``form_dict`` for the whole request. Returns an empty string
    when the row is written outside such a request (tests, background jobs, a
    console session) — the hook then leaves the log untouched.
    """
    form = getattr(frappe.local, "form_dict", None)
    if not form:
        return ""

    # markup has no place in an audit trail, and the reason is plain text by design
    return strip_html_tags(cstr(form.get("reason"))).strip()


def _trim(reason: str) -> str:
    if len(reason) <= SUBJECT_REASON_LIMIT:
        return reason

    return reason[:SUBJECT_REASON_LIMIT].rstrip() + "…"
