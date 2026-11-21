"""Steel Force setup check: the settings and per-van setup the app needs next
to sf_trading, listed for the office (Vansale Settings > Check Steel Force
setup). Reads only; nothing is changed.

Each finding: {"area", "item", "ok", "note"}. `ok` None = for information.
"""

from __future__ import annotations

import frappe
from frappe import _

from vansale import steelforce

_REQUESTER_ROLES = {"Sales User", "Counter Sale", "Branch Head"}


def _row(area: str, item: str, ok, note: str) -> dict:
    return {"area": area, "item": item, "ok": ok, "note": note}


def _mode(van: dict, field: str, global_value):
    value = van.get(field)
    return global_value if not value or value == "Follow Global" else value


def findings() -> list[dict]:
    from vansale.api.me import cr_number_field
    from vansale.vansale.doctype.vansale_settings.vansale_settings import global_flags

    flags = global_flags()
    out: list[dict] = []
    add = out.append

    # Site-wide settings
    add(_row(_("Site"), _("Credit sale only with a credit limit"), bool(flags.get("credit_needs_limit")),
             _("On: ERPNext treats no limit as unlimited; the Steel Force desk blocks credit without one.")))
    cr = cr_number_field()
    add(_row(_("Site"), _("CR number field"), bool(cr),
             _("Field {0}").format(cr) if cr else _("Not found: the CR box is hidden and every VAT customer is refused.")))
    add(_row(_("Site"), _("Advance payments"), not flags.get("allow_advance_payment"),
             _("Keep off: sf_trading refuses a receipt that names no invoice.")))
    add(_row(_("Site"), _("Returns without invoice"), not flags.get("allow_return_without_invoice"),
             _("Keep off: such a return skips the return window.")))
    add(_row(_("Site"), _("Customers a salesman finds"), None, flags.get("customer_scope") or "Own customers"))
    field_type = frappe.db.get_value("Custom Field", {"dt": "Sales Invoice", "fieldname": "custom_return_reason"}, "fieldtype")
    add(_row(_("Site"), _("Return reason field"), field_type in (None, "Data"),
             _("Type {0}").format(field_type or "-") if field_type else _("Not on this site")))

    vans = frappe.get_all(
        "Vansale Configuration",
        fields=["name", "company", "branch", "default_customer_group", "selling_price_list",
                "cash_sale_posting_mode", "advance_payment_mode", "return_without_invoice_mode"],
    )
    for van in vans:
        area = _("Van {0}").format(van.name)
        posting = _mode(van, "cash_sale_posting_mode", flags.get("cash_sale_posting"))
        add(_row(area, _("Cash sale posting"), posting == "Payment Entry",
                 posting if posting == "Payment Entry" else
                 _("{0}: set it to Payment Entry. sf_trading's cash due date and payment rules skip POS invoices.").format(posting or "-")))
        add(_row(area, _("Branch"), bool(van.branch),
                 van.branch or _("Not set: no Branch permission, so credit customers and branch payment modes are missing.")))
        if van.branch:
            has_config = frappe.db.exists("Branch Configuration", van.branch)
            add(_row(area, _("Branch Configuration"), bool(has_config),
                     _("Found") if has_config else _("Missing: the branch has no payment modes.")))
            try:
                from sf_trading.branch_price_list import allowed_price_lists, default_price_list
            except ImportError:
                allowed_price_lists = default_price_list = None
            if allowed_price_lists:
                allowed = allowed_price_lists(van.branch, "selling")
                if allowed and van.selling_price_list and van.selling_price_list not in allowed:
                    add(_row(area, _("Selling price list"), False,
                             _("{0} is not one of the branch's lists ({1}); the app uses {2}.").format(
                                 van.selling_price_list, ", ".join(allowed), default_price_list(van.branch, "selling") or "-")))
        group_ok = bool(van.default_customer_group) and not frappe.db.get_value(
            "Customer Group", van.default_customer_group, "is_group")
        selling_default = frappe.db.get_single_value("Selling Settings", "customer_group")
        settings_ok = bool(selling_default) and not frappe.db.get_value("Customer Group", selling_default, "is_group")
        ok = group_ok or settings_ok
        add(_row(area, _("Default customer group"), ok,
                 (van.default_customer_group if group_ok else selling_default) if ok
                 else _("No leaf group on the van or in Selling Settings: new customers are refused.")))
        if _mode(van, "advance_payment_mode", None) == "Enabled":
            add(_row(area, _("Advance payments"), False, _("Enabled for this van: sf_trading refuses them.")))
        if _mode(van, "return_without_invoice_mode", None) == "Enabled":
            add(_row(area, _("Returns without invoice"), False, _("Enabled for this van: they skip the return window.")))
        users = frappe.get_all("Vansale Configuration User", {"parent": van.name}, pluck="user")
        for user in users:
            roles = set(frappe.get_roles(user))
            add(_row(area, user, None, ", ".join(filter(None, [
                _("can request cancellation") if roles & _REQUESTER_ROLES else _("no requester role (Request cancellation hidden)"),
                _("B2B Creator") if "B2B Creator" in roles else _("B2C customers only"),
            ]))))
        loyalty = steelforce.loyalty_config(van.company)
        add(_row(area, _("Loyalty at payment"), None,
                 _("Up to {0}").format(loyalty["max"]) if loyalty else _("Not set up on {0}").format(van.company)))
    return out


