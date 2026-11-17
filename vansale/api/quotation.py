"""Quotation endpoints.

A quotation is addressed to a Customer or to a Lead (`quotation_to`), as in
ERPNext. A lead stays a lead while it is only quoted; when its quotation
becomes a Sales Order (`make_order`) or a Sales Invoice (`make_invoice`) the
lead is converted into a Customer. Which of the two the app offers is the
"Quotation becomes" setting.
"""

from __future__ import annotations

from typing import Any, Optional

import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, getdate, nowdate

from vansale.api import selling
from vansale.api.access import check_read, readable_doc
from vansale.api.doc_defaults import apply_van_defaults
from vansale.api.invoice import _get_default_warehouse, _user_company
from vansale.api.me import quotation_next_step, update_stock_enabled
from vansale.api.outbox import claim
from vansale import steelforce

_LIST_FIELDS = [
    "name", "quotation_to", "party_name", "customer_name", "grand_total", "status",
    "transaction_date", "valid_till", "docstatus", "modified",
]


def _check_party(quotation_to: str, party: str) -> None:
    if quotation_to not in ("Customer", "Lead"):
        frappe.throw(_("Quotation can be made for a Customer or a Lead"))
    if not party:
        frappe.throw(_("Pick a customer or a lead"))
    check_read(quotation_to, party)


def _fill(doc, items, valid_till, remarks, discount_amount) -> None:
    if valid_till:
        doc.valid_till = getdate(valid_till)
    if remarks is not None:
        # Neither document has a remarks field; Terms is the free-text one.
        doc.terms = remarks or None
    selling.prepare_lines(doc, items, None)
    selling.tag_sales_person(doc)
    selling.discount(doc, discount_amount)


def _result(doc, replay: bool = False) -> dict:
    return {
        "name": doc.name,
        "grand_total": selling.totals(doc)["grand_total"],
        "status": doc.status,
        "docstatus": cint(doc.docstatus),
        "modified": selling.stamp(doc),
        "idempotent_replay": replay,
    }


@frappe.whitelist(methods=["POST"])
def save(
    client_id: str,
    party: str,
    items: list[dict[str, Any]],
    quotation_to: str = "Customer",
    valid_till: Optional[str] = None,
    remarks: Optional[str] = None,
    discount_amount: Optional[float] = None,
    submit: int = 0,
    posting_ts: Optional[str] = None,
) -> dict:
    if not client_id:
        frappe.throw(_("client_id is required"))
    if not items:
        frappe.throw(_("At least one item is required"))
    _check_party(quotation_to, party)

    existing = claim(client_id, "quotation", "Quotation")
    if existing:
        return _result(frappe.get_doc("Quotation", existing), replay=True)

    company = _user_company()
    doc = frappe.new_doc("Quotation")
    doc.quotation_to = quotation_to
    doc.party_name = party
    doc.company = company
    doc.order_type = "Sales"
    doc.transaction_date = nowdate()
    doc.valid_till = getdate(valid_till) if valid_till else add_days(nowdate(), 30)
    template = selling.tax_template(party if quotation_to == "Customer" else None, company, doc.transaction_date)
    if template:
        doc.taxes_and_charges = template
    _fill(doc, items, valid_till, remarks, discount_amount)
    doc.insert()
    if cint(submit):
        doc.submit()

    selling.record_outbox(client_id, "quotation", "Quotation", doc.name, posting_ts, {
        "party": party, "quotation_to": quotation_to, "items": items,
    })
    frappe.db.commit()
    return {**_result(doc), "customer": party if quotation_to == "Customer" else None}


@frappe.whitelist(methods=["POST"])
def update_draft(
    name: str,
    items: list[dict[str, Any]],
    valid_till: Optional[str] = None,
    remarks: Optional[str] = None,
    discount_amount: Optional[float] = None,
    submit: int = 0,
) -> dict:
    if not items:
        frappe.throw(_("At least one item is required"))
    doc = selling.own_draft("Quotation", name, "edit")
    _fill(doc, items, valid_till, remarks, discount_amount)
    doc.flags.ignore_version = True
    doc.save()
    if cint(submit):
        doc.submit()
    frappe.db.commit()
    return _result(doc)


@frappe.whitelist(methods=["POST"])
def submit_draft(name: str) -> dict:
    """Submit a stored draft. Loads by name — never `frappe.client.submit` (see ARCHITECTURE §2)."""
    doc = selling.own_draft("Quotation", name, "submit")
    doc.submit()
    frappe.db.commit()
    return _result(doc)


@frappe.whitelist(methods=["POST"])
def mark_lost(name: str, reason: Optional[str] = None) -> dict:
    """The customer turned the quote down — close it so it stops showing as open."""
    doc = readable_doc("Quotation", name)
    if cint(doc.docstatus) != 1:
        frappe.throw(_("Only a submitted quotation can be marked lost"))
    lost = (reason or "").strip()
    reasons = [{"lost_reason": lost}] if lost and frappe.db.exists("Quotation Lost Reason", lost) else []
    doc.declare_enquiry_lost(reasons, [], lost or None)
    frappe.db.commit()
    return _result(doc)


@frappe.whitelist(methods=["GET"])
def list_mine(
    limit: int = 50,
    search: Optional[str] = None,
    status: Optional[str] = None,
    party: Optional[str] = None,
) -> list[dict]:
    filters: dict = {"owner": frappe.session.user, "docstatus": ["in", [0, 1]]}
    if status:
        filters["status"] = status
    if party:
        filters["party_name"] = party
    rows = frappe.get_all(
        "Quotation",
        filters=filters,
        or_filters=selling.search_filters(search, ("customer_name", "party_name")),
        fields=_LIST_FIELDS,
        order_by="transaction_date desc, modified desc",
        limit=cint(limit) or 50,
    )
    for r in rows:
        r["modified"] = selling.naive_site_to_utc_iso(r.get("modified"))
    return rows


