"""Whitelisted endpoints the app calls on Steel Force sites (sf_trading).

Thin wrappers: each one checks what the salesman may do and hands over to
sf_trading's own function, so the rule stays in one place. On a site without
sf_trading they answer "nothing here" instead of failing.
"""

from __future__ import annotations

from typing import Optional

import frappe
from frappe import _
from frappe.utils import flt

from vansale import steelforce

_CANCELLABLE = ("Quotation", "Sales Order")


@frappe.whitelist(methods=["GET"])
def drivers() -> list[dict]:
    """Drivers (delivery persons) serving the salesman's branch, each with the
    cash they still hold and whether sf_trading would refuse them a new cash
    sale (an overdue collection, or at their cash limit)."""
    if not steelforce.is_active() or not frappe.db.exists("DocType", "Driver"):
        return []
    from vansale.api.me import van_default

    branch = van_default("Branch")
    try:
        from sf_trading.driver_branches import driver_branches
    except ImportError:
        driver_branches = None
    rows = frappe.get_all("Driver", filters={"status": "Active"}, fields=["name", "full_name"], order_by="full_name asc")
    if branch and driver_branches:
        rows = [r for r in rows if branch in (driver_branches(r.name) or [branch])]
    return [{"name": r.name, "full_name": r.full_name or r.name, **_driver_cash(r.name, branch)} for r in rows]


def _driver_cash(driver: str, branch: Optional[str]) -> dict:
    """What the driver holds and why sf_trading would refuse them (its own
    checks, so the rule stays in sf_trading)."""
    try:
        from sf_trading.api import sales_invoice_override as sio
    except ImportError:
        return {}
    try:
        holding = flt(sio._driver_uncollected_total(driver))
        limit = flt(frappe.db.get_value("Driver", driver, "custom_cash_limit"))
        branch_limit = flt(sio._driver_branch_sub_limit(driver, branch)) if branch else 0.0
        branch_holding = flt(sio._driver_branch_uncollected_total(driver, branch)) if branch_limit else 0.0
        overdue = sio._get_driver_overdue_invoice(driver)
    except Exception:
        frappe.log_error(title="vansale: driver cash status")
        return {}
    blocked = None
    if overdue:
        blocked = _("Overdue collection {0} of {1}").format(overdue.name, overdue.posting_date)
    elif limit and holding >= limit:
        blocked = _("At the cash limit")
    elif branch_limit and branch_holding >= branch_limit:
        blocked = _("At the {0} branch cash limit").format(branch)
    return {
        "holding": holding,
        "cash_limit": limit,
        "branch_holding": branch_holding,
        "branch_limit": branch_limit,
        "blocked": blocked,
    }


@frappe.whitelist(methods=["GET"])
def cancellation_options(doctype: str, name: str) -> dict:
    """Whether the salesman may ask for this submitted quotation / order to be
    cancelled (sf_trading's request workflow must be active and the user must
    hold a requester role), and the reasons to pick from."""
    if doctype not in _CANCELLABLE or not steelforce.is_active():
        return {"can_request": False, "reasons": []}
    try:
        from sf_trading.order_cancellation import can_request
    except ImportError:
        return {"can_request": False, "reasons": []}
    allowed = bool(can_request(doctype, name))
    reasons = (
        frappe.get_all("Order Cancellation Reason", pluck="name", order_by="name asc")
        if allowed and frappe.db.exists("DocType", "Order Cancellation Reason")
        else []
    )
    return {"can_request": allowed, "reasons": reasons}


@frappe.whitelist(methods=["POST"])
def request_cancellation(doctype: str, name: str, reason: str, details: Optional[str] = None) -> dict:
    """Send a submitted quotation / order to the office for cancellation, with a
    reason (sf_trading records it and starts its approval)."""
    if doctype not in _CANCELLABLE:
        frappe.throw(_("Only a quotation or a sales order can be cancelled from the app"))
    if not steelforce.is_active():
        frappe.throw(_("Cancellation requests are not set up on this site"))
    from sf_trading.order_cancellation import request_cancellation as sf_request

    result = sf_request(doctype, name, reason, details)
    frappe.db.commit()
    return dict(result or {})
