"""Pure rules behind the Approvals screen. No `frappe` import: nothing here
touches a site, so every rule is tested without one.

The server (`vansale.steelforce.approvals`) calls these; the PWA mirrors the
same rules in `frontend/src/features/approvals/rules.ts`. Permission Manager
(PM) stays the owner of who may do what; this module only decides how an
action is labelled, what it must be given and how the inbox is summed up.
"""

from __future__ import annotations

from typing import Optional

OVERDUE_DAYS = 30
"""An item waiting longer than this many days is overdue (the desk's own cut)."""

HIGH_PRIORITIES = ("High", "Critical")

_AREAS = {
    "Accounts": ("Journal Entry", "Payment Entry", "Payment Advice", "Payment Request"),
    "Purchase": ("Purchase Invoice", "Purchase Order", "Purchase Receipt"),
    "Sales": ("Sales Invoice", "Sales Order", "Quotation", "Delivery Note"),
    "Masters": ("Customer", "Supplier", "Item", "SF Master Change Request"),
    "Stock": ("Stock Reconciliation", "Material Request", "Stock Entry"),
}
_AREA_BY_DOCTYPE = {
    doctype: area for area, doctypes in _AREAS.items() for doctype in doctypes
}


def tone_of(action: str, is_return_for_correction: bool) -> str:
    """How the action button looks: "reject", "other" or "approve".

    A return-for-correction transition is always a reject, whatever it is
    called. Otherwise the name decides: "Reject ..." rejects, "Request ..."
    (for instance "Request Cancellation") is neither, the rest approve.
    """
    if is_return_for_correction:
        return "reject"
    name = (action or "").strip().lower()
    if name.startswith("reject"):
        return "reject"
    if name.startswith("request"):
        return "other"
    return "approve"


def required_inputs(
    require_comment: bool,
    require_attachment: bool,
    is_return_for_correction: bool,
    has_attachment: bool,
) -> dict[str, bool]:
    """What the approver must still give before the action can be applied.

    A comment is required by the transition, and always when the action
    returns the document for correction. An attachment is required only while
    the document has none.
    """
    return {
        "comment": bool(require_comment or is_return_for_correction),
        "attachment": bool(require_attachment and not has_attachment),
    }


def check_apply(
    spec: Optional[dict], comment: Optional[str], has_attachment: bool
) -> Optional[str]:
    """Whether an apply may go ahead: None when it may, otherwise the reason.

    `spec` is the action's ActionSpec, or None when the action is not one the
    user may take on the document ("not_allowed"). A recommendation (the user
    was asked for advice, not a decision) needs no comment or attachment.
    """
    if not spec:
        return "not_allowed"
    if spec.get("recommend_only"):
        return None

    needed = required_inputs(
        bool(spec.get("require_comment")),
        bool(spec.get("require_attachment")),
        bool(spec.get("is_return_for_correction")),
        has_attachment,
    )
    if needed["comment"] and not (comment or "").strip():
        return "comment_required"
    if needed["attachment"]:
        return "attachment_required"
    return None


def area_of(doctype: str) -> str:
    """The filter chip a document type belongs to: Accounts, Purchase, Sales,
    Masters, Stock, or "Other"."""
    return _AREA_BY_DOCTYPE.get(doctype, "Other")


def inbox_stats(needs_you_items: list[dict]) -> dict:
    """The desk's two stats over the items waiting on the user: how many are
    High or Critical, and how many have waited more than 30 days."""
    high = 0
    overdue = 0
    for item in needs_you_items:
        if item.get("priority") in HIGH_PRIORITIES:
            high += 1
        if (item.get("days") or 0) > OVERDUE_DAYS:
            overdue += 1
    return {"high": high, "overdue": overdue}
