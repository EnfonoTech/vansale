"""The company a user works in, for the places that fill one in when none is given.

A site can hold more than one company. A user whose Company User Permissions
leave out the site's default company must never be put on it:
get_user_default("Company") returns nothing for such a user, and falling back
to Global Defaults then made van invoices in a company the user cannot even
open.
"""

from __future__ import annotations

import frappe
from frappe import _


def permitted_companies(user: str | None = None) -> list[str]:
    """The companies the user's Company User Permissions allow; [] when the
    user has no Company restriction (Administrator never has one, as Frappe
    ignores its User Permissions)."""
    user = user or frappe.session.user
    if user == "Administrator":
        return []
    rows = frappe.get_all(
        "User Permission",
        filters={"user": user, "allow": "Company"},
        pluck="for_value",
        distinct=True,
    )
    return list(dict.fromkeys(row for row in rows if row))


def get_user_company(user: str | None = None, throw: bool = False) -> str | None:
    """The company the user works in.

    1. the user's default Company: their Company User Permission with Is Default
       ticked, else frappe.defaults.get_user_default (their own default, or the
       site's when they may use it);
    2. else the only company the user is permitted (Company User Permissions);
    3. else, ONLY for a user with no Company restriction at all, the site's
       default company (they may post anywhere, so the old behaviour is kept for
       them -- Administrator and the scheduler too);
    4. else None -- a restricted user never falls back to a company they cannot
       access. With throw=True, raise a clear translated message asking to set a
       default company.
    """
    user = user or frappe.session.user
    permitted = permitted_companies(user)
    company = None
    if permitted:
        # get_user_default prefers the user's (or the site's) "company" default
        # to the Is Default permission
        company = frappe.db.get_value(
            "User Permission",
            {"user": user, "allow": "Company", "is_default": 1},
            "for_value",
        )
    if not company and user == frappe.session.user:
        # it reads the session user's permissions, so it is asked only about that user
        company = frappe.defaults.get_user_default("Company")
    if company and (not permitted or company in permitted):
        return company
    if len(permitted) == 1:
        return permitted[0]
    if not permitted:
        company = frappe.defaults.get_global_default("company")
        if company:
            return company
    if throw:
        frappe.throw(
            _(
                "No default company is set for user {0}. Ask your administrator to set a Company user permission with Is Default ticked."
            ).format(user)
        )
    return None
