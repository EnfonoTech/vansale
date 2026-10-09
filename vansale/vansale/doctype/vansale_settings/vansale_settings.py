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


def validate_print_formats(doc) -> None:
    """The invoice / receipt print format must be one for that doctype."""
    for fieldname, doctype in (
        ("invoice_print_format", "Sales Invoice"),
        ("receipt_print_format", "Payment Entry"),
    ):
        fmt = doc.get(fieldname)
        if fmt and frappe.db.get_value("Print Format", fmt, "doc_type") != doctype:
            frappe.throw(
                frappe._("Print Format {0} is not for {1}").format(frappe.bold(fmt), doctype)
            )


class VansaleSettings(Document):
    def validate(self):
        validate_print_formats(self)

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
    flags = {
        "enable_route": True,
        "require_pin": True,
        "allow_uom_change": True,
        # Off by default: most sites price from the price list only.
        "use_customer_price": False,
        # Cash sale = POS invoice unless a site chooses Payment Entry.
        "cash_sale_posting": "POS Invoice",
        "cash_payment_entry_status": "Submit",
        # Collections follow the cash-sale status unless set on their own.
        "collection_payment_entry_status": "Same as cash sale",
        "allow_advance_payment": False,
        "invoice_print_format": None,
        "receipt_print_format": None,
        "allow_split_payment": False,
        "allow_return_without_invoice": False,
        "direct_print": False,
        "print_after_submit": False,
        # PDF (save to device) button on print screens; on unless a site hides it.
        "show_pdf_button": True,
        "print_copies": 1,
    }
    try:
        row = frappe.db.get_singles_dict("Vansale Settings") or {}
        if "enable_route" in row:
            flags["enable_route"] = bool(int(row.get("enable_route") or 0))
        if "require_pin" in row:
            flags["require_pin"] = bool(int(row.get("require_pin") or 0))
        if "allow_uom_change" in row:
            flags["allow_uom_change"] = bool(int(row.get("allow_uom_change") or 0))
        if "use_customer_price" in row:
            flags["use_customer_price"] = bool(int(row.get("use_customer_price") or 0))
        for key in (
            "cash_sale_posting",
            "cash_payment_entry_status",
            "collection_payment_entry_status",
            "invoice_print_format",
            "receipt_print_format",
        ):
            if row.get(key):
                flags[key] = row[key]
        for key in (
            "direct_print",
            "print_after_submit",
            "allow_split_payment",
            "allow_return_without_invoice",
            "allow_advance_payment",
            "show_pdf_button",
        ):
            if key in row:
                flags[key] = bool(int(row.get(key) or 0))
        if row.get("print_copies"):
            flags["print_copies"] = max(1, int(row["print_copies"]))
    except Exception:
        # Pre-migration site or missing table — keep the safe defaults.
        return flags
    frappe.cache().set_value(CACHE_KEY, flags)
    return flags
