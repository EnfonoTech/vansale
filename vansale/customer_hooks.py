"""Customer document hooks.

Auto-tag the creating user's Sales Person on every newly-inserted
Customer so desk-created customers show up on the creator's driver
roster without an explicit admin action. Mirrors the API-side logic in
`vansale.api.customer.create`, which already does this for PWA-created
customers, but extends the behavior to Customers inserted via any path
(desk form, Data Import, scripts, etc.).

Behavior when the Vansale module is NOT actively used:
  - Zero Vansale Configuration User rows → cached `_module_active` flag
    returns False → hook is a fast no-op (no DB query per Customer).
  - Site Config key `disable_vansale_customer_autotag` = 1 → explicit
    admin opt-out without needing to remove the hook.

Silent no-op when:
  - module not active (no Vansale Configuration Users exist), or
  - site explicitly opts out via `disable_vansale_customer_autotag`, or
  - session user has no Vansale Configuration User row, or
  - the sales_team already includes the same sales_person (idempotent).
"""

from __future__ import annotations

import frappe

from vansale.api.me import current_user_sales_person


_MODULE_ACTIVE_CACHE_KEY = "vansale_module_active"
_MODULE_ACTIVE_TTL = 300  # seconds — cheap to recompute; 5 min is fine


def _module_active() -> bool:
    """True if any Vansale Configuration User rows exist on this site.

    Cached for 5 minutes so the hot-path Customer.before_insert doesn't
    pay a COUNT(*) per insert. Adding/removing a Vansale Configuration
    User invalidates this key via `clear_module_active_cache`.
    """
    cache = frappe.cache()
    cached = cache.get_value(_MODULE_ACTIVE_CACHE_KEY)
    if cached is not None:
        return bool(int(cached))
    active = bool(
        frappe.db.sql(
            "SELECT 1 FROM `tabVansale Configuration User` LIMIT 1"
        )
    )
    cache.set_value(
        _MODULE_ACTIVE_CACHE_KEY, "1" if active else "0", expires_in_sec=_MODULE_ACTIVE_TTL
    )
    return active


def clear_module_active_cache(doc=None, method=None) -> None:
    """Hook for Vansale Configuration User on_update/on_trash — drops the
    cached active flag so the next Customer insert re-evaluates.
    """
    try:
        frappe.cache().delete_value(_MODULE_ACTIVE_CACHE_KEY)
    except Exception:
        pass


def auto_assign_sales_person(doc, method=None) -> None:
    """before_insert hook. See module docstring."""
    # Explicit per-site opt-out — admins can disable without removing
    # the hook wiring from hooks.py.
    if frappe.conf.get("disable_vansale_customer_autotag"):
        return

    # Fast no-op when the module isn't used on this site at all.
    if not _module_active():
        return

    # Administrator + bulk-import flows shouldn't accidentally tag a
    # random van user's Sales Person onto every Customer they seed —
    # only fire when the session user actually maps to one.
    try:
        sp = current_user_sales_person()
    except Exception:
        return
    if not sp:
        return
    existing = [(row.sales_person or "") for row in (doc.sales_team or [])]
    if sp in existing:
        return
    doc.append("sales_team", {"sales_person": sp, "allocated_percentage": 100})
