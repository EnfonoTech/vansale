"""Clear all stored PINs so users re-create them at the fixed 4-digit length.

Pre-1.0.13 the PIN was validated at 4–8 digits — some users ended up with
6-digit PINs via the accidental 6-dot UI. 1.0.13 locks the length to 4 on
both client and server, which would otherwise reject those 6-digit hashes
at unlock time and strand the user. Easiest safe path: wipe the Vansale
Pin docs; the next APK launch falls through to `setup_pin` via the
normal password-login path (PinView detects `pin_verified_at === null`).
"""

from __future__ import annotations

import frappe


def execute() -> None:
    if not frappe.db.has_table("Vansale Pin"):
        return
    frappe.db.sql("DELETE FROM `tabVansale Pin`")
    frappe.db.commit()
