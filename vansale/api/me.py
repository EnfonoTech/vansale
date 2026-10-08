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
    sales_person = user_to_sales_person(user)
    require_location = False
    selling_price_list: str | None = None
    van_route_mode: str | None = None
    van_pin_mode: str | None = None
    van_uom_mode: str | None = None
    van_customer_price_mode: str | None = None
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
            wanted = [
                f
                for f in ("route_mode", "pin_mode", "uom_change_mode", "customer_price_mode")
                if meta.has_field(f)
            ]
            if wanted:
                row = frappe.db.get_value(
                    "Vansale Configuration", van_code, wanted, as_dict=True
                ) or {}
                van_route_mode = row.get("route_mode")
                van_pin_mode = row.get("pin_mode")
                van_uom_mode = row.get("uom_change_mode")
                van_customer_price_mode = row.get("customer_price_mode")
        except Exception:
            van_route_mode = van_pin_mode = van_uom_mode = van_customer_price_mode = None

    # Most specific wins: user row → van → global master switch.
    flags = global_flags()
    enable_route = _resolve_mode(van_route_mode, default=flags["enable_route"])
    require_pin = _resolve_mode(
        cfg_user.pin_mode if cfg_user else None,
        van_pin_mode,
        default=flags["require_pin"],
    )
    allow_uom_change = _resolve_mode(van_uom_mode, default=flags["allow_uom_change"])
    use_customer_price = _resolve_mode(
        van_customer_price_mode, default=flags.get("use_customer_price", False)
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
        "allow_uom_change": allow_uom_change,
        "use_customer_price": use_customer_price,
        "currency_precision": rate_precision(),
        "cash_sale_posting": cash_sale_settings(user)["posting"],
        "split_payment": split_payment_allowed(user),
        "advance_payment": advance_payment_allowed(user),
        "return_without_invoice": return_without_invoice_allowed(user),
        "print_formats": print_formats(user),
        "print": print_behaviour(user),
        "customer_form": customer_form_config(),
    }


def current_user_sales_person() -> str | None:
    """Shared helper — used by invoice.save to auto-tag sales_team."""
    return user_to_sales_person(frappe.session.user)


def user_to_sales_person(user: str | None) -> str | None:
    """Map a User to their Sales Person.

    Vansale Configuration User.sales_person first; else the user's "Sales
    Person" User Permission (default one first) — how sites without a
    sales person on the van row (e.g. Badria) link salesmen.

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
    ) or frappe.db.get_value(
        "User Permission",
        {"user": user, "allow": "Sales Person"},
        "for_value",
        order_by="is_default desc, creation asc",
    )


def is_office_user(user: str | None = None, default_roles: frozenset[str] | set[str] = frozenset()) -> bool:
    """Whether `user` sees everyone's data (office staff, not a driver).

    Vansale Settings "Office roles" when set; otherwise `default_roles`, the
    caller's previous hard-coded set, so sites that haven't set it behave as
    before. A site whose drivers hold manager roles (Badria: Accounts / Stock
    Manager through a Role Profile) lists only its real office roles.
    """
    roles = set(frappe.get_roles(user or frappe.session.user))
    configured = set(
        frappe.get_all("Vansale Office Role", filters={"parenttype": "Vansale Settings"}, pluck="role")
    )
    return bool(roles & (configured or set(default_roles)))


# Second customer name fields seen on sites, most common first.
_CUSTOMER_NAME_2_CANDIDATES = (
    "custom_customer_name_english",
    "custom_customer_name_arabic",
    "customer_name_in_arabic",
    "custom_arabic_name",
)


def customer_name_2_field() -> str | None:
    """Customer field for a second name (e.g. Arabic / English).

    Vansale Settings "Second customer name field" if it exists on Customer,
    else the first known field that exists; None when the site has none.
    """
    meta = frappe.get_meta("Customer")
    configured = frappe.db.get_single_value("Vansale Settings", "customer_name_2_field")
    for fieldname in ([configured] if configured else []) + list(_CUSTOMER_NAME_2_CANDIDATES):
        if fieldname and meta.has_field(fieldname):
            return fieldname
    return None


def customer_form_config() -> dict:
    """Optional customer fields this site has, for the app's customer form."""
    meta = frappe.get_meta("Customer")
    name_2 = customer_name_2_field()
    return {
        "name_2": {"field": name_2, "label": _(meta.get_label(name_2))} if name_2 else None,
        "cr_number": meta.has_field("custom_cr_number"),
        # ZATCA "additional number" only where the site's Address has a field for it.
        "additional_number": any(
            frappe.get_meta("Address").has_field(f) for f in ("custom_additional_number", "additional_number")
        ),
    }


