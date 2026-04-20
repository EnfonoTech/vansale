"""Sales Invoice endpoints.

`save` is idempotent by `client_id` — if the client already queued an
invoice with this UUID and we succeed later, re-submitting the same
`client_id` returns the already-saved doc rather than creating a duplicate.
That's the contract the Phase 2 drain engine relies on.
"""

from __future__ import annotations

from typing import Any, Optional

import frappe
from frappe import _

from vansale.api.datetime_util import naive_site_to_utc_iso, parse_client_ts


def _user_default(allow: str) -> Optional[str]:
    return frappe.db.get_value(
        "User Permission",
        {"user": frappe.session.user, "allow": allow, "is_default": 1},
        "for_value",
    )


def _get_default_warehouse(company: str) -> Optional[str]:
    """Prefer the Van User's configured warehouse; fall back to company / stock default."""
    return (
        _user_default("Warehouse")
        or frappe.db.get_value("Company", company, "default_warehouse")
        or frappe.db.get_single_value("Stock Settings", "default_warehouse")
    )


def _user_company() -> str:
    return (
        _user_default("Company")
        or frappe.defaults.get_user_default("Company", frappe.session.user)
        or frappe.db.get_single_value("Global Defaults", "default_company")
    )


def _default_tax_template(company: str) -> Optional[str]:
    """Resolve the Company's default Sales Taxes and Charges Template.

    Some sites enforce taxes_and_charges as mandatory (either directly
    or via customisations like fateh_trading on this bench). Rather
    than surface a cryptic error to the van user we auto-pick the
    company's default.
    """
    return frappe.db.get_value(
        "Sales Taxes and Charges Template",
        {"company": company, "is_default": 1, "disabled": 0},
        "name",
    ) or frappe.db.get_value(
        "Sales Taxes and Charges Template",
        {"company": company, "disabled": 0},
        "name",
        order_by="modified desc",
    )


def _existing_by_client_id(client_id: str) -> Optional[str]:
    """Look up a prior submission of the same idempotency key."""
    if not client_id:
        return None
    name = frappe.db.get_value("Vansale Outbox", {"client_id": client_id}, "ref_name")
    if name and frappe.db.exists("Sales Invoice", name):
        return name
    return None


def _record_outbox(client_id: str, ref_name: str, posting_ts: Optional[str], payload: dict) -> None:
    if not client_id:
        return
    if frappe.db.exists("Vansale Outbox", client_id):
        doc = frappe.get_doc("Vansale Outbox", client_id)
    else:
        doc = frappe.new_doc("Vansale Outbox")
        doc.client_id = client_id
    doc.event_type = "invoice"
    doc.user = frappe.session.user
    doc.client_ts = parse_client_ts(posting_ts) if posting_ts else None
    doc.drained_at = frappe.utils.now_datetime()
    doc.status = "processed"
    doc.ref_doctype = "Sales Invoice"
    doc.ref_name = ref_name
    doc.payload_json = frappe.as_json(payload)
    doc.save(ignore_permissions=True)


@frappe.whitelist(methods=["POST"])
def save(
    client_id: str,
    customer: str,
    items: list[dict[str, Any]],
    posting_ts: Optional[str] = None,
    warehouse: Optional[str] = None,
    remarks: Optional[str] = None,
    update_stock: int = 1,
    submit: int = 1,
) -> dict:
    if not client_id:
        frappe.throw(_("client_id is required"))
    if not customer:
        frappe.throw(_("Customer is required"))
    if not items:
        frappe.throw(_("At least one item is required"))

    existing = _existing_by_client_id(client_id)
    if existing:
        doc = frappe.get_doc("Sales Invoice", existing)
        return {
            "name": doc.name,
            "grand_total": float(doc.grand_total or 0),
            "status": doc.status,
            "modified": naive_site_to_utc_iso(doc.modified),
            "idempotent_replay": True,
        }

    company = _user_company()
    set_warehouse = warehouse or _get_default_warehouse(company)

    posting = parse_client_ts(posting_ts) if posting_ts else frappe.utils.now_datetime()

    doc = frappe.new_doc("Sales Invoice")
    doc.customer = customer
    doc.company = company
    doc.set_posting_time = 1
    doc.posting_date = posting.date()
    doc.posting_time = posting.strftime("%H:%M:%S")
    doc.update_stock = int(bool(update_stock))
    doc.set_warehouse = set_warehouse
    doc.remarks = remarks
    doc.custom_client_id = client_id  # custom field added via fixture

    # Tax template — auto-apply if the site enforces mandatory taxes
    # and the caller didn't supply one.
    tax_template = _default_tax_template(company)
    if tax_template:
        doc.taxes_and_charges = tax_template

    for item in items:
        if not item.get("item_code"):
            frappe.throw(_("item_code is required on every line"))
        row = doc.append("items", {})
        row.item_code = item["item_code"]
        row.qty = float(item.get("qty") or 1)
        if item.get("rate") is not None:
            row.rate = float(item["rate"])
        row.uom = item.get("uom") or row.uom
        if set_warehouse:
            row.warehouse = item.get("warehouse") or set_warehouse

    doc.insert(ignore_permissions=False)
    if submit:
        doc.submit()

    _record_outbox(client_id, doc.name, posting_ts, {
        "customer": customer,
        "items": items,
        "warehouse": set_warehouse,
    })
    frappe.db.commit()

    return {
        "name": doc.name,
        "grand_total": float(doc.grand_total or 0),
        "status": doc.status,
        "modified": naive_site_to_utc_iso(doc.modified),
        "idempotent_replay": False,
    }


@frappe.whitelist(methods=["GET"])
def list_mine(limit: int = 50, customer: Optional[str] = None) -> list[dict]:
    filters: dict = {"owner": frappe.session.user, "docstatus": ["in", [0, 1]]}
    if customer:
        filters["customer"] = customer
    rows = frappe.get_all(
        "Sales Invoice",
        filters=filters,
        fields=[
            "name",
            "customer",
            "customer_name",
            "grand_total",
            "outstanding_amount",
            "status",
            "posting_date",
            "posting_time",
            "modified",
        ],
        order_by="posting_date desc, posting_time desc",
        limit=int(limit),
    )
    for r in rows:
        r["modified"] = naive_site_to_utc_iso(r.get("modified"))
    return rows


@frappe.whitelist(methods=["GET"])
def detail(name: str) -> dict:
    doc = frappe.get_doc("Sales Invoice", name)
    return {
        "name": doc.name,
        "customer": doc.customer,
        "customer_name": doc.customer_name,
        "grand_total": float(doc.grand_total or 0),
        "net_total": float(doc.net_total or 0),
        "total_taxes_and_charges": float(doc.total_taxes_and_charges or 0),
        "outstanding_amount": float(doc.outstanding_amount or 0),
        "status": doc.status,
        "items": [
            {
                "item_code": i.item_code,
                "item_name": i.item_name,
                "qty": float(i.qty or 0),
                "rate": float(i.rate or 0),
                "amount": float(i.amount or 0),
                "uom": i.uom,
                "warehouse": i.warehouse,
            }
            for i in doc.items
        ],
        "modified": naive_site_to_utc_iso(doc.modified),
    }
