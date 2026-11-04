"""Shared plumbing for the pre-invoice sales cycle: Quotation and Sales Order.

Lead → Quotation → Sales Order → Sales Invoice → Payment / Return. Invoice,
Payment and Return have their own modules; the two documents in front of them
are near-identical (customer, lines, tax, discount, validity / delivery date),
so their endpoints share the builders here and differ only in the few fields
that are really different.

Every write is idempotent by `client_id` through `vansale.api.outbox.claim`,
like the invoice endpoints. Reads are scoped to the salesman's own documents
(owner) or whatever Frappe's permissions let him read.
"""

from __future__ import annotations

from typing import Any, Optional

import frappe
from frappe import _
from frappe.utils import cint, flt

from vansale.api.datetime_util import naive_site_to_utc_iso, parse_client_ts
from vansale.api.me import current_user_sales_person


def record_outbox(
    client_id: Optional[str],
    event_type: str,
    ref_doctype: str,
    ref_name: str,
    posting_ts: Optional[str],
    payload: dict,
) -> None:
    """Fill in the outbox row `claim` reserved, once the document exists."""
    if not client_id:
        return
    if frappe.db.exists("Vansale Outbox", client_id):
        doc = frappe.get_doc("Vansale Outbox", client_id)
    else:
        doc = frappe.new_doc("Vansale Outbox")
        doc.client_id = client_id
    doc.event_type = event_type
    doc.user = frappe.session.user
    doc.client_ts = parse_client_ts(posting_ts) if posting_ts else None
    doc.drained_at = frappe.utils.now_datetime()
    doc.status = "processed"
    doc.ref_doctype = ref_doctype
    doc.ref_name = ref_name
    doc.payload_json = frappe.as_json(payload)
    doc.save(ignore_permissions=True)


def own_draft(doctype: str, name: str, action: str):
    """Load a draft the user may change: theirs, or one they hold the permission for."""
    if not name:
        frappe.throw(_("name required"))
    doc = frappe.get_doc(doctype, name)
    if cint(doc.docstatus) != 0:
        frappe.throw(_("Only draft documents can be changed"))
    if doc.owner != frappe.session.user and not frappe.has_permission(doctype, "write", doc=doc):
        frappe.throw(_("You cannot {0} this document").format(action))
    return doc


def prepare_lines(doc, items: list[dict[str, Any]], warehouse: Optional[str], delivery_date=None) -> None:
    """Replace the document's lines with the client's, taxes and totals included.

    Pricing follows the invoice form: `price_list_rate` + `rate` so ERPNext
    derives the discount. A missing/zero qty is rejected, never defaulted to 1.
    """
    from vansale.api.invoice import _append_items, _apply_template_taxes

    doc.set("items", [])
    _append_items(doc, items, warehouse)
    if delivery_date is not None:
        for row in doc.items:
            row.delivery_date = delivery_date
    _apply_template_taxes(doc)


def tag_sales_person(doc) -> None:
    # Quotation has no sales team table; Sales Order and Sales Invoice do.
    if not doc.meta.has_field("sales_team"):
        return
    sp = current_user_sales_person()
    if sp and not doc.get("sales_team"):
        doc.append("sales_team", {"sales_person": sp, "allocated_percentage": 100})


def discount(doc, amount: Optional[float]) -> None:
    from vansale.api.invoice import _set_additional_discount

    _set_additional_discount(doc, amount)


def tax_template(party_customer: Optional[str], company: str, date) -> Optional[str]:
    from vansale.api.invoice import _resolve_tax_template

    return _resolve_tax_template(party_customer, company, date)


def line_rows(doc) -> list[dict]:
    return [
        {
            "name": i.name,
            "item_code": i.item_code,
            "item_name": i.item_name,
            "qty": flt(i.qty),
            "uom": i.uom,
            "conversion_factor": flt(i.conversion_factor) or 1.0,
            "stock_uom": i.stock_uom,
            "rate": flt(i.rate),
            "price_list_rate": flt(i.price_list_rate),
            "discount_percentage": flt(i.discount_percentage),
            "amount": flt(i.amount),
            "warehouse": i.get("warehouse"),
            "delivered_qty": flt(i.get("delivered_qty")),
        }
        for i in doc.items
    ]


def tax_rows(doc) -> list[dict]:
    return [
        {
            "description": t.description,
            "rate": flt(t.rate),
            "tax_amount": flt(
                t.tax_amount_after_discount_amount
                if t.tax_amount_after_discount_amount is not None
                else t.tax_amount
            ),
            "total": flt(t.total),
        }
        for t in (doc.taxes or [])
    ]


def totals(doc) -> dict:
    return {
        "currency": doc.currency,
        "net_total": flt(doc.net_total),
        "total_taxes_and_charges": flt(doc.total_taxes_and_charges),
        "discount_amount": flt(doc.discount_amount),
        "grand_total": flt(doc.rounded_total) or flt(doc.grand_total),
    }


def stamp(doc) -> str:
    return naive_site_to_utc_iso(doc.modified)


def search_filters(search: Optional[str], extra: tuple[str, ...]) -> Optional[dict]:
    s = (search or "").strip()
    if not s:
        return None
    return {f: ["like", f"%{s}%"] for f in ("name", *extra)}
