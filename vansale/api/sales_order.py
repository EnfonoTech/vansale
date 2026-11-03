"""Sales Order endpoints.

An order is taken for a Customer (directly, or from a quotation —
`quotation.make_order`) and becomes a Sales Invoice with `make_invoice`,
which the existing invoice screens then take through payment.
"""

from __future__ import annotations

from typing import Any, Optional

import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, getdate, nowdate

from vansale.api import selling
from vansale.api.access import check_read, readable_doc
from vansale.api.invoice import _get_default_warehouse, _user_company
from vansale.api.outbox import claim

_LIST_FIELDS = [
    "name", "customer", "customer_name", "grand_total", "status", "transaction_date",
    "delivery_date", "per_delivered", "per_billed", "docstatus", "modified",
]


def _fill(doc, items, delivery_date, remarks, discount_amount, warehouse) -> None:
    if delivery_date:
        doc.delivery_date = getdate(delivery_date)
    if remarks is not None:
        doc.terms = remarks or None
    if warehouse:
        doc.set_warehouse = warehouse
    selling.prepare_lines(doc, items, doc.set_warehouse, doc.delivery_date)
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
    customer: str,
    items: list[dict[str, Any]],
    delivery_date: Optional[str] = None,
    warehouse: Optional[str] = None,
    remarks: Optional[str] = None,
    discount_amount: Optional[float] = None,
    submit: int = 0,
    posting_ts: Optional[str] = None,
) -> dict:
    if not client_id:
        frappe.throw(_("client_id is required"))
    if not customer:
        frappe.throw(_("Customer is required"))
    if not items:
        frappe.throw(_("At least one item is required"))
    check_read("Customer", customer)

    existing = claim(client_id, "sales_order", "Sales Order")
    if existing:
        return _result(frappe.get_doc("Sales Order", existing), replay=True)

    company = _user_company()
    doc = frappe.new_doc("Sales Order")
    doc.customer = customer
    doc.company = company
    doc.order_type = "Sales"
    doc.transaction_date = nowdate()
    doc.delivery_date = getdate(delivery_date) if delivery_date else add_days(nowdate(), 7)
    template = selling.tax_template(customer, company, doc.transaction_date)
    if template:
        doc.taxes_and_charges = template
    _fill(doc, items, delivery_date, remarks, discount_amount, warehouse or _get_default_warehouse(company))
    doc.insert()
    if cint(submit):
        doc.submit()

    selling.record_outbox(client_id, "sales_order", "Sales Order", doc.name, posting_ts, {
        "customer": customer, "items": items,
    })
    frappe.db.commit()
    return _result(doc)


@frappe.whitelist(methods=["POST"])
def update_draft(
    name: str,
    items: list[dict[str, Any]],
    delivery_date: Optional[str] = None,
    warehouse: Optional[str] = None,
    remarks: Optional[str] = None,
    discount_amount: Optional[float] = None,
    submit: int = 0,
) -> dict:
    if not items:
        frappe.throw(_("At least one item is required"))
    doc = selling.own_draft("Sales Order", name, "edit")
    _fill(doc, items, delivery_date, remarks, discount_amount, warehouse or doc.set_warehouse)
    doc.flags.ignore_version = True
    doc.save()
    if cint(submit):
        doc.submit()
    frappe.db.commit()
    return _result(doc)


@frappe.whitelist(methods=["POST"])
def submit_draft(name: str) -> dict:
    """Submit a stored draft. Loads by name — never `frappe.client.submit` (see ARCHITECTURE §2)."""
    doc = selling.own_draft("Sales Order", name, "submit")
    doc.submit()
    frappe.db.commit()
    return _result(doc)


@frappe.whitelist(methods=["GET"])
def list_mine(
    limit: int = 50,
    search: Optional[str] = None,
    status: Optional[str] = None,
    customer: Optional[str] = None,
) -> list[dict]:
    filters: dict = {"owner": frappe.session.user, "docstatus": ["in", [0, 1]]}
    if status:
        filters["status"] = status
    if customer:
        filters["customer"] = customer
    rows = frappe.get_all(
        "Sales Order",
        filters=filters,
        or_filters=selling.search_filters(search, ("customer_name", "customer")),
        fields=_LIST_FIELDS,
        order_by="transaction_date desc, modified desc",
        limit=cint(limit) or 50,
    )
    for r in rows:
        r["modified"] = selling.naive_site_to_utc_iso(r.get("modified"))
    return rows


@frappe.whitelist(methods=["GET"])
def detail(name: str) -> dict:
    doc = readable_doc("Sales Order", name)
    invoices = frappe.get_all(
        "Sales Invoice Item",
        filters={"sales_order": doc.name, "docstatus": ["<", 2]},
        pluck="parent",
        distinct=True,
    )
    return {
        "name": doc.name,
        "customer": doc.customer,
        "party_name": doc.customer_name or doc.customer,
        "company": doc.company,
        "transaction_date": str(doc.transaction_date) if doc.transaction_date else None,
        "delivery_date": str(doc.delivery_date) if doc.delivery_date else None,
        "status": doc.status,
        "docstatus": cint(doc.docstatus),
        "per_delivered": flt(doc.per_delivered),
        "per_billed": flt(doc.per_billed),
        "remarks": doc.terms,
        "warehouse": doc.set_warehouse,
        **selling.totals(doc),
        "items": selling.line_rows(doc),
        "taxes": selling.tax_rows(doc),
        "invoices": invoices,
        "modified": selling.stamp(doc),
    }


@frappe.whitelist(methods=["POST"])
def make_invoice(client_id: str, name: str) -> dict:
    """Draft Sales Invoice for what the order has not billed yet.

    Left as a draft on purpose: cash / credit, payment mode and the van's
    stock check happen in the invoice form, which already handles them.
    """
    if not client_id:
        frappe.throw(_("client_id is required"))
    order = readable_doc("Sales Order", name)
    if cint(order.docstatus) != 1:
        frappe.throw(_("Submit the order before invoicing it"))

    existing = claim(client_id, "invoice", "Sales Invoice")
    if existing:
        return {"name": existing, "idempotent_replay": True}

    from erpnext.selling.doctype.sales_order.sales_order import make_sales_invoice

    invoice = make_sales_invoice(order.name)
    company = invoice.company
    warehouse = order.set_warehouse or _get_default_warehouse(company)
    # The van ships what it invoices — unless a Delivery Note already did.
    invoice.update_stock = 0 if flt(order.per_delivered) > 0 else 1
    if invoice.update_stock and warehouse:
        invoice.set_warehouse = warehouse
        for row in invoice.items:
            row.warehouse = row.warehouse or warehouse
    invoice.custom_client_id = client_id
    selling.tag_sales_person(invoice)
    invoice.insert()

    selling.record_outbox(client_id, "invoice", "Sales Invoice", invoice.name, None, {"sales_order": order.name})
    frappe.db.commit()
    return {
        "name": invoice.name,
        "grand_total": flt(invoice.grand_total),
        "status": invoice.status,
        "docstatus": cint(invoice.docstatus),
        "idempotent_replay": False,
    }
