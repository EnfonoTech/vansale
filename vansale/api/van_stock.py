"""Van (truck-local) stock view. Uses ERPNext's existing Bin table so a
van is just a Warehouse tagged as the user's default — no parallel
ledger to maintain. Stock movements happen via Stock Entry transfers.
"""

from __future__ import annotations

from typing import Optional

import frappe
from frappe import _

from vansale.api.access import check_read
from vansale.api.outbox import claim
from vansale.api.datetime_util import naive_site_to_utc_iso, parse_client_ts


def _record_stock_entry_outbox(
    client_id: str | None,
    ref_name: str,
    posting_ts: str | None,
    payload: dict,
) -> None:
    if not client_id:
        return
    if frappe.db.exists("Vansale Outbox", client_id):
        doc = frappe.get_doc("Vansale Outbox", client_id)
    else:
        doc = frappe.new_doc("Vansale Outbox")
        doc.client_id = client_id
    doc.event_type = "stock_adjust"
    doc.user = frappe.session.user
    doc.client_ts = parse_client_ts(posting_ts) if posting_ts else None
    doc.drained_at = frappe.utils.now_datetime()
    doc.status = "processed"
    doc.ref_doctype = "Stock Entry"
    doc.ref_name = ref_name
    doc.payload_json = frappe.as_json(payload)
    doc.save(ignore_permissions=True)


def _user_van_warehouse() -> Optional[str]:
    """Resolve the van user's primary warehouse via User Permission.

    Vansale Configuration sets ``is_default=1`` on the first warehouse row
    for each assigned user. Fallback to Frappe's per-user defaults for
    admin accounts that haven't been added to a Vansale Configuration.
    """
    user = frappe.session.user
    return (
        frappe.db.get_value(
            "User Permission",
            {"user": user, "allow": "Warehouse", "is_default": 1},
            "for_value",
        )
        or frappe.defaults.get_user_default("Warehouse", user)
    )


def _user_warehouses() -> list[str]:
    """All warehouses the van user has User Permission for."""
    user = frappe.session.user
    return frappe.get_all(
        "User Permission",
        filters={"user": user, "allow": "Warehouse"},
        pluck="for_value",
    )


@frappe.whitelist(methods=["GET"])
def my_warehouse() -> dict:
    wh = _user_van_warehouse()
    return {"warehouse": wh}


@frappe.whitelist(methods=["GET"])
def list_stock(warehouse: Optional[str] = None, limit: int = 500) -> dict:
    wh = warehouse or _user_van_warehouse()
    if not wh:
        frappe.throw(_("No van warehouse set. Assign one on your Sales Person profile."))
    check_read("Warehouse", wh)
    rows = frappe.db.sql(
        """
        SELECT b.item_code, i.item_name, i.stock_uom, b.actual_qty,
               b.stock_value, i.image
        FROM `tabBin` b
        JOIN `tabItem` i ON i.name = b.item_code
        WHERE b.warehouse = %s AND i.disabled = 0 AND b.actual_qty > 0
        ORDER BY i.item_name ASC
        LIMIT %s
        """,
        (wh, int(limit)),
        as_dict=True,
    )
    for r in rows:
        r["actual_qty"] = float(r.get("actual_qty") or 0)
        r["stock_value"] = float(r.get("stock_value") or 0)
    return {"warehouse": wh, "items": rows}


@frappe.whitelist(methods=["POST"])
def transfer_in(
    from_warehouse: str,
    items: list[dict],
    to_warehouse: Optional[str] = None,
    reason: Optional[str] = None,
    client_id: Optional[str] = None,
    posting_ts: Optional[str] = None,
) -> dict:
    """Create a Material Transfer Stock Entry from ``from_warehouse`` to the user's van.

    Idempotent via ``client_id`` — when the offline queue replays this
    call, the server returns the previously-persisted Stock Entry
    instead of creating a duplicate load. Uses Vansale Outbox
    (event_type="stock_adjust"), matching the invoice/payment/return
    pattern.
    """
    # Replay short-circuit — done BEFORE validation so a retry of a
    # successful load doesn't re-throw "At least one item required"
    # because the caller trimmed the payload.
    if client_id:
        prior = claim(client_id, "stock_adjust", "Stock Entry")
        if prior:
            prior_doc = frappe.get_doc("Stock Entry", prior)
            return {
                "name": prior_doc.name,
                "modified": naive_site_to_utc_iso(prior_doc.modified),
                "idempotent_replay": True,
            }

    target = to_warehouse or _user_van_warehouse()
    if not target:
        frappe.throw(_("No destination warehouse"))
    if not from_warehouse:
        frappe.throw(_("Source warehouse required"))
    if not items:
        frappe.throw(_("At least one item required"))

    doc = frappe.new_doc("Stock Entry")
    doc.stock_entry_type = "Material Transfer"
    doc.from_warehouse = from_warehouse
    doc.to_warehouse = target
    doc.remarks = reason or "Van replenishment"

    for item in items:
        row = doc.append("items", {})
        row.item_code = item["item_code"]
        row.qty = float(item.get("qty") or 0)
        row.s_warehouse = from_warehouse
        row.t_warehouse = target

    doc.insert(ignore_permissions=False)
    doc.submit()

    # Outbox row in the same transaction as the Stock Entry (claimed above):
    # a retry can't load the van twice, and a rollback drops both.
    if client_id:
        _record_stock_entry_outbox(
            client_id,
            doc.name,
            posting_ts,
            {
                "from_warehouse": from_warehouse,
                "to_warehouse": target,
                "reason": reason,
                "items": items,
            },
        )

    frappe.db.commit()

    return {"name": doc.name, "modified": naive_site_to_utc_iso(doc.modified)}
