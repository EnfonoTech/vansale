"""Per-user defaults + profile for the SPA.

The PWA reads this on login / PIN unlock and uses the returned values
to pre-fill invoice forms, payment forms, the van stock page, etc. —
so the UI inherits the same scoping that the server enforces via
Vansale Configuration + User Permission.
"""

from __future__ import annotations

import frappe
from frappe import _

from vansale.vansale.doctype.vansale_settings.vansale_settings import global_flags


def _resolve_mode(*modes: str | None, default: bool) -> bool:
    """Collapse a most-specific-first chain of tri-state modes into a bool.

    Each level is "Enabled", "Disabled" or "Follow Global" (also None / "" on
    rows saved before the field existed). The first level that commits wins;
    if every level defers, `default` — the global master switch — decides.

    Kept in one helper so the per-van and per-user chains cannot drift.
    """
    for mode in modes:
        if mode == "Enabled":
            return True
        if mode == "Disabled":
            return False
    return default


@frappe.whitelist(methods=["GET"])
def config_defaults() -> dict:
    """Return the user's Vansale Configuration defaults.

    Shape:
        {
          "user": "ali@example.com",
          "full_name": "Ali",
          "is_van_user": True,
          "is_van_manager": False,
          "company": "Trading Co",
          "branch": null,
          "default_warehouse": "Van-01 - TC",
          "warehouses": ["Van-01 - TC"],
          "default_cost_center": "Van-01 - TC",
          "cost_centers": ["Van-01 - TC", "Main - TC"],
          "van_code": "VAN-RIYADH-01",
          "currency": "SAR"
        }
    """
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("Login required"), frappe.AuthenticationError)

    user_doc = frappe.get_doc("User", user)
    roles = [r.role for r in user_doc.roles]

    perms = frappe.get_all(
        "User Permission",
        filters={"user": user},
        fields=["allow", "for_value", "is_default"],
    )

    company: str | None = None
    branch: str | None = None
    default_warehouse: str | None = None
    default_cost_center: str | None = None
    warehouses: list[str] = []
    cost_centers: list[str] = []

    for p in perms:
        allow = p["allow"]
        value = p["for_value"]
        is_default = bool(p.get("is_default"))
        if allow == "Company":
            if is_default or company is None:
                company = value
        elif allow == "Branch":
            if is_default or branch is None:
                branch = value
        elif allow == "Warehouse":
            warehouses.append(value)
            if is_default:
                default_warehouse = value
        elif allow == "Cost Center":
            cost_centers.append(value)
            if is_default:
                default_cost_center = value

    # Van code + sales person — first Vansale Configuration that lists this user.
    cfg_user = frappe.db.get_value(
        "Vansale Configuration User",
        {"user": user},
        ["parent", "sales_person", "pin_mode"],
        as_dict=True,
    )
    van_code = cfg_user.parent if cfg_user else None
    sales_person = cfg_user.sales_person if cfg_user else None
    require_location = False
    selling_price_list: str | None = None
    van_route_mode: str | None = None
    van_pin_mode: str | None = None
    if van_code:
        # require_location is new (v1.0.12); guard with has_field so old sites don't crash
        try:
            if frappe.get_meta("Vansale Configuration").has_field("require_location"):
                require_location = bool(
                    frappe.db.get_value("Vansale Configuration", van_code, "require_location") or 0
                )
        except Exception:
            require_location = False
        # selling_price_list is new (v1.0.18); same has_field guard.
        try:
            if frappe.get_meta("Vansale Configuration").has_field("selling_price_list"):
                selling_price_list = (
                    frappe.db.get_value("Vansale Configuration", van_code, "selling_price_list") or None
                )
        except Exception:
            selling_price_list = None
        # route_mode / pin_mode are new (v1.0.26); same has_field guard. On a
        # site that has not migrated, both stay None → "Follow Global" → the
        # global defaults (both on), i.e. the old always-on behaviour.
        try:
            meta = frappe.get_meta("Vansale Configuration")
            wanted = [f for f in ("route_mode", "pin_mode") if meta.has_field(f)]
            if wanted:
                row = frappe.db.get_value(
                    "Vansale Configuration", van_code, wanted, as_dict=True
                ) or {}
                van_route_mode = row.get("route_mode")
                van_pin_mode = row.get("pin_mode")
        except Exception:
            van_route_mode = van_pin_mode = None

    # Most specific wins: user row → van → global master switch.
    flags = global_flags()
    enable_route = _resolve_mode(van_route_mode, default=flags["enable_route"])
    require_pin = _resolve_mode(
        cfg_user.pin_mode if cfg_user else None,
        van_pin_mode,
        default=flags["require_pin"],
    )

    sales_person_name = None
    if sales_person:
        sales_person_name = frappe.db.get_value("Sales Person", sales_person, "sales_person_name") or sales_person

    currency = None
    if company:
        currency = frappe.db.get_value("Company", company, "default_currency")

    return {
        "user": user_doc.name,
        "full_name": user_doc.full_name,
        "language": user_doc.language or "en",
        "is_van_user": "Van User" in roles,
        "is_van_manager": "Van Manager" in roles,
        "is_system_manager": "System Manager" in roles,
        "roles": roles,
        "company": company,
        "branch": branch,
        "default_warehouse": default_warehouse,
        "warehouses": warehouses,
        "default_cost_center": default_cost_center,
        "cost_centers": cost_centers,
        "van_code": van_code,
        "currency": currency,
        "sales_person": sales_person,
        "sales_person_name": sales_person_name,
        "require_location": require_location,
        "selling_price_list": selling_price_list,
        "enable_route": enable_route,
        "require_pin": require_pin,
    }


def current_user_sales_person() -> str | None:
    """Shared helper — used by invoice.save to auto-tag sales_team."""
    return user_to_sales_person(frappe.session.user)


def user_to_sales_person(user: str | None) -> str | None:
    """Map a User to their linked Sales Person via Vansale Configuration.

    Used by the Van Route Plan desk-side customer filter (route.py
    customer_query) — the driver they're building the route for may
    not be the logged-in admin, so we can't use session.user.
    """
    if not user:
        return None
    return frappe.db.get_value(
        "Vansale Configuration User",
        {"user": user},
        "sales_person",
    )


def user_to_van_config(user: str | None) -> str | None:
    """Return the Vansale Configuration van_code a user is assigned to."""
    if not user:
        return None
    return frappe.db.get_value(
        "Vansale Configuration User",
        {"user": user},
        "parent",
    )


def current_user_van_price_list() -> str | None:
    """Return the `selling_price_list` configured on the current user's van.

    Used by `item._customer_price_list` to slot van-wide pricing between
    the Customer-specific default and Customer Group defaults. Guarded
    with `has_field` so older sites that haven't migrated yet keep
    working (the field lands in the v3 doctype bump).
    """
    van = user_to_van_config(frappe.session.user)
    if not van:
        return None
    try:
        if not frappe.get_meta("Vansale Configuration").has_field("selling_price_list"):
            return None
    except Exception:
        return None
    return frappe.db.get_value("Vansale Configuration", van, "selling_price_list") or None


@frappe.whitelist(methods=["GET"])
def vans() -> list[dict]:
    """For Van Managers: list all Vansale Configurations (admin picker)."""
    roles = frappe.get_roles(frappe.session.user)
    if "System Manager" not in roles and "Van Manager" not in roles:
        return []
    return frappe.get_all(
        "Vansale Configuration",
        fields=["name", "van_code", "van_name", "company", "branch"],
        order_by="van_code asc",
        limit=200,
    )
