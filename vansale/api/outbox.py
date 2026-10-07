"""Idempotency keys for offline-queued writes (Vansale Outbox, name = client_id).

A save that times out on the device is queued and resent with the same
client_id while the first request may still be running. Checking "does an
outbox row exist?" and then creating the document let both requests pass
the check and post twice. `claim` reserves the key inside the request's
transaction before anything is created:

- the key was already processed → returns the existing document's name;
- another request holds the key → waits for it (row lock), then returns
  what it created, or takes over the key if that request rolled back;
- otherwise inserts the outbox row, which commits or rolls back together
  with the document.

The caller's `_record_*outbox` later fills in ref_name / payload on the
same row.
"""

from __future__ import annotations

from typing import Optional

import frappe


def _locked_row(client_id: str):
    # Locking read: waits for an uncommitted insert of the same key and sees
    # the latest committed row (a plain read would use the old snapshot).
    rows = frappe.db.sql(
        "SELECT ref_doctype, ref_name FROM `tabVansale Outbox` WHERE name = %s FOR UPDATE",
        client_id,
        as_dict=True,
    )
    return rows[0] if rows else None


def claim(client_id: Optional[str], event_type: str, ref_doctype: str) -> Optional[str]:
    """Reserve `client_id`; return the existing document name if already processed.

    Call it before the request writes anything (it may roll back on replay).
    """
    if not client_id:
        return None
    row = _locked_row(client_id)
    if row is None:
        doc = frappe.new_doc("Vansale Outbox")
        doc.client_id = client_id
        doc.event_type = event_type
        doc.user = frappe.session.user
        doc.status = "queued"
        doc.ref_doctype = ref_doctype
        try:
            doc.insert(ignore_permissions=True)
            return None
        except frappe.DuplicateEntryError:
            row = _locked_row(client_id)
    if row and row.ref_name and _exists_latest(row.ref_doctype or ref_doctype, row.ref_name):
        # Replay. End this transaction (nothing was written: `claim` runs
        # before any write) so the caller's plain reads of that document
        # use a fresh snapshot instead of the one from before we waited.
        frappe.db.rollback()
        return row.ref_name
    return None


def _exists_latest(doctype: str, name: str) -> bool:
    # Locking read for the same reason as `_locked_row`: after waiting for the
    # other request, a plain `frappe.db.exists` would still use this
    # transaction's older snapshot and miss the document it just created.
    return bool(
        frappe.db.sql(
            f"SELECT name FROM `tab{doctype}` WHERE name = %s LOCK IN SHARE MODE", name
        )
    )
