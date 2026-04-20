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
from vansale.api.me import current_user_sales_person


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
    payment_type: Optional[str] = None,       # "cash" | "credit" — drives is_pos + payments
    mode_of_payment: Optional[str] = None,    # used when payment_type == "cash"
    discount_amount: Optional[float] = None,  # invoice-level additional discount
    apply_discount_on: Optional[str] = None,  # "Grand Total" | "Net Total"
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

    # Cash / credit: cash → is_pos + fully paid via mode_of_payment.
    pay_type = (payment_type or "").lower()
    if pay_type == "cash":
        doc.is_pos = 1
        # payments row filled after insert so grand_total is known.

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
        if item.get("uom"):
            row.uom = item["uom"]
        if item.get("conversion_factor"):
            row.conversion_factor = float(item["conversion_factor"])
        # Price — prefer price_list_rate so ERPNext computes discount_percentage.
        if item.get("price_list_rate") is not None:
            row.price_list_rate = float(item["price_list_rate"])
        if item.get("rate") is not None:
            row.rate = float(item["rate"])
        if item.get("discount_percentage") is not None:
            row.discount_percentage = float(item["discount_percentage"])
        if item.get("discount_amount") is not None:
            row.discount_amount = float(item["discount_amount"])
        if set_warehouse:
            row.warehouse = item.get("warehouse") or set_warehouse

    # Auto-tag sales person (commission tracking) if configured.
    sp = current_user_sales_person()
    if sp:
        doc.append("sales_team", {"sales_person": sp, "allocated_percentage": 100})

    # Invoice-level additional discount.
    if discount_amount is not None:
        doc.discount_amount = float(discount_amount)
        doc.apply_discount_on = apply_discount_on or "Grand Total"

    doc.insert(ignore_permissions=False)

    # Fill payment row only after insert so grand_total is computed.
    if pay_type == "cash" and submit:
        mop = mode_of_payment or "Cash"
        account = _default_mop_account(mop, company)
        if not account:
            frappe.throw(_("No default account configured for Mode of Payment {0}").format(mop))
        # clear any auto-added payments rows from Sales Invoice defaults
        doc.set("payments", [])
        doc.append("payments", {
            "mode_of_payment": mop,
            "account": account,
            "amount": float(doc.grand_total or 0),
        })
        doc.save()

    if submit:
        doc.submit()

    _record_outbox(client_id, doc.name, posting_ts, {
        "customer": customer,
        "items": items,
        "warehouse": set_warehouse,
        "payment_type": pay_type or None,
        "mode_of_payment": mode_of_payment,
    })
    frappe.db.commit()

    return {
        "name": doc.name,
        "grand_total": float(doc.grand_total or 0),
        "outstanding_amount": float(doc.outstanding_amount or 0),
        "status": doc.status,
        "docstatus": int(doc.docstatus or 0),
        "modified": naive_site_to_utc_iso(doc.modified),
        "idempotent_replay": False,
    }


def _default_mop_account(mop: str, company: str) -> Optional[str]:
    """Resolve the Mode of Payment's account for the given company."""
    acc = frappe.db.get_value(
        "Mode of Payment Account",
        {"parent": mop, "company": company},
        "default_account",
    )
    if acc:
        return acc
    # Fallback — any account on the MoP row
    rows = frappe.get_all(
        "Mode of Payment Account",
        filters={"parent": mop},
        fields=["default_account", "company"],
    )
    for r in rows:
        if r.get("default_account"):
            return r["default_account"]
    return None


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
    taxes = [
        {
            "description": t.description,
            "rate": float(t.rate or 0),
            "tax_amount": float(t.tax_amount or 0),
            "total": float(t.total or 0),
        }
        for t in (doc.taxes or [])
    ]
    sales_persons = [
        {
            "sales_person": sp.sales_person,
            "allocated_percentage": float(sp.allocated_percentage or 0),
        }
        for sp in (doc.sales_team or [])
    ]
    return {
        "name": doc.name,
        "customer": doc.customer,
        "customer_name": doc.customer_name,
        "company": doc.company,
        "currency": doc.currency,
        "posting_date": str(doc.posting_date) if doc.posting_date else None,
        "posting_time": str(doc.posting_time) if doc.posting_time else None,
        "due_date": str(doc.due_date) if doc.due_date else None,
        "is_return": int(doc.is_return or 0),
        "grand_total": float(doc.grand_total or 0),
        "net_total": float(doc.net_total or 0),
        "total_taxes_and_charges": float(doc.total_taxes_and_charges or 0),
        "discount_amount": float(doc.discount_amount or 0),
        "outstanding_amount": float(doc.outstanding_amount or 0),
        "paid_amount": float((doc.grand_total or 0) - (doc.outstanding_amount or 0)),
        "status": doc.status,
        "docstatus": int(doc.docstatus or 0),
        "remarks": doc.remarks,
        "items": [
            {
                "item_code": i.item_code,
                "item_name": i.item_name,
                "qty": float(i.qty or 0),
                "rate": float(i.rate or 0),
                "price_list_rate": float(i.price_list_rate or 0),
                "discount_percentage": float(i.discount_percentage or 0),
                "discount_amount": float(i.discount_amount or 0),
                "amount": float(i.amount or 0),
                "uom": i.uom,
                "warehouse": i.warehouse,
            }
            for i in doc.items
        ],
        "taxes": taxes,
        "sales_persons": sales_persons,
        "modified": naive_site_to_utc_iso(doc.modified),
    }