@frappe.whitelist(methods=["GET"])
def detail(name: str) -> dict:
    doc = readable_doc("Quotation", name)
    orders = frappe.get_all(
        "Sales Order Item",
        filters={"prevdoc_docname": doc.name, "docstatus": ["<", 2]},
        pluck="parent",
        distinct=True,
    )
    return {
        "name": doc.name,
        "quotation_to": doc.quotation_to,
        "party": doc.party_name,
        "party_name": doc.customer_name or doc.party_name,
        "customer": doc.party_name if doc.quotation_to == "Customer" else None,
        "company": doc.company,
        "transaction_date": str(doc.transaction_date) if doc.transaction_date else None,
        "valid_till": str(doc.valid_till) if doc.valid_till else None,
        "status": doc.status,
        "docstatus": cint(doc.docstatus),
        "remarks": doc.terms,
        **selling.totals(doc),
        "items": selling.line_rows(doc),
        "taxes": selling.tax_rows(doc),
        "orders": orders,
        "invoices": steelforce.invoices_for_quotation(doc.name),
        "modified": selling.stamp(doc),
    }


@frappe.whitelist(methods=["POST"])
def make_order(client_id: str, name: str, delivery_date: Optional[str] = None, submit: int = 0) -> dict:
    """Sales Order from a submitted quotation (ERPNext `make_sales_order`).

    A lead's quotation converts the lead into a Customer first, in the same
    transaction, so a refused order leaves the lead untouched.
    """
    if not client_id:
        frappe.throw(_("client_id is required"))
    quotation = readable_doc("Quotation", name)
    if cint(quotation.docstatus) != 1:
        frappe.throw(_("Submit the quotation before making an order"))
    if quotation_next_step() == "Sales Invoice":
        frappe.throw(_("Quotations become invoices on this site, not orders"))
    if quotation.quotation_to not in ("Customer", "Lead"):
        frappe.throw(_("Only a customer or lead quotation can become an order"))

    existing = claim(client_id, "sales_order", "Sales Order")
    if existing:
        return {"name": existing, "idempotent_replay": True}

    converted = None
    if quotation.quotation_to == "Lead":
        # Our conversion rather than ERPNext's: the Customer `before_insert` hook
        # assigns the new customer to the salesman. `make_sales_order` then finds
        # it through the Customer's `lead_name`.
        from vansale.api.lead import ensure_customer

        customer, created = ensure_customer(readable_doc("Lead", quotation.party_name))
        converted = customer if created else None

    from erpnext.selling.doctype.quotation.quotation import make_sales_order

    order = make_sales_order(quotation.name)
    delivery = getdate(delivery_date) if delivery_date else add_days(nowdate(), 7)
    order.delivery_date = delivery
    for row in order.items:
        row.delivery_date = delivery
    apply_van_defaults(order)
    selling.tag_sales_person(order)
    order.insert()
    if cint(submit):
        order.submit()

    selling.record_outbox(client_id, "sales_order", "Sales Order", order.name, None, {"quotation": quotation.name})
    frappe.db.commit()
    return {
        "name": order.name,
        "grand_total": flt(order.grand_total),
        "status": order.status,
        "docstatus": cint(order.docstatus),
        "customer": order.customer,
        "converted_customer": converted,
        "idempotent_replay": False,
    }


def _quotation_customer(quotation) -> tuple[str, Optional[str]]:
    """(customer, customer converted now?) — a lead's quotation converts the lead."""
    if quotation.quotation_to == "Lead":
        from vansale.api.lead import ensure_customer

        customer, created = ensure_customer(readable_doc("Lead", quotation.party_name))
        return customer, (customer if created else None)
    return quotation.party_name, None


@frappe.whitelist(methods=["POST"])
def make_invoice(client_id: str, name: str) -> dict:
    """Draft Sales Invoice straight from a submitted quotation (no Sales Order),
    when the "Quotation becomes" setting allows it. Left as a draft: payment
    type, collection and submit happen in the invoice form, as for an order.
    """
    if not client_id:
        frappe.throw(_("client_id is required"))
    if quotation_next_step() == "Sales Order":
        frappe.throw(_("Quotations become sales orders on this site, not invoices"))
    quotation = readable_doc("Quotation", name)
    if cint(quotation.docstatus) != 1:
        frappe.throw(_("Submit the quotation before invoicing it"))
    if quotation.quotation_to not in ("Customer", "Lead"):
        frappe.throw(_("Only a customer or lead quotation can be invoiced"))

    existing = claim(client_id, "invoice", "Sales Invoice")
    if existing:
        return {"name": existing, "idempotent_replay": True}

    customer, converted = _quotation_customer(quotation)
    invoice = steelforce.invoice_from_quotation(quotation.name, customer)
    warehouse = _get_default_warehouse(invoice.company)
    invoice.update_stock = int(update_stock_enabled())
    if warehouse:
        invoice.set_warehouse = warehouse
        for row in invoice.items:
            row.warehouse = row.get("warehouse") or warehouse
    invoice.custom_client_id = client_id
    apply_van_defaults(invoice)
    selling.tag_sales_person(invoice)
    invoice.insert()

    selling.record_outbox(client_id, "invoice", "Sales Invoice", invoice.name, None, {"quotation": quotation.name})
    frappe.db.commit()
    return {
        "name": invoice.name,
        "grand_total": flt(invoice.grand_total),
        "status": invoice.status,
        "docstatus": cint(invoice.docstatus),
        "customer": invoice.customer,
        "converted_customer": converted,
        "idempotent_replay": False,
    }
