"""Customer endpoints scoped to the logged-in salesperson."""

from __future__ import annotations

from typing import Optional

import frappe
from frappe import _

from vansale.api.datetime_util import naive_site_to_utc_iso


_LIST_FIELDS = [
    "name",
    "customer_name",
    "customer_group",
    "territory",
    "mobile_no",
    "email_id",
    "tax_id",
    "customer_primary_address",
    "default_currency",
    "disabled",
    "modified",
]


def _customer_filters_for_user() -> dict:
    """Return the base filter set for Customer queries.

    Customer-level scoping happens via Frappe's User Permission system
    (Territory, Customer Group) when admins configure it. The Vansale
    Configuration pattern — mirroring RMAX's Branch Configuration —
    doesn't create Customer-level User Permissions, so every Van User
    sees all active customers unless the admin restricts explicitly.
    """
    return {"disabled": 0}


@frappe.whitelist(methods=["GET"])
def list_mine(limit: int = 50, search: Optional[str] = None) -> list[dict]:
    filters = _customer_filters_for_user()
    or_filters = {}
    if search:
        s = f"%{search}%"
        or_filters = {"customer_name": ["like", s], "mobile_no": ["like", s], "tax_id": ["like", s]}
    rows = frappe.get_all(
        "Customer",
        filters=filters,
        or_filters=or_filters or None,
        fields=_LIST_FIELDS,
        limit=int(limit),
        order_by="modified desc",
    )
    for r in rows:
        r["modified"] = naive_site_to_utc_iso(r.get("modified"))
    return rows


@frappe.whitelist(methods=["GET"])
def detail(name: str) -> dict:
    if not name:
        frappe.throw(_("Customer name required"))
    doc = frappe.get_doc("Customer", name)
    addresses = frappe.db.sql(
        """
        SELECT a.name, a.address_line1, a.address_line2, a.city, a.state, a.pincode, a.country,
               a.is_primary_address, a.is_shipping_address, a.phone
        FROM `tabAddress` a
        JOIN `tabDynamic Link` l ON l.parent = a.name
        WHERE l.link_doctype = 'Customer' AND l.link_name = %s
        ORDER BY a.is_primary_address DESC, a.creation DESC
        """,
        (name,),
        as_dict=True,
    )
    outstanding = (
        frappe.db.sql(
            """
            SELECT COALESCE(SUM(outstanding_amount), 0)
            FROM `tabSales Invoice`
            WHERE customer = %s AND docstatus = 1
            """,
            (name,),
        )[0][0]
        or 0
    )
    return {
        "name": doc.name,
        "customer_name": doc.customer_name,
        "customer_group": doc.customer_group,
        "territory": doc.territory,
        "mobile_no": doc.mobile_no,
        "email_id": doc.email_id,
        "tax_id": doc.tax_id,
        "default_currency": doc.default_currency,
        "addresses": addresses,
        "outstanding": float(outstanding or 0),
        "modified": naive_site_to_utc_iso(doc.modified),
    }


@frappe.whitelist(methods=["POST"])
def create(
    customer_name: str,
    mobile_no: str | None = None,
    territory: str | None = None,
    tax_id: str | None = None,
    customer_group: str | None = None,
    customer_type: str | None = None,         # "b2b" | "b2c"
    email_id: str | None = None,
    address_line1: str | None = None,
    address_line2: str | None = None,
    city: str | None = None,
    state: str | None = None,
    pincode: str | None = None,
    country: str | None = None,
) -> dict:
    """Create a Customer + optional primary Address.

    B2B (customer_type="b2b") requires address_line1 + city (per PDF §2b).
    B2C (customer_type="b2c") default — Individual, address optional.
    """
    if not customer_name:
        frappe.throw(_("Customer name required"))
    ctype = (customer_type or "b2c").lower()
    is_b2b = ctype == "b2b"
    if is_b2b and (not address_line1 or not city):
        frappe.throw(_("Address (line 1 + city) is mandatory for B2B customers"))

    doc = frappe.get_doc({
        "doctype": "Customer",
        "customer_name": customer_name,
        "customer_type": "Company" if is_b2b else "Individual",
        "mobile_no": mobile_no,
        "email_id": email_id,
        "territory": territory or frappe.db.get_single_value("Selling Settings", "territory") or "All Territories",
        "customer_group": customer_group or frappe.db.get_single_value("Selling Settings", "customer_group") or "All Customer Groups",
        "tax_id": tax_id,
    })
    doc.insert(ignore_permissions=False)

    # Create Address if fields provided (mandatory for B2B, optional for B2C).
    address_name: str | None = None
    if address_line1:
        addr = frappe.get_doc({
            "doctype": "Address",
            "address_title": customer_name,
            "address_type": "Billing",
            "address_line1": address_line1,
            "address_line2": address_line2,
            "city": city,
            "state": state,
            "pincode": pincode,
            "country": country or frappe.db.get_single_value("Global Defaults", "country") or "Saudi Arabia",
            "phone": mobile_no,
            "email_id": email_id,
            "is_primary_address": 1,
            "is_shipping_address": 1,
            "links": [{"link_doctype": "Customer", "link_name": doc.name}],
        })
        addr.insert(ignore_permissions=False)
        address_name = addr.name
        # Link back to customer as primary address.
        frappe.db.set_value("Customer", doc.name, "customer_primary_address", address_name)

    frappe.db.commit()
    return {
        "name": doc.name,
        "customer_name": doc.customer_name,
        "customer_type": doc.customer_type,
        "address": address_name,
    }


@frappe.whitelist(methods=["GET"])
def summary(customer: str) -> dict:
    """Aggregates for the customer detail tile strip."""
    outstanding = frappe.db.sql(
        """
        SELECT COALESCE(SUM(outstanding_amount), 0)
        FROM `tabSales Invoice`
        WHERE customer = %s AND docstatus = 1
        """,
        (customer,),
    )[0][0] or 0
    last_invoice = frappe.db.get_value(
        "Sales Invoice", {"customer": customer, "docstatus": 1},
        ["name", "grand_total", "posting_date"],
        order_by="posting_date desc",
        as_dict=True,
    )
    if last_invoice:
        last_invoice["posting_date"] = naive_site_to_utc_iso(last_invoice.get("posting_date"))
    return {
        "outstanding": float(outstanding or 0),
        "last_invoice": last_invoice,
    }