# frappe.call from the desk form posts; reads only, so either method.
@frappe.whitelist(methods=["GET", "POST"])
def check() -> dict:
    """The setup findings as an HTML table for the office."""
    frappe.only_for(("System Manager", "Van Manager"))
    if not steelforce.is_active():
        return {"html": _("sf_trading is not installed on this site: nothing to check.")}
    rows = findings()
    esc = frappe.utils.escape_html
    bad = sum(1 for r in rows if r["ok"] is False)
    good = sum(1 for r in rows if r["ok"] is True)
    notes = sum(1 for r in rows if r["ok"] is None)
    # The desk's own pills: red = to fix, green = fine, grey = for information.
    pill = {
        False: ("red", _("Fix")),
        True: ("green", _("OK")),
        None: ("gray", _("Info")),
    }

    def item(r) -> str:
        color, label = pill[r["ok"]]
        return (
            "<div style='display:flex;gap:10px;align-items:flex-start;padding:9px 0;"
            "border-top:1px solid var(--border-color)'>"
            f"<span class='indicator-pill {color}' style='flex:none;width:58px;justify-content:center'>{label}</span>"
            "<div style='min-width:0;flex:1'>"
            f"<div style='font-weight:600;overflow-wrap:anywhere'>{esc(r['item'])}</div>"
            f"<div class='text-muted small' style='overflow-wrap:anywhere'>{esc(str(r['note'] or ''))}</div>"
            "</div></div>"
        )

    groups: dict[str, list[dict]] = {}
    for r in rows:
        groups.setdefault(r["area"], []).append(r)
    order = {False: 0, None: 1, True: 2}  # what to fix first, then notes, then fine
    sections = []
    for area, items in groups.items():
        items.sort(key=lambda r: order[r["ok"]])
        to_fix = sum(1 for r in items if r["ok"] is False)
        badge = (
            f"<span class='indicator-pill red' style='margin-inline-start:8px'>{to_fix} {_('to fix')}</span>"
            if to_fix else ""
        )
        sections.append(
            "<div style='margin-top:16px'>"
            f"<div style='display:flex;align-items:center;font-weight:700;font-size:14px;margin-bottom:2px'>{esc(area)}{badge}</div>"
            + "".join(item(r) for r in items)
            + "</div>"
        )
    head = (
        "<div style='display:flex;gap:8px;flex-wrap:wrap;align-items:center'>"
        + (f"<span class='indicator-pill red'>{bad} {_('to fix')}</span>" if bad else
           f"<span class='indicator-pill green'>{_('Nothing to fix')}</span>")
        + f"<span class='indicator-pill green'>{good} {_('OK')}</span>"
        + f"<span class='indicator-pill gray'>{notes} {_('for information')}</span>"
        + "</div>"
    )
    html = f"<div style='max-width:100%'>{head}{''.join(sections)}</div>"
    return {"html": html, "to_fix": bad}
