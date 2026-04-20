"""Payment Entry endpoints.

`save` is idempotent by `client_id` exactly like invoices. Supports cash
and bank modes; extends via `mode_of_payment` which maps to a Mode of
Payment doc.
"""

from __future__ import annotations

from typing import Optional

import frappe
from frappe import _

from vansale.api.datetime_util import naive_site_to_utc_iso, parse_client_ts


def _existing_by_client_id(client_id: str) -> Optional[str]:
    if not client_id:
        return None
    name = frappe.db.get_value("Vansale Outbox", {"client_id": client_id}, "ref_name")
    if name and frappe.db.exists("Payment Entry", name):
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
    doc.event_type = "payment"
    doc.user = frappe.session.user
    doc.client_ts = parse_client_ts(posting_ts) if posting_ts else None
    doc.drained_at = frappe.utils.now_datetime()
    doc.status = "processed"
    doc.ref_doctype = "Payment Entry"
    doc.ref_name = ref_name
    doc.payload_json = frappe.as_json(payload)
    doc.save(ignore_permissions=True)


def _resolve_accounts(company: str, mode_of_payment: str) -> tuple[str, str]:
    """Return (paid_from, paid_to). paid_from is customer's receivable; paid_to is the bank/cash."""
    receivable = frappe.db.get_value(
        "Company", company, "default_receivable_account"
    ) or frappe.db.get_value(
        "Account", {"company": company, "account_type": "Receivable", "is_group": 0}, "name"
    )
    paid_to = frappe.db.get_value(
        "Mode of Payment Account",
        {"parent": mode_of_payment, "company": company},
        "default_account",
    )
    if not paid_to:
        paid_to = (
            frappe.db.get_value(
                "Account",
                {"company": company, "account_type": "Cash", "is_group": 0},
                "name",
            )
            or frappe.db.get_value(
                "Account",
                {"company": company, "account_type": "Bank", "is_group": 0},
                "name",
            )
        )
    if not (receivable and paid_to):
        frappe.throw(_("Could not resolve accounts for payment — set defaults on Company."))
    return receivable, paid_to


@frappe.whitelist(methods=["POST"])
def save(
    client_id: str,
    customer: str,
    paid_amount: float,
    mode_of_payment: str = "Cash",
    reference_no: Optional[str] = None,
    reference_date: Optional[str] = None,
    invoice_name: Optional[str] = None,
    posting_ts: Optional[str] = None,
    remarks: Optional[str] = None,
    submit: int = 1,
) -> dict:
    if not client_id:
        frappe.throw(_("client_id is required"))
    if not customer:
        frappe.throw(_("Customer required"))
    try:
        amount = float(paid_amount)
    except (TypeError, ValueError):
        frappe.throw(_("Invalid amount"))
    if amount <= 0:
        frappe.throw(_("Amount must be positive"))

    existing = _existing_by_client_id(client_id)
    if existing:
        doc = frappe.get_doc("Payment Entry", existing)
        return {
            "name": doc.name,
            "paid_amount": float(doc.paid_amount or 0),
            "status": doc.status,
            "modified": naive_site_to_utc_iso(doc.modified),
            "idempotent_replay": True,
        }

    company = (
        frappe.db.get_value(
            "User Permission",
            {"user": frappe.session.user, "allow": "Company", "is_default": 1},
            "for_value",
        )
        or frappe.defaults.get_user_default("Company", frappe.session.user)
        or frappe.db.get_single_value("Global Defaults", "default_company")
    )
    paid_from, paid_to = _resolve_accounts(company, mode_of_payment)
    posting = parse_client_ts(posting_ts) if posting_ts else frappe.utils.now_datetime()

    # Account currencies — required by ERPNext's Payment Entry validation;
    # skipping this made validate() trip on str vs Dict attribute access.
    paid_from_currency = frappe.db.get_value("Account", paid_from, "account_currency") or "SAR"
    paid_to_currency = frappe.db.get_value("Account", paid_to, "account_currency") or "SAR"

    doc = frappe.new_doc("Payment Entry")
    doc.payment_type = "Receive"
    doc.party_type = "Customer"
    doc.party = customer
    doc.company = company
    doc.mode_of_payment = mode_of_payment
    doc.paid_amount = amount
    doc.received_amount = amount
    doc.paid_from = paid_from
    doc.paid_to = paid_to
    doc.paid_from_account_currency = paid_from_currency
    doc.paid_to_account_currency = paid_to_currency
    doc.party_account = paid_from  # for Receive, party_account == paid_from (Debtors)
    doc.party_account_currency = paid_from_currency
    doc.source_exchange_rate = 1
    doc.target_exchange_rate = 1
    doc.reference_no = reference_no
    doc.reference_date = reference_date
    doc.posting_date = posting.date()
    doc.remarks = remarks

    if invoice_name:
        inv = frappe.db.get_value(
            "Sales Invoice",
            invoice_name,
            ["grand_total", "outstanding_amount", "currency"],
            as_dict=True,
        )
        if inv:
            allocated = min(amount, float(inv.outstanding_amount or 0))
            doc.append(
                "references",
                {
                    "reference_doctype": "Sales Invoice",
                    "reference_name": invoice_name,
                    "total_amount": float(inv.grand_total or 0),
                    "outstanding_amount": float(inv.outstanding_amount or 0),
                    "allocated_amount": allocated,
                },
            )

    # NOTE: do NOT call doc.setup_party_account_field() — it's gone in
    # ERPNext v15 and previously raised AttributeError("'str'"). The
    # explicit party_account assignment above already matches what the
    # method used to populate.
    doc.insert(ignore_permissions=False)
    if submit:
        doc.submit()

    _record_outbox(client_id, doc.name, posting_ts, {
        "customer": customer,
        "amount": amount,
        "mode_of_payment": mode_of_payment,
        "invoice_name": invoice_name,
    })
    frappe.db.commit()

    return {
        "name": doc.name,
        "paid_amount": float(doc.paid_amount or 0),
        "status": doc.status,
        "modified": naive_site_to_utc_iso(doc.modified),
        "idempotent_replay": False,
    }


@frappe.whitelist(methods=["GET"])
def list_mine(limit: int = 50, customer: Optional[str] = None) -> list[dict]:
    filters: dict = {"docstatus": 1}
    if customer:
        filters["party"] = customer
    rows = frappe.get_all(
        "Payment Entry",
        filters=filters,
        fields=["name", "party", "party_name", "paid_amount", "mode_of_payment", "posting_date", "modified"],
        order_by="posting_date desc, modified desc",
        limit=int(limit),
    )
    for r in rows:
        r["modified"] = naive_site_to_utc_iso(r.get("modified"))
    return rows


@frappe.whitelist(methods=["GET"])
def outstanding(customer: str) -> list[dict]:
    rows = frappe.get_all(
        "Sales Invoice",
        filters={"customer": customer, "docstatus": 1, "outstanding_amount": [">", 0]},
        fields=["name", "grand_total", "outstanding_amount", "posting_date"],
        order_by="posting_date asc",
    )
    for r in rows:
        r["posting_date"] = naive_site_to_utc_iso(r.get("posting_date"))
    return rows
