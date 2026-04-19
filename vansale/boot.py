"""Boot-session hook — injects Van User defaults into the bootinfo.

Reference: `rmax_custom/boot.py`.

For Van Users the PWA (not the desk) is the primary UI, so we:
  - Redirect desk login to `/vansale` (rarely triggers; most users go straight to PWA).
  - Restrict sidebar modules to Vansale.
  - Override `sysdefaults.company` with the User Permission default so form defaults
    resolve to the van's company instead of the global default.
  - Set `bootinfo.vansale_defaults` so custom JS (and the PWA via `boot()`) can read
    the user's default cost center / warehouse without extra round-trips.
"""

from __future__ import annotations

import frappe


def boot_session(bootinfo) -> None:
    user = frappe.session.user
    if user in ("Administrator", "Guest"):
        return

    roles = frappe.get_roles(user)
    if "System Manager" in roles:
        # System Managers retain full desk access; still expose defaults for
        # convenience so they can impersonate.
        bootinfo.vansale_defaults = _collect_user_defaults(user)
        return

    is_van_user = "Van User" in roles or "Van Manager" in roles
    if not is_van_user:
        return

    # Route + sidebar restrictions (desk fallback — PWA is primary).
    bootinfo.default_route = "/vansale"
    bootinfo.allowed_modules = ["Vansale"]
    bootinfo.is_vansale_restricted = True

    defaults = _collect_user_defaults(user)
    bootinfo.vansale_defaults = defaults

    # Session defaults override so new forms pick up the user's company
    # instead of Global Defaults.
    company = defaults.get("company")
    if company:
        bootinfo.user_default_company = company
        if bootinfo.sysdefaults:
            bootinfo.sysdefaults["company"] = company
        if hasattr(bootinfo, "user") and hasattr(bootinfo.user, "defaults"):
            bootinfo.user.defaults["company"] = company
            bootinfo.user.defaults["Company"] = company


def _collect_user_defaults(user: str) -> dict:
    """Resolve (company, warehouse, cost_center, branch) from User Permission."""
    defaults: dict = {"company": None, "warehouse": None, "cost_center": None, "branch": None}
    rows = frappe.get_all(
        "User Permission",
        filters={"user": user, "is_default": 1},
        fields=["allow", "for_value"],
    )
    for r in rows:
        key = {
            "Company": "company",
            "Warehouse": "warehouse",
            "Cost Center": "cost_center",
            "Branch": "branch",
        }.get(r["allow"])
        if key:
            defaults[key] = r["for_value"]
    return defaults
