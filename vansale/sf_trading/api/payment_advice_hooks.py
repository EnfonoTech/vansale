# apps/vansale/vansale/sf_trading/api/payment_advice_hooks.py
"""Keep a Payment Advice in step with the Payment Entry raised from it.

Stamping happens on the Payment Entry's `on_submit` — not `before_submit` as the original
payment_advice app did — so a submit that fails validation cannot leave the advice pointing
at a Payment Entry that never posted. `on_cancel` reverses the stamp and puts the advice back
to Approved, so a corrected payment can be raised again.

The advice fields written here (`payment_entry`, `payment_entry_date`, `status`) all carry
allow_on_submit, and they are written with `db_set` rather than `save()` so the submitted
advice is not re-validated and its `modified` timestamp does not fight a concurrent save.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt

from vansale.sf_trading.doctype.payment_advice.payment_advice import (
    refresh_reference_status,
)

ADVICE_FIELD = "custom_payment_advice"

STATUS_APPROVED = "Approved"
STATUS_PARTLY_PAID = "Partly Paid"
STATUS_PAID = "Paid"


def _advice_name(doc):
    return (doc.get(ADVICE_FIELD) or "").strip()


def _load_advice(name):
    if not name or not frappe.db.exists("Payment Advice", name):
        return None
    return frappe.get_doc("Payment Advice", name)


def on_payment_entry_submit(doc, method=None):
    """Record the Payment Entry on its Payment Advice and move the advice's status on."""
    name = _advice_name(doc)
    if not name:
        return

    advice = _load_advice(name)
    if not advice:
        frappe.log_error(
            _("Payment Entry %(pe)s references missing Payment Advice %(advice)s")
            % {"pe": doc.name, "advice": name},
            "sf_trading: payment advice missing",
        )
        return

    if cint(advice.docstatus) != 1:
        frappe.throw(
            _("Payment Advice %s must be submitted before its Payment Entry can be submitted.")
            % frappe.bold(name)
        )

    status = (
        STATUS_PAID
        if flt(doc.paid_amount) >= flt(advice.payment_amount)
        else STATUS_PARTLY_PAID
    )

    advice.db_set(
        {
            "payment_entry": doc.name,
            "payment_entry_date": doc.posting_date,
            "status": status,
        },
        update_modified=False,
    )

    # invoices have just been part/fully paid by this PE — pull their new status through
    refresh_reference_status(advice.name)


def on_payment_entry_cancel(doc, method=None):
    """Reverse the stamp so a fresh Payment Entry can be raised for the same advice."""
    name = _advice_name(doc)
    if not name:
        return

    advice = _load_advice(name)
    if not advice:
        return

    if advice.payment_entry and advice.payment_entry != doc.name:
        # the advice has since moved to another Payment Entry — leave it alone
        return

    advice.db_set(
        {
            "payment_entry": None,
            "payment_entry_date": None,
            "status": STATUS_APPROVED if cint(advice.docstatus) == 1 else advice.status,
        },
        update_modified=False,
    )

    # the cancellation restored the invoices' outstanding — reflect that on the advice
    refresh_reference_status(advice.name)


def validate_payment_entry_advice(doc, method=None):
    """Guard against two live Payment Entries claiming the same advice."""
    name = _advice_name(doc)
    if not name:
        return

    clash = frappe.get_all(
        "Payment Entry",
        filters={
            ADVICE_FIELD: name,
            "docstatus": 1,
            "name": ["!=", doc.name],
        },
        pluck="name",
        limit=1,
    )
    if clash:
        frappe.throw(
            _("Payment Advice %(advice)s is already paid by Payment Entry %(pe)s.")
            % {"advice": frappe.bold(name), "pe": frappe.bold(clash[0])}
        )
