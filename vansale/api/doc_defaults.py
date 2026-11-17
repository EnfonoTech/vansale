"""Values the van knows and a site may require on every selling document.

Called on each Quotation / Sales Order / Sales Invoice the app creates or
rebuilds, before it is saved. Only fills what is empty, so a value the
document already carries (copied from a quotation or an order, or chosen
by the salesman) is never replaced.

- `selling_price_list`: the van's price list, else Selling Settings'. A site
  without a Selling Settings default could not save any document at all.
- `branch`: the van's branch, else the user's default Branch permission, on
  doctypes that have the field. Set before save, because other apps read it
  early in validation (pricing, payment modes, cost center).
- `custom_sales_person`: the salesman, on sites where that field exists and
  is mandatory (same `has_field` fallback the app uses on Customer).
"""

from __future__ import annotations

import frappe


def apply_van_defaults(doc) -> None:
    from vansale.api.me import current_user_sales_person, current_user_van_price_list, van_default

    meta = doc.meta
    if meta.has_field("selling_price_list") and not doc.get("selling_price_list"):
        price_list = current_user_van_price_list() or frappe.db.get_single_value(
            "Selling Settings", "selling_price_list"
        )
        if price_list:
            doc.selling_price_list = price_list

    if meta.has_field("branch") and not doc.get("branch"):
        branch = van_default("Branch") or frappe.db.get_value(
            "User Permission",
            {"user": frappe.session.user, "allow": "Branch"},
            "for_value",
            order_by="is_default desc, creation asc",
        )
        if branch:
            doc.branch = branch

    if meta.has_field("custom_sales_person") and not doc.get("custom_sales_person"):
        sales_person = current_user_sales_person()
        if sales_person:
            doc.custom_sales_person = sales_person
