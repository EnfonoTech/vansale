"""Stable `api_key` / `api_secret` issuance.

Rule from `frappe-vue-pwa` §3.5 commandment 7:
regenerating `api_secret` on every PIN unlock invalidates the token on
every user's phone. Only generate on the first ever unlock; reuse the
same pair thereafter.
"""

from __future__ import annotations

import frappe
from frappe.utils.password import get_decrypted_password


def get_or_create_stable_secret(user_doc) -> tuple[str, str]:
    """Return (api_key, api_secret) for the given User doc.

    On first call: generates + persists both.
    Subsequent calls: returns the existing pair without rotating it.
    """
    existing_secret: str | None = None

    if user_doc.api_key:
        try:
            existing_secret = get_decrypted_password(
                "User", user_doc.name, "api_secret", raise_exception=False
            )
        except Exception:
            existing_secret = None

    if existing_secret:
        return user_doc.api_key, existing_secret

    api_secret = frappe.generate_hash(length=15)
    user_doc.api_key = user_doc.api_key or frappe.generate_hash(length=15)
    user_doc.api_secret = api_secret
    user_doc.flags.ignore_permissions = True
    user_doc.save(ignore_permissions=True)
    frappe.db.commit()
    return user_doc.api_key, api_secret
