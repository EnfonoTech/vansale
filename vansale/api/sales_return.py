"""Sales return (credit note) endpoints.

Returns are modelled as Sales Invoice with ``is_return=1``. Qty on each
line is negative; total must not exceed the original invoice's qty.
"""

from __future__ import annotations

from typing import Any, Optional

import frappe
from frappe import _
from frappe.utils import flt

from vansale.api.access import readable_doc
from vansale.api.outbox import claim
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


def returned_qty_by_row(original) -> dict[str, float]:
    """Qty already returned per original invoice row (submitted returns).

    Returns made before rows were linked (`sales_invoice_item` empty) are
    counted against that item's rows in invoice order.
    """
    returned = {line.name: 0.0 for line in original.items}
    unlinked: dict[str, float] = {}
    for r in frappe.db.sql(
        """
        SELECT sii.sales_invoice_item, sii.item_code, -sii.qty AS qty
        FROM `tabSales Invoice Item` sii
        JOIN `tabSales Invoice` si ON si.name = sii.parent
        WHERE si.return_against = %s AND si.is_return = 1 AND si.docstatus = 1
        """,
        original.name,
        as_dict=True,
    ):
        if r.sales_invoice_item in returned:
            returned[r.sales_invoice_item] += flt(r.qty)
        else:
            unlinked[r.item_code] = unlinked.get(r.item_code, 0.0) + flt(r.qty)
    for line in original.items:
        take = min(unlinked.get(line.item_code, 0.0), flt(line.qty) - returned[line.name])
        if take > 0:
            returned[line.name] += take
            unlinked[line.item_code] -= take
    return returned


def append_return_rows(doc, original, items: list[dict[str, Any]]) -> None:
    """Add return lines to `doc`, each tied to one row of the original invoice.

    A line names its row with `sales_invoice_item`; without it, the first row
    of that item with qty left is used. Qty may not exceed what is left on the
    row after earlier returns. UOM, conversion factor, rate, discount and
    warehouse come from the original row, so the credit matches the sale.
    Lines with qty 0 are skipped.
    """
    rows = {line.name: line for line in original.items}
    left = {
        name: flt(rows[name].qty) - done for name, done in returned_qty_by_row(original).items()
    }
    for item in items:
        code = item.get("item_code")
        qty = abs(flt(item.get("qty")))
        if qty <= 0:
            continue
        row_name = item.get("sales_invoice_item")
        if row_name:
            if row_name not in rows:
                frappe.throw(_("Line {0} is not on invoice {1}").format(row_name, original.name))
            orig = rows[row_name]
        else:
            if not code:
                frappe.throw(_("item_code is required on every return line"))
            candidates = [l for l in original.items if l.item_code == code]
            if not candidates:
                frappe.throw(_("Item {0} not in original invoice").format(code))
            orig = next((l for l in candidates if left[l.name] > 0), candidates[0])
        if qty > left[orig.name] + 1e-9:
            frappe.throw(
                _("Cannot return {0} {1} of {2}: only {3} left after earlier returns").format(
                    qty, orig.uom, orig.item_code, max(left[orig.name], 0)
                )
            )
        left[orig.name] -= qty

        row = doc.append("items", {})
        row.item_code = orig.item_code
        row.qty = -qty
        row.uom = orig.uom
        row.conversion_factor = flt(orig.conversion_factor) or 1
        row.price_list_rate = flt(orig.price_list_rate)
        row.rate = flt(orig.rate)
        if orig.discount_percentage:
            row.discount_percentage = flt(orig.discount_percentage)
        row.warehouse = item.get("warehouse") or orig.warehouse or doc.set_warehouse
        row.sales_invoice_item = orig.name

    if not doc.get("items"):
        frappe.throw(_("Enter a return qty for at least one line"))

    # Same taxes as the sale (see invoice._apply_template_taxes).
    doc.taxes_and_charges = original.taxes_and_charges
    if doc.taxes_and_charges and not doc.get("taxes"):
        doc.append_taxes_from_master()


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

    existing = claim(client_id, "return", "Sales Invoice")
    if existing:
        doc = frappe.get_doc("Sales Invoice", existing)
        return {
            "name": doc.name,
            "grand_total": float(doc.grand_total or 0),
            "status": doc.status,
            "idempotent_replay": True,
        }

    original = readable_doc("Sales Invoice", original_invoice)
    if original.docstatus != 1:
        frappe.throw(_("Original invoice must be submitted"))

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

    append_return_rows(doc, original, items)

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
