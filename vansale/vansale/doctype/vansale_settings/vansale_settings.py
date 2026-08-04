"""Vansale Settings — site-wide module master switches.

Two levels sit below this one (`Vansale Configuration.route_mode` /
`pin_mode` per van, and `Vansale Configuration User.pin_mode` per user), each
defaulting to "Follow Global". Resolution lives in `vansale.api.me` so the
API and the DocType cannot drift apart.
"""

from __future__ import annotations

import frappe
from frappe.model.document import Document

CACHE_KEY = "vansale_settings_flags"


class VansaleSettings(Document):
    def on_update(self):
        # Every `config_defaults` call reads these two flags, so they are
        # cached. Without this the cache would serve a stale master switch
        # until the next bench restart.
        frappe.cache().delete_value(CACHE_KEY)


def global_flags() -> dict:
    """Cached {enable_route, require_pin, allow_uom_change}. Defaults to on when unset.

    A site that has not migrated yet has no Singles row at all — treat that
    as "both on" so upgrading never silently removes a module.
    """
    cached = frappe.cache().get_value(CACHE_KEY)
    if cached:
        return cached
    flags = {"enable_route": True, "require_pin": True, "allow_uom_change": True}
    try:
        row = frappe.db.get_singles_dict("Vansale Settings") or {}
        if "enable_route" in row:
            flags["enable_route"] = bool(int(row.get("enable_route") or 0))
        if "require_pin" in row:
            flags["require_pin"] = bool(int(row.get("require_pin") or 0))
        if "allow_uom_change" in row:
            flags["allow_uom_change"] = bool(int(row.get("allow_uom_change") or 0))
    except Exception:
        # Pre-migration site or missing table — keep the safe defaults.
        return flags
    frappe.cache().set_value(CACHE_KEY, flags)
    return flags
