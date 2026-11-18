"""Pre-check before submit: what would refuse this sale, while the salesman is
still with the customer.

Nothing is saved. The app calls it (online only) before *Submit* on an invoice
or an order and shows every problem at once, instead of one server refusal
after another. The submit itself still runs every check, so a skipped
pre-check (offline) is never a way around a rule.
"""

from __future__ import annotations

from typing import Any, Optional

import frappe
from frappe import _
from frappe.utils import flt

_DOCTYPES = ("Sales Invoice", "Sales Order", "Quotation")


def credit_limit_problem(customer: str, company: str) -> Optional[str]:
    """Setting "Credit sale only for customers with a credit limit": ERPNext treats
    no limit as unlimited, so a customer without one could buy on credit."""
    from vansale.vansale.doctype.vansale_settings.vansale_settings import global_flags

    if not global_flags().get("credit_needs_limit"):
        return None
    from erpnext.selling.doctype.customer.customer import get_credit_limit

    if flt(get_credit_limit(customer, company)) > 0:
        return None
    return _("{0} has no credit limit: sell for cash, or ask the office for a credit limit.").format(customer)


def over_limit_message(
    doctype: str, customer: str, company: str, amount: float, payment_type: Optional[str]
) -> Optional[tuple[str, bool]]:
    """ERPNext's credit-limit check, run ahead: what the customer owes (unpaid
    invoices + open orders) plus the unpaid part of this sale, against the
    limit. (message, hard): hard unless the user holds the Credit Controller
    role, who ERPNext lets through."""
    from frappe.utils import fmt_money

    from vansale import steelforce

    if flt(amount) <= 0 or not customer or not company:
        return None
    # Steel Force: a cash sale never counts against the limit.
    if (payment_type or "").lower() == "cash" and steelforce.is_active():
        return None
    from erpnext.selling.doctype.customer.customer import get_credit_limit, get_customer_outstanding

    limit = flt(get_credit_limit(customer, company))
    if limit <= 0:
        return None
    # "Bypass credit limit check at Sales Order": the order isn't checked, its invoice is.
    if doctype == "Sales Order" and frappe.db.get_value(
        "Customer Credit Limit",
        {"parent": customer, "parenttype": "Customer", "company": company},
        "bypass_credit_limit_check",
    ):
        return None
    used = flt(get_customer_outstanding(customer, company))
    if used + flt(amount) <= limit + 0.005:
        return None
    message = _("Over the credit limit: {0} owes {1}, this sale adds {2}, the limit is {3}.").format(
        customer, fmt_money(used), fmt_money(amount), fmt_money(limit)
    )
    controller = frappe.db.get_single_value("Accounts Settings", "credit_controller")
    return message, not (controller and controller in frappe.get_roles())


def check_credit_allowed(customer: str, company: str) -> None:
    """Server-side guard for the same rule, on save."""
    problem = credit_limit_problem(customer, company)
    if problem:
        frappe.throw(problem, title=_("Credit not allowed"))


@frappe.whitelist(methods=["POST"])
def check(
    doctype: str,
    customer: str,
    payment_type: Optional[str] = None,
    lines: Optional[list[dict[str, Any]]] = None,
    amount: Optional[float] = None,
    from_order: Optional[int] = None,
) -> dict:
    """{"problems": [...], "warnings": [...]} for a sale about to be submitted.

    `amount`: the part of the sale left unpaid (the whole order for an order),
    for the credit-limit check. `from_order`: an invoice made from an order,
    which ERPNext does not check again (the order was)."""
    from vansale import steelforce
    from vansale.api.access import check_read
    from vansale.api.invoice import _user_company

    if doctype not in _DOCTYPES:
        frappe.throw(_("Cannot check {0}").format(doctype))
    if not customer:
        return {"problems": [], "warnings": []}
    check_read("Customer", customer)
    lines = lines or []

    problems: list[str] = []
    warnings: list[str] = []
    if (payment_type or "").lower() in ("credit", "cheque") and doctype != "Quotation":
        problem = credit_limit_problem(customer, _user_company())
        if problem:
            problems.append(problem)
    if doctype != "Quotation" and not frappe.utils.cint(from_order):
        over = over_limit_message(doctype, customer, _user_company(), flt(amount), payment_type)
        if over:
            (problems if over[1] else warnings).append(over[0])

    extra = steelforce.precheck(doctype, customer, payment_type, lines, flt(amount))
    for text in extra.get("problems") or []:
        if text and text not in problems:
            problems.append(text)
    for text in extra.get("warnings") or []:
        if text and text not in warnings:
            warnings.append(text)
    return {"problems": problems, "warnings": warnings}
