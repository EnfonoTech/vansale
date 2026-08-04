"""Sales return (credit note) endpoints.

Returns are modelled as Sales Invoice with ``is_return=1``. Qty on each
line is negative; total must not exceed the original invoice's qty.
"""

from __future__ import annotations

from typing import Any, Optional

import frappe
from frappe import _

from vansale.api.datetime_util import naive_site_to_utc_iso, parse_client_ts

# Structured return reasons. Mirrors the `custom_return_reason` Select options
# shipped in `fixtures/custom_field.json` — keep the two in step.
RETURN_REASONS = (
    "Damaged",
    "Expired",
    "Wrong Item",
    "Customer Refused",
    "Short Delivery",
    "Other",
)


def resolve_return_reason(reason: Optional[str]) -> tuple[str, str]:
    """Split the client's `reason` into (structured option, remarks text).

    A reason is mandatory: a credit note with no stated cause is unauditable,
    and "why are returns up this month" is the first question the office asks.

    Older APKs send free text here rather than one of the options. Those are
    filed as "Other" with the text preserved in remarks instead of being
    rejected — refusing them would break returns on every phone that has not
    updated yet, mid-rollout.
    """
    text = (reason or "").strip()
    if not text:
        frappe.throw(_("A return reason is required"))
    if text in RETURN_REASONS:
        return text, text
    return "Other", text


def _existing(client_id: str) -> Optional[str]:
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
    doc.event_type = "return"
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
    original_invoice: str,
    items: list[dict[str, Any]],
    reason: Optional[str] = None,
    note: Optional[str] = None,
    posting_ts: Optional[str] = None,
    submit: int = 1,
) -> dict:
    if not client_id:
        frappe.throw(_("client_id is required"))
    if not original_invoice:
        frappe.throw(_("Original invoice required"))
    if not items:
        frappe.throw(_("At least one line is required"))

    # Validated before the idempotency check so a replay cannot smuggle a
    # reason-less return through on the second attempt.
    reason_option, reason_text = resolve_return_reason(reason)

    existing = _existing(client_id)
    if existing:
        doc = frappe.get_doc("Sales Invoice", existing)
        return {
            "name": doc.name,
            "grand_total": float(doc.grand_total or 0),
            "status": doc.status,
            "idempotent_replay": True,
        }

    original = frappe.get_doc("Sales Invoice", original_invoice)
    if original.docstatus != 1:
        frappe.throw(_("Original invoice must be submitted"))

    original_lines = {i.item_code: i for i in original.items}
    posting = parse_client_ts(posting_ts) if posting_ts else frappe.utils.now_datetime()

    doc = frappe.new_doc("Sales Invoice")
    doc.customer = original.customer
    doc.company = original.company
    doc.set_posting_time = 1
    doc.posting_date = posting.date()
    doc.posting_time = posting.strftime("%H:%M:%S")
    doc.is_return = 1
    doc.return_against = original_invoice
    doc.update_stock = original.update_stock
    doc.set_warehouse = original.set_warehouse
    extra = (note or "").strip()
    doc.remarks = f"{reason_text} — {extra}" if extra and extra != reason_text else reason_text
    # Guarded: a site that has not migrated the fixture yet still takes returns,
    # it just loses the structured breakdown until the next migrate.
    if frappe.get_meta("Sales Invoice").has_field("custom_return_reason"):
        doc.custom_return_reason = reason_option
    doc.custom_client_id = client_id

    for line in items:
        code = line.get("item_code")
        if not code or code not in original_lines:
            frappe.throw(_("Item {0} not in original invoice").format(code))
        qty = abs(float(line.get("qty") or 0))
        if qty <= 0:
            continue
        max_qty = float(original_lines[code].qty or 0)
        if qty > max_qty:
            frappe.throw(_("Cannot return more than sold: {0}").format(code))
        row = doc.append("items", {})
        row.item_code = code
        row.qty = -qty
        row.rate = float(original_lines[code].rate or 0)
        row.uom = original_lines[code].uom
        row.warehouse = line.get("warehouse") or original_lines[code].warehouse

    doc.insert(ignore_permissions=False)
    if submit:
        doc.submit()

    _record_outbox(client_id, doc.name, posting_ts, {
        "original_invoice": original_invoice,
        "items": items,
        "reason": reason,
        "note": note,
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
def list_mine(limit: int = 50) -> list[dict]:
    rows = frappe.get_all(
        "Sales Invoice",
        filters={"is_return": 1, "docstatus": 1, "owner": frappe.session.user},
        fields=["name", "customer", "return_against", "grand_total", "posting_date", "modified"],
        order_by="posting_date desc",
        limit=int(limit),
    )
    for r in rows:
        r["modified"] = naive_site_to_utc_iso(r.get("modified"))
    return rows
