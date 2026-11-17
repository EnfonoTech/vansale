"""Steel Force adapter: how the app works next to the `sf_trading` app.

Branch `develop_2` only. sf_trading owns Steel Force's business rules (branch,
minimum price, credit, customer approval, return reasons, ...). This module
never re-implements one: it fills the fields those rules read and uses
sf_trading's own functions where they exist.

Every function here is safe on a site without sf_trading: it checks for the
field / app it needs and otherwise leaves the standard behaviour alone. The
standard modules call in at a few points only, so merging `develop` into
`develop_2` stays easy.
"""

from __future__ import annotations

from typing import Optional

import frappe

SF_APP = "sf_trading"


def is_active() -> bool:
    """sf_trading is installed on this site."""
    return SF_APP in frappe.get_installed_apps()


# ─── Payment mode on the document ─────────────────────────────────────────────

_PAYMENT_MODE_FIELD = "custom_payment_mode"


def set_payment_mode(doc, pay_type: Optional[str]) -> None:
    """sf_trading's `custom_payment_mode` (Cash / Credit / Cheque) on a Sales
    Invoice / Sales Order. The field defaults to its first option (Cash) when
    nothing is sent, so a credit sale must say Credit explicitly; sf_trading's
    credit, cash-limit and due-date rules all read it."""
    if not doc.meta.has_field(_PAYMENT_MODE_FIELD):
        return
    value = {"cash": "Cash", "credit": "Credit", "cheque": "Cheque"}.get((pay_type or "").lower())
    if value:
        doc.set(_PAYMENT_MODE_FIELD, value)


def payment_type_of(doc) -> Optional[str]:
    """"cash" / "credit" from `custom_payment_mode`, or None when the site has no
    such field (the caller then derives it the standard way). A cheque is a
    credit sale to sf_trading (post-dated), so the app shows it as credit."""
    if not doc.meta.has_field(_PAYMENT_MODE_FIELD) or not doc.get(_PAYMENT_MODE_FIELD):
        return None
    return "cash" if doc.get(_PAYMENT_MODE_FIELD) == "Cash" else "credit"


# ─── New customers ────────────────────────────────────────────────────────────

def on_new_customer(doc, company: Optional[str] = None) -> None:
    """sf_trading shows a branch user only the customers of their company
    (`custom_company`); the desk fills it in the browser, so an API-created
    customer must carry it or it disappears from the salesman's lists."""
    if doc.meta.has_field("custom_company") and not doc.get("custom_company"):
        from vansale.api.invoice import _user_company

        doc.custom_company = company or _user_company()


# ─── Return reasons ───────────────────────────────────────────────────────────

_REASON_TEMPLATE_FIELD = "custom_return_reason_template"
_REASON_DOCTYPE = "Sales Return Reason"


def _uses_reason_master() -> bool:
    return bool(
        frappe.get_meta("Sales Invoice").has_field(_REASON_TEMPLATE_FIELD)
        and frappe.db.exists("DocType", _REASON_DOCTYPE)
    )


def return_reason_options() -> list[str]:
    """The reasons a salesman picks from: sf_trading's *Sales Return Reason*
    list on its sites, else the app's own list."""
    if _uses_reason_master():
        names = frappe.get_all(_REASON_DOCTYPE, pluck="name", order_by="name asc")
        if names:
            # "Other" last, as in the app's own list
            return [n for n in names if n != "Other"] + (["Other"] if "Other" in names else [])
    from vansale.api.sales_return import RETURN_REASONS

    return list(RETURN_REASONS)


def set_return_reason(doc, reason_option: str, reason_text: str, note: Optional[str]) -> bool:
    """Write the reason the sf_trading way (template link + free text).
    Returns False when the site doesn't use the reason master, so the caller
    keeps the standard behaviour."""
    if not _uses_reason_master():
        return False
    if frappe.db.exists(_REASON_DOCTYPE, reason_option):
        doc.set(_REASON_TEMPLATE_FIELD, reason_option)
    elif frappe.db.exists(_REASON_DOCTYPE, "Other"):
        doc.set(_REASON_TEMPLATE_FIELD, "Other")
    extra = (note or "").strip()
    detail = extra or (reason_text if reason_text != reason_option else "")
    if detail and doc.meta.get_field("custom_return_reason") and doc.meta.get_field(
        "custom_return_reason"
    ).fieldtype in ("Data", "Small Text", "Text"):
        doc.custom_return_reason = detail
    return True


def copy_to_return(doc, original) -> None:
    """A credit note keeps the original sale's sales person (targets and
    commission net off against it) and payment mode (sf_trading treats a cash
    return and a credit return differently)."""
    for field in ("custom_sales_person", _PAYMENT_MODE_FIELD):
        if doc.meta.has_field(field) and original.get(field) and not doc.get(field):
            doc.set(field, original.get(field))


# ─── Quotation → Sales Invoice ────────────────────────────────────────────────

def invoice_from_quotation(quotation_name: str, customer: str):
    """Unsaved Sales Invoice for a submitted quotation.

    Steel Force: a customer's quotation goes through sf_trading's own mapping
    (the desk's "Sales Invoice" button). sf_trading has no lead quotations, and
    its mapping can't take one (it bills the party, i.e. the lead), so a
    lead's quotation goes through ERPNext's mapping and gets sf_trading's
    row link (`custom_quotation`) stamped on, which is what drives the
    quotation's status and the one-invoice-per-quotation check.
    Elsewhere: ERPNext's mapping. `customer` is the quotation's customer, or
    the customer its lead was just converted into.
    """
    from erpnext.selling.doctype.quotation.quotation import make_sales_invoice

    linked = is_active() and frappe.get_meta("Sales Invoice Item").has_field("custom_quotation")
    if not linked:
        return make_sales_invoice(quotation_name)

    if frappe.db.get_value("Quotation", quotation_name, "quotation_to") == "Customer":
        from sf_trading.api.quotation import make_sales_invoice_from_quotation

        return frappe.get_doc(make_sales_invoice_from_quotation(quotation_name))

    existing = invoices_for_quotation(quotation_name)
    if existing:
        frappe.throw(
            frappe._("A Sales Invoice {0} already exists for Quotation {1}.").format(
                frappe.bold(existing[0]), quotation_name
            ),
            title=frappe._("Duplicate Invoice"),
        )
    invoice = make_sales_invoice(quotation_name)
    if invoice.customer != customer:
        invoice.customer = customer
        invoice.run_method("set_missing_values")
    for row in invoice.items:
        row.custom_quotation = quotation_name
    return invoice


def invoices_for_quotation(quotation_name: str) -> list[str]:
    """Sales Invoices made straight from a quotation (sf_trading links their
    rows through `custom_quotation`); [] on sites without that link."""
    if not frappe.get_meta("Sales Invoice Item").has_field("custom_quotation"):
        return []
    return frappe.get_all(
        "Sales Invoice Item",
        filters={"custom_quotation": quotation_name, "docstatus": ["<", 2]},
        pluck="parent",
        distinct=True,
    )


def draft_sale_printable() -> bool:
    """sf_trading refuses to print a draft Sales Invoice (a draft return still
    prints), so the app hides Print on draft sales there."""
    if not is_active():
        return True
    try:
        from sf_trading import draft_print  # noqa: F401
    except ImportError:
        return True
    return "sf_trading.draft_print.block_draft_sale_print" not in str(
        frappe.get_hooks("doc_events").get("Sales Invoice", {}).get("before_print", "")
    )
