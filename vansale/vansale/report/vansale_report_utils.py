"""Shared helpers for the Vansale reports.

**Van attribution is via `owner`, not warehouse or sales person.** That is a
deliberate constraint, not a shortcut: `Payment Entry` created by the app
carries no warehouse, no cost center and no sales team row (see
`vansale.api.payment.create`), so the only field common to Sales Invoice,
Payment Entry and Van Daily Visit that identifies the van is who created the
document. `Vansale Configuration User` maps user → van, one row per user.

Consequence worth knowing: a document an office user creates on a driver's
behalf is attributed to the office user, and shows with a blank van. The
reports surface those rather than hiding them, so the gap is visible.
"""

from __future__ import annotations

import frappe
from frappe import _

MANAGER_ROLES = {"Van Manager", "System Manager", "Accounts Manager"}


def user_van(user: str | None = None) -> str | None:
    """The Vansale Configuration this user drives for, if any."""
    return frappe.db.get_value(
        "Vansale Configuration User", {"user": user or frappe.session.user}, "parent"
    )


def is_manager() -> bool:
    from vansale.api.me import is_office_user

    return is_office_user(default_roles=MANAGER_ROLES)


def van_scope(filters: dict) -> tuple[str, dict]:
    """Build the van/user WHERE fragment plus its bind values.

    A driver may only ever see their own van, regardless of what the filter
    panel was set to — the report is a whitelisted endpoint like any other, so
    the restriction has to be enforced here rather than in the UI.
    """
    conditions: list[str] = []
    values: dict = {}

    if not is_manager():
        own = user_van()
        if not own:
            # No van assigned and not a manager → nothing to show. `1=0` keeps
            # the caller's SQL shape intact.
            return " AND 1=0", values
        conditions.append("vcu.parent = %(own_van)s")
        values["own_van"] = own
    elif filters.get("van"):
        conditions.append("vcu.parent = %(van)s")
        values["van"] = filters["van"]

    if filters.get("user"):
        conditions.append("doc.owner = %(user)s")
        values["user"] = filters["user"]

    return (" AND " + " AND ".join(conditions)) if conditions else "", values


def date_range(filters: dict, field: str) -> tuple[str, dict]:
    """Inclusive posting-date window. Both bounds are required by the JSON."""
    from_date = filters.get("from_date")
    to_date = filters.get("to_date")
    if not from_date or not to_date:
        frappe.throw(_("From Date and To Date are required"))
    if from_date > to_date:
        frappe.throw(_("From Date cannot be after To Date"))
    return (
        f" AND doc.{field} BETWEEN %(from_date)s AND %(to_date)s",
        {"from_date": from_date, "to_date": to_date},
    )


def company_scope(filters: dict) -> tuple[str, dict]:
    if filters.get("company"):
        return " AND doc.company = %(company)s", {"company": filters["company"]}
    return "", {}