def user_to_van_config(user: str | None) -> str | None:
    """Return the Vansale Configuration van_code a user is assigned to."""
    if not user:
        return None
    return frappe.db.get_value(
        "Vansale Configuration User",
        {"user": user},
        "parent",
    )


def rate_precision() -> int:
    """Decimals for rates/amounts — the precision ERPNext uses for Sales
    Invoice Item.rate (field precision → System Settings currency precision
    → number format)."""
    from frappe.model.meta import get_field_precision

    return get_field_precision(frappe.get_meta("Sales Invoice Item").get_field("rate"))


DEFAULT_INVOICE_PRINT_FORMAT = "Vansale Tax Invoice"
DEFAULT_RECEIPT_PRINT_FORMAT = "Vansale Payment Receipt"


def _van_value(fieldname: str, user: str | None = None):
    """A field of the user's Vansale Configuration (None if unset / no van)."""
    van = user_to_van_config(user or frappe.session.user)
    if not van or not frappe.get_meta("Vansale Configuration").has_field(fieldname):
        return None
    return frappe.db.get_value("Vansale Configuration", van, fieldname)


def _van_or_global(van_field: str, global_key: str, default, user: str | None = None):
    value = _van_value(van_field, user)
    if value and value != "Follow Global":
        return value
    return global_flags().get(global_key) or default


def cash_sale_settings(user: str | None = None) -> dict:
    """How a cash sale is posted: van → Vansale Settings.

    posting: "POS Invoice" (is_pos; ERPNext applies the company's POS Profile)
             or "Payment Entry" (normal invoice + Payment Entry against it).
    payment_entry_status: "Submit" or "Draft" (office submits later).
    """
    return {
        "posting": _van_or_global("cash_sale_posting_mode", "cash_sale_posting", "POS Invoice", user),
        "payment_entry_status": _van_or_global(
            "cash_payment_entry_status_mode", "cash_payment_entry_status", "Submit", user
        ),
    }


def collection_payment_entry_status(user: str | None = None) -> str:
    """Draft / Submit for Payment Entries from Payment Collection: van →
    Vansale Settings; "Same as cash sale" (the default) keeps the cash-sale
    status, as before the two were separate."""
    status = _van_or_global(
        "collection_payment_entry_status_mode", "collection_payment_entry_status", "Same as cash sale", user
    )
    if status in ("Submit", "Draft"):
        return status
    return cash_sale_settings(user)["payment_entry_status"]


def advance_payment_allowed(user: str | None = None) -> bool:
    """Whether a collection may be taken as an advance (left unallocated):
    van → Vansale Settings (default off)."""
    return _resolve_mode(
        _van_value("advance_payment_mode", user), default=global_flags().get("allow_advance_payment", False)
    )


def split_payment_allowed(user: str | None = None) -> bool:
    """Whether a cash sale may be paid with several modes: van → Vansale Settings (default off)."""
    return _resolve_mode(
        _van_value("split_payment_mode", user), default=global_flags().get("allow_split_payment", False)
    )


def return_without_invoice_allowed(user: str | None = None) -> bool:
    """Whether a return may be made without an original invoice: van → Vansale Settings (default off)."""
    return _resolve_mode(
        _van_value("return_without_invoice_mode", user),
        default=global_flags().get("allow_return_without_invoice", False),
    )


def print_formats(user: str | None = None) -> dict:
    """Print formats the app uses: van → Vansale Settings → the app's own."""
    return {
        "invoice": _van_or_global(
            "invoice_print_format", "invoice_print_format", DEFAULT_INVOICE_PRINT_FORMAT, user
        ),
        "receipt": _van_or_global(
            "receipt_print_format", "receipt_print_format", DEFAULT_RECEIPT_PRINT_FORMAT, user
        ),
    }


def print_behaviour(user: str | None = None) -> dict:
    """Print button / after-submit behaviour and copies: van → Vansale Settings."""
    flags = global_flags()
    return {
        "direct": _resolve_mode(_van_value("direct_print_mode", user), default=flags.get("direct_print", False)),
        "after_submit": _resolve_mode(
            _van_value("print_after_submit_mode", user), default=flags.get("print_after_submit", False)
        ),
        "copies": max(1, int(_van_value("print_copies", user) or flags.get("print_copies") or 1)),
    }


def customer_price_enabled(user: str | None = None) -> bool:
    """Whether customer-specific Item Prices apply for this user's van.

    Van `customer_price_mode` → Vansale Settings `use_customer_price` (off by
    default, since most sites price from the price list only).
    """
    van = user_to_van_config(user or frappe.session.user)
    van_mode = None
    if van and frappe.get_meta("Vansale Configuration").has_field("customer_price_mode"):
        van_mode = frappe.db.get_value("Vansale Configuration", van, "customer_price_mode")
    return _resolve_mode(van_mode, default=global_flags().get("use_customer_price", False))


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
