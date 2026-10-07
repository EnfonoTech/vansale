"""Customer endpoints scoped to the logged-in salesperson."""

from __future__ import annotations

import re
from typing import Optional

import frappe
from frappe import _

from vansale.api.access import check_read
from vansale.api.outbox import claim
from vansale.api.datetime_util import naive_site_to_utc_iso, parse_client_ts
from vansale.api.me import current_user_sales_person, customer_name_2_field, is_office_user, user_to_van_config


def _record_customer_outbox(
    client_id: str | None,
    ref_name: str,
    posting_ts: str | None,
    payload: dict,
) -> None:
    if not client_id:
        return
    if frappe.db.exists("Vansale Outbox", client_id):
        doc = frappe.get_doc("Vansale Outbox", client_id)
    else:
        doc = frappe.new_doc("Vansale Outbox")
        doc.client_id = client_id
    doc.event_type = "customer"
    doc.user = frappe.session.user
    doc.client_ts = parse_client_ts(posting_ts) if posting_ts else None
    doc.drained_at = frappe.utils.now_datetime()
    doc.status = "processed"
    doc.ref_doctype = "Customer"
    doc.ref_name = ref_name
    doc.payload_json = frappe.as_json(payload)
    doc.save(ignore_permissions=True)


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


def _assigned_customer_names(sales_person: str | None) -> list[str] | None:
    """Names of customers assigned to the given sales person.

    Assignment is read from the Customer → Sales Team child table — the
    same column that `vansale.api.invoice.save` writes to when tagging
    new invoices. Returns ``None`` when there's no sales_person to scope
    by (admins / non-van users see everything); returns ``[]`` when the
    sales person has nothing assigned (UI shows an empty list rather
    than silently falling back to every customer).
    """
    if not sales_person:
        return None
    rows = frappe.db.sql(
        """
        SELECT DISTINCT parent AS name
        FROM `tabSales Team`
        WHERE parenttype = 'Customer' AND sales_person = %s
        """,
        (sales_person,),
        as_dict=True,
    )
    return [r["name"] for r in rows]


def _sales_person_customers(sales_person: str | None) -> set[str]:
    """Customers linked to a sales person: Sales Team rows, plus
    Customer.custom_sales_person on sites that have that field (Badria)."""
    if not sales_person:
        return set()
    names = set(_assigned_customer_names(sales_person) or [])
    if frappe.get_meta("Customer").has_field("custom_sales_person"):
        names.update(frappe.get_all("Customer", {"custom_sales_person": sales_person}, pluck="name"))
    return names


# KSA ZATCA address fields: names differ by app / version (ksa_compliance uses
# custom_building_number / custom_area). Written to the first that exists.
_ADDRESS_FIELDS = {
    "building_number": ("custom_building_number", "building_number"),
    "additional_number": ("custom_additional_number", "additional_number"),
    "district": ("custom_area", "custom_district", "district"),
}
_KSA = "Saudi Arabia"


def _address_field(key: str) -> Optional[str]:
    meta = frappe.get_meta("Address")
    return next((f for f in _ADDRESS_FIELDS[key] if meta.has_field(f)), None)


def _validate_ksa(
    country: Optional[str],
    is_b2b: bool,
    vat: Optional[str] = None,
    building_number: Optional[str] = None,
    pincode: Optional[str] = None,
    district: Optional[str] = None,
    street: Optional[str] = None,
    city: Optional[str] = None,
) -> None:
    """ZATCA rules for Saudi customers: VAT 15 digits starting and ending
    with 3, building number 4 digits, postal code 5 digits; a B2B (standard
    invoice) buyer needs street, building number, district, city and postal
    code."""
    if (country or _KSA) != _KSA:
        return
    errors = []
    if vat and not re.fullmatch(r"3\d{13}3", vat.strip()):
        errors.append(_("VAT number must be 15 digits, starting and ending with 3"))
    if building_number and not re.fullmatch(r"\d{4}", str(building_number).strip()):
        errors.append(_("Building number must be 4 digits"))
    if pincode and not re.fullmatch(r"\d{5}", str(pincode).strip()):
        errors.append(_("Postal code must be 5 digits"))
    if is_b2b:
        missing = [
            label
            for label, value in (
                (_("Street"), street),
                (_("Building number"), building_number),
                (_("District"), district),
                (_("City"), city),
                (_("Postal code"), pincode),
            )
            if not (value and str(value).strip())
        ]
        if missing:
            errors.append(_("Required for B2B customers: {0}").format(", ".join(missing)))
    if errors:
        frappe.throw("<br>".join(errors), title=_("Customer details"))


def _title_field() -> Optional[str]:
    """Customer's title field when it isn't customer_name (Badria shows
    custom_customer_name_english as the customer's title)."""
    meta = frappe.get_meta("Customer")
    tf = meta.title_field
    return tf if tf and tf != "customer_name" and meta.has_field(tf) else None


def _display_names(row) -> tuple[str, Optional[str]]:
    """(name to show, second name) — title field first, as desk shows it."""
    tf, name_2 = _title_field(), customer_name_2_field()
    title = row.get(tf) if tf else None
    display = title or row.get("customer_name")
    other = row.get("customer_name") if title else (row.get(name_2) if name_2 else None)
    return display, (other if other and other != display else None)


def _default_leaf(doctype: str, van_field: str, selling_settings_field: str) -> Optional[str]:
    """Default Customer Group / Territory for a new customer.

    The van's default, else Selling Settings, else none — never a group node
    (ERPNext rejects "Cannot select a Group type Customer Group"; falling back
    to "All Customer Groups" made customer create fail on sites without a
    Selling Settings default).
    """
    van = user_to_van_config(frappe.session.user)
    candidates = [
        frappe.db.get_value("Vansale Configuration", van, van_field)
        if van and frappe.get_meta("Vansale Configuration").has_field(van_field)
        else None,
        frappe.db.get_single_value("Selling Settings", selling_settings_field),
    ]
    for value in candidates:
        if value and not frappe.db.get_value(doctype, value, "is_group"):
            return value
    return None


def _vat_field() -> Optional[str]:
    """ZATCA VAT field (ksa_compliance) when the site has it."""
    return "custom_vat_registration_number" if frappe.get_meta("Customer").has_field(
        "custom_vat_registration_number"
    ) else None


@frappe.whitelist(methods=["GET"])
def list_mine(limit: int = 50, search: Optional[str] = None) -> list[dict]:
    filters: dict = {"disabled": 0}

    # Van users see the union of customers linked to their Sales Person
    # (Sales Team / custom_sales_person) and customers they created. Office
    # users (Vansale Settings "Office roles", default System / Van Manager)
    # see all. Computed up front because get_list's or_filters are AND-ed
    # with filters; search stays an AND-layer over that set.
    if not is_office_user(default_roles={"System Manager", "Van Manager"}):
        allowed = _sales_person_customers(current_user_sales_person()) | set(
            frappe.get_all("Customer", {"owner": frappe.session.user}, pluck="name")
        )
        if not allowed:
            return []
        filters["name"] = ["in", list(allowed)]

    name_2, vat, title = customer_name_2_field(), _vat_field(), _title_field()
    fields = _LIST_FIELDS + [f for f in {name_2, vat, title} if f]
    or_filters = {}
    if search:
        s = f"%{search}%"
        or_filters = {"customer_name": ["like", s], "mobile_no": ["like", s], "tax_id": ["like", s]}
        for f in {name_2, vat, title}:
            if f:
                or_filters[f] = ["like", s]
    # get_list (not get_all): role permissions and the user's User
    # Permissions apply, e.g. a salesman limited to some Customer Groups.
    rows = frappe.get_list(
        "Customer",
        filters=filters,
        or_filters=or_filters or None,
        fields=fields,
        limit=int(limit),
        order_by="modified desc",
    )
    for r in rows:
        r["modified"] = naive_site_to_utc_iso(r.get("modified"))
        # Stable keys for the app whatever the site calls these fields.
        r["customer_name_2"] = r.get(name_2) if name_2 else None
        r["vat_number"] = (r.get(vat) if vat else None) or r.get("tax_id")
        r["display_name"], r["secondary_name"] = _display_names(r)
    return rows


@frappe.whitelist(methods=["POST"])
def save_address(
    customer: str,
    address: str | None = None,
    address_line1: str | None = None,
    address_line2: str | None = None,
    city: str | None = None,
    state: str | None = None,
    pincode: str | None = None,
    country: str | None = None,
    building_number: str | None = None,
    additional_number: str | None = None,
    district: str | None = None,
    phone: str | None = None,
) -> dict:
    """Edit a customer's address, or add one when `address` is empty."""
    check_read("Customer", customer)
    cust = frappe.get_doc("Customer", customer)
    country = country or frappe.db.get_single_value("Global Defaults", "country") or _KSA
    if not address_line1 or not city:
        frappe.throw(_("Street and city are required"))
    _validate_ksa(
        country, cust.customer_type == "Company", None, building_number, pincode, district, address_line1, city
    )

    if address:
        doc = frappe.get_doc("Address", address)
        if not any(l.link_doctype == "Customer" and l.link_name == customer for l in doc.links):
            frappe.throw(_("Address {0} does not belong to {1}").format(address, customer), frappe.PermissionError)
    else:
        doc = frappe.new_doc("Address")
        doc.address_title = cust.customer_name
        doc.address_type = "Billing"
        doc.is_primary_address = 0 if cust.customer_primary_address else 1
        doc.append("links", {"link_doctype": "Customer", "link_name": customer})

    doc.update({
        "address_line1": address_line1,
        "address_line2": address_line2,
        "city": city,
        "state": state,
        "pincode": pincode,
        "country": country,
        "phone": phone,
    })
    for key, value in (
        ("building_number", building_number),
        ("additional_number", additional_number),
        ("district", district),
    ):
        field = _address_field(key)
        if field:
            doc.set(field, str(value).strip() if value else None)
    doc.save()
    if not cust.customer_primary_address:
        frappe.db.set_value("Customer", customer, "customer_primary_address", doc.name)
    return {"name": doc.name}


@frappe.whitelist(methods=["POST"])
def save_contact(customer: str, mobile_no: str | None = None, email_id: str | None = None) -> dict:
    """Set the customer's mobile / email.

    In ERPNext these live on the customer's primary Contact (Customer.mobile_no
    and email_id only copy it), so update that Contact, or create one and make
    it primary when the customer has none.
    """
    check_read("Customer", customer)
    cust = frappe.get_doc("Customer", customer)
    mobile_no = (mobile_no or "").strip()
    email_id = (email_id or "").strip()

    if cust.customer_primary_contact:
        contact = frappe.get_doc("Contact", cust.customer_primary_contact)
    else:
        contact = frappe.new_doc("Contact")
        contact.first_name = cust.customer_name
        contact.append("links", {"link_doctype": "Customer", "link_name": customer})

    if mobile_no:
        row = next((p for p in contact.phone_nos if p.is_primary_mobile_no), None)
        if row:
            row.phone = mobile_no
        else:
            contact.add_phone(mobile_no, is_primary_mobile_no=1)
    else:
        contact.set("phone_nos", [p for p in contact.phone_nos if not p.is_primary_mobile_no])
    if email_id:
        row = next((e for e in contact.email_ids if e.is_primary), None)
        if row:
            row.email_id = email_id
        else:
            contact.add_email(email_id, is_primary=1)
    else:
        contact.set("email_ids", [e for e in contact.email_ids if not e.is_primary])
    contact.save()

    # Customer copies the primary contact's mobile / email (fetch_from).
    frappe.db.set_value(
        "Customer",
        customer,
        {"customer_primary_contact": contact.name, "mobile_no": mobile_no or None, "email_id": email_id or None},
    )
    return {"contact": contact.name, "mobile_no": mobile_no, "email_id": email_id}


@frappe.whitelist(methods=["GET"])
def detail(name: str) -> dict:
    if not name:
        frappe.throw(_("Customer name required"))
    check_read("Customer", name)
    doc = frappe.get_doc("Customer", name)
    address_names = frappe.get_all(
        "Dynamic Link",
        filters={"link_doctype": "Customer", "link_name": name, "parenttype": "Address"},
        pluck="parent",
    )
    fields = ["name", "address_line1", "address_line2", "city", "state", "pincode", "country",
              "is_primary_address", "is_shipping_address", "phone"]
    mapped = {key: _address_field(key) for key in _ADDRESS_FIELDS}
    addresses = frappe.get_all(
        "Address",
        filters={"name": ["in", address_names or [""]]},
        fields=fields + [f for f in mapped.values() if f],
        order_by="is_primary_address desc, creation desc",
    )
    for a in addresses:
        # Stable keys for the app whatever the site calls these fields.
        for key, field in mapped.items():
            a[key] = a.pop(field, None) if field and field != key else a.get(key)
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
    display_name, secondary_name = _display_names(doc)
    vat = _vat_field()
    return {
        "name": doc.name,
        "customer_name": doc.customer_name,
        "display_name": display_name,
        "secondary_name": secondary_name,
        "vat_number": (doc.get(vat) if vat else None) or doc.tax_id,
        "customer_type": doc.customer_type,
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
    building_number: str | None = None,
    additional_number: str | None = None,
    district: str | None = None,
    client_id: str | None = None,
    posting_ts: str | None = None,
    cr_number: str | None = None,
    customer_name_2: str | None = None,
) -> dict:
    """Create a Customer + optional primary Address.

    Idempotent via `client_id` (optional) — when the offline queue
    replays a create, the server returns the previously-persisted
    Customer instead of creating a duplicate. The lookup uses Vansale
    Outbox (event_type="customer"), matching the invoice/payment/
    sales_return pattern.

    B2B (customer_type="b2b") requires address_line1 + city and, for KSA
    ZATCA Phase 2 compliance, a **building number** (4-digit) on the
    primary address (per PDF §2b + KSA E-Invoicing requirements).
    B2C (customer_type="b2c") default — Individual, address optional.

    `building_number`, `additional_number`, `district` are persisted to
    the custom fields added by the `ksa_compliance` app. When the app
    isn't installed these fields are silently dropped by Frappe (unknown
    fieldnames on `Address` are ignored), so the API stays portable.
    """
    if not customer_name:
        frappe.throw(_("Customer name required"))

    # Idempotent replay — return the earlier Customer if the same
    # client_id already drained. Clients on the offline queue retry
    # after network loss; without this guard we'd create duplicates.
    if client_id:
        prior = claim(client_id, "customer", "Customer")
        if prior:
            doc = frappe.get_doc("Customer", prior)
            return {
                "name": doc.name,
                "customer_name": doc.customer_name,
                "customer_type": doc.customer_type,
                "address": doc.customer_primary_address,
                "idempotent_replay": True,
            }
    ctype = (customer_type or "b2c").lower()
    is_b2b = ctype == "b2b"

    # Resolve country once — used for both Customer.custom_country (a
    # site-custom reqd Link field added on trading-demo) and the primary
    # Address. Default to KSA when the caller doesn't pick one; fall back
    # to Global Defaults before that so sites with a different home
    # country keep working.
    resolved_country = (
        country
        or frappe.db.get_single_value("Global Defaults", "country")
        or "Saudi Arabia"
    )

    if resolved_country == _KSA:
        _validate_ksa(resolved_country, is_b2b, tax_id, building_number, pincode, district, address_line1, city)
    elif is_b2b:
        missing = [label for label, value in ((_("Address line 1"), address_line1), (_("City"), city)) if not value]
        if missing:
            frappe.throw(
                _("The following fields are mandatory for B2B customers: {0}").format(", ".join(missing))
            )
    if address_line1:
        # Address fields this site makes mandatory (e.g. pincode), checked
        # before anything is created so the driver gets a clear message.
        address_meta = frappe.get_meta("Address")
        given = {"city": city, "state": state, "pincode": pincode}
        missing = [
            _(address_meta.get_label(f)) for f, v in given.items()
            if not v and address_meta.get_field(f) and address_meta.get_field(f).reqd
        ]
        if missing:
            frappe.throw(_("Please fill in the address: {0}").format(", ".join(missing)))

    customer_payload: dict = {
        "doctype": "Customer",
        "customer_name": customer_name,
        "customer_type": "Company" if is_b2b else "Individual",
        "mobile_no": mobile_no,
        "email_id": email_id,
        "territory": territory or _default_leaf("Territory", "default_territory", "territory"),
        "customer_group": customer_group
        or _default_leaf("Customer Group", "default_customer_group", "customer_group"),
        "tax_id": tax_id,
    }
    # Only set `custom_country` if the field actually exists on Customer
    # for this site (ksa_compliance / customer-specific customization).
    # Keeping the API portable to sites without the custom field.
    customer_meta = frappe.get_meta("Customer")
    if customer_meta.has_field("custom_country"):
        customer_payload["custom_country"] = resolved_country
    # Optional fields, written only where the site has them (ksa_compliance
    # ZATCA fields, a second-language name).
    vat_field = _vat_field()
    if vat_field and tax_id:
        customer_payload[vat_field] = tax_id
    if cr_number and customer_meta.has_field("custom_cr_number"):
        customer_payload["custom_cr_number"] = cr_number
    name_2_field = customer_name_2_field()
    if name_2_field and customer_name_2:
        customer_payload[name_2_field] = customer_name_2
    doc = frappe.get_doc(customer_payload)
    # Auto-stamp the creating van user's sales_person into Sales Team so
    # the customer shows up in list_mine() without a manual admin tag +
    # so invoice commission tracking works from the first invoice. Sites
    # that link customers by Customer.custom_sales_person get that too.
    sp = current_user_sales_person()
    if sp:
        doc.append("sales_team", {"sales_person": sp, "allocated_percentage": 100})
        if customer_meta.has_field("custom_sales_person"):
            doc.custom_sales_person = sp
    doc.insert(ignore_permissions=False)

    # Create Address if fields provided (mandatory for B2B, optional for B2C).
    address_name: str | None = None
    if address_line1:
        addr_data = {
            "doctype": "Address",
            "address_title": customer_name,
            "address_type": "Billing",
            "address_line1": address_line1,
            "address_line2": address_line2,
            "city": city,
            "state": state,
            "pincode": pincode,
            "country": resolved_country,
            "phone": mobile_no,
            "email_id": email_id,
            "is_primary_address": 1,
            "is_shipping_address": 1,
            "links": [{"link_doctype": "Customer", "link_name": doc.name}],
        }
        for key, value in (
            ("building_number", building_number),
            ("additional_number", additional_number),
            ("district", district),
        ):
            field = _address_field(key)
            if value and field:
                addr_data[field] = str(value).strip()
        addr = frappe.get_doc(addr_data)
        addr.insert(ignore_permissions=False)
        address_name = addr.name
        # Link back to customer as primary address.
        frappe.db.set_value("Customer", doc.name, "customer_primary_address", address_name)

    # Outbox row in the same transaction as the Customer (claimed above), so
    # a retry can never create a second customer and a rollback drops both.
    if client_id:
        _record_customer_outbox(
            client_id,
            doc.name,
            posting_ts,
            {
                "customer_name": customer_name,
                "customer_type": ctype,
                "address": address_name,
                "mobile_no": mobile_no,
            },
        )
    frappe.db.commit()

    return {
        "name": doc.name,
        "customer_name": doc.customer_name,
        "customer_type": doc.customer_type,
        "address": address_name,
    }


def _build_statement_html(name: str, from_date: str | None, to_date: str | None) -> str:
    """Shared statement-HTML builder for both the download and JSON endpoints.

    The JSON variant is what the Capacitor APK uses — `frappe.response.type="download"`
    returns raw HTML bytes that our `apiCall` helper can't parse through `res.json()`.
    Keeping a single source of truth avoids the layouts drifting apart.
    """
    if not name:
        frappe.throw(_("Customer name required"))
    check_read("Customer", name)
    cust = frappe.get_doc("Customer", name)

    to_date = to_date or str(frappe.utils.today())
    from_date = from_date or frappe.utils.add_days(to_date, -90)

    # Built from GL Entry, the ledger the books use, so opening and closing
    # match Accounts Receivable. Listing Sales Invoices as debits and Payment
    # Entries as credits showed every cash (POS) sale as unpaid, since its
    # payment sits inside the invoice, and left out Journal Entries.
    from vansale.api.invoice import _user_company

    company = _user_company() or ""
    opening = frappe.db.sql(
        """
        SELECT COALESCE(SUM(debit - credit), 0) AS bal
        FROM `tabGL Entry`
        WHERE party_type = 'Customer' AND party = %s AND company = %s
          AND posting_date < %s AND is_cancelled = 0
        """,
        (name, company, from_date),
        as_dict=True,
    )
    opening_balance = float(opening[0]["bal"]) if opening else 0.0

    entries = frappe.db.sql(
        """
        SELECT posting_date, voucher_type, voucher_no,
               SUM(debit) AS debit, SUM(credit) AS credit, MIN(creation) AS created
        FROM `tabGL Entry`
        WHERE party_type = 'Customer' AND party = %s AND company = %s
          AND posting_date BETWEEN %s AND %s AND is_cancelled = 0
        GROUP BY posting_date, voucher_type, voucher_no
        ORDER BY posting_date ASC, created ASC
        """,
        (name, company, from_date, to_date),
        as_dict=True,
    )
    modes = dict(
        frappe.get_all(
            "Payment Entry",
            filters={"name": ["in", [e.voucher_no for e in entries if e.voucher_type == "Payment Entry"] or [""]]},
            fields=["name", "mode_of_payment"],
            as_list=True,
        )
    )
    returns = set(
        frappe.get_all(
            "Sales Invoice",
            filters={"name": ["in", [e.voucher_no for e in entries if e.voucher_type == "Sales Invoice"] or [""]], "is_return": 1},
            pluck="name",
        )
    )

    rows: list[dict] = []
    for e in entries:
        if e.voucher_type == "Payment Entry":
            desc = f"Payment — {modes.get(e.voucher_no) or ''}".strip(" —")
        elif e.voucher_no in returns:
            desc = "Credit Note"
        else:
            desc = e.voucher_type
        rows.append({
            "date": e.posting_date,
            "ref": e.voucher_no,
            "desc": desc,
            "debit": float(e.debit or 0),
            "credit": float(e.credit or 0),
        })

    # Running balance.
    running = opening_balance
    for r in rows:
        running = running + r["debit"] - r["credit"]
        r["balance"] = running
    closing = running

    currency = frappe.db.get_value("Company", company, "default_currency") or cust.default_currency or ""
    esc = frappe.utils.escape_html

    def fmt(x: float) -> str:
        return f"{x:,.2f}"

    inv_rows_html = "".join(
        f"<tr><td>{r['date']}</td><td>{esc(r['ref'])}</td><td>{esc(r['desc'])}</td>"
        f"<td style='text-align:right'>{fmt(r['debit']) if r['debit'] else ''}</td>"
        f"<td style='text-align:right'>{fmt(r['credit']) if r['credit'] else ''}</td>"
        f"<td style='text-align:right'>{fmt(r['balance'])}</td></tr>"
        for r in rows
    )
    if not rows:
        inv_rows_html = "<tr><td colspan='6' style='text-align:center;color:#888;padding:1rem'>No transactions in this period.</td></tr>"

    html = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Statement — {esc(cust.customer_name)}</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif; padding: 2rem; color: #111; }}
  h1 {{ font-size: 1.3rem; margin: 0 0 0.2rem; }}
  .meta {{ color: #555; font-size: 0.9rem; margin-bottom: 1rem; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.9rem; }}
  th, td {{ padding: 0.4rem 0.5rem; border-bottom: 1px solid #ddd; }}
  th {{ background: #f5f5f5; text-align: left; }}
  tfoot td {{ font-weight: 700; border-top: 2px solid #111; border-bottom: none; }}
  .opening {{ color: #555; font-style: italic; }}
  @media print {{ body {{ padding: 1rem; }} .no-print {{ display: none; }} }}
  .no-print {{ text-align: right; margin-bottom: 1rem; }}
  .no-print button {{ padding: 0.4rem 0.9rem; border-radius: 6px; border: 1px solid #2563eb; background: #2563eb; color: white; cursor: pointer; }}
</style></head>
<body>
  <div class="no-print"><button onclick="window.print()">Print</button></div>
  <h1>{esc(cust.customer_name)} — Statement</h1>
  <div class="meta">
    Period: <strong>{from_date}</strong> to <strong>{to_date}</strong><br/>
    Company: {esc(company)} · Currency: {esc(currency)}<br/>
    {f'Tax ID: {esc(cust.tax_id)}<br/>' if cust.tax_id else ''}
    {f'Mobile: {esc(cust.mobile_no)}<br/>' if cust.mobile_no else ''}
  </div>
  <table>
    <thead>
      <tr><th>Date</th><th>Reference</th><th>Description</th>
          <th style="text-align:right">Debit</th>
          <th style="text-align:right">Credit</th>
          <th style="text-align:right">Balance</th></tr>
    </thead>
    <tbody>
      <tr class="opening"><td colspan="5">Opening balance</td>
          <td style="text-align:right">{fmt(opening_balance)}</td></tr>
      {inv_rows_html}
    </tbody>
    <tfoot>
      <tr><td colspan="5" style="text-align:right">Closing balance</td>
          <td style="text-align:right">{fmt(closing)}</td></tr>
    </tfoot>
  </table>
</body></html>"""

    return html


@frappe.whitelist(methods=["GET"])
def statement_html(name: str, from_date: str | None = None, to_date: str | None = None):
    """Render a printable customer statement as HTML (direct-download variant).

    Used by the web PWA's `window.open` fallback. The JSON variant below is
    preferred on the APK — WebView intercepts relative URLs under the
    capacitor:// scheme so we can't rely on a naive `<a href>` / `window.open`.
    """
    html = _build_statement_html(name, from_date, to_date)
    frappe.local.response.type = "download"
    frappe.local.response.filename = f"statement-{name}.html"
    frappe.local.response.filecontent = html.encode("utf-8")
    frappe.local.response.content_type = "text/html"
    frappe.local.response.display_content_as = "inline"


@frappe.whitelist(methods=["GET"])
def statement_json(
    name: str,
    from_date: str | None = None,
    to_date: str | None = None,
) -> dict:
    """JSON-wrapped statement HTML for the Capacitor APK.

    Returning through Frappe's normal `{message: ...}` envelope means
    `apiCall<StatementPayload>` can deserialize + v-html render it
    inside the in-app StatementView (no `window.open` round-trip, which
    fails on native because the WebView runs at `https://localhost`).
    """
    html = _build_statement_html(name, from_date, to_date)
    return {"html": html}


@frappe.whitelist(methods=["GET"])
def statement_pdf(name: str, from_date: str | None = None, to_date: str | None = None):
    """Render the customer statement as a PDF binary.

    Used by the APK — the WebView cannot reliably open the system print
    dialog from inside a sandboxed iframe, so we hand it PDF bytes that
    `saveBlobToDevice` writes to `Documents/` via the Filesystem plugin.
    """
    from frappe.utils.pdf import get_pdf

    html = _build_statement_html(name, from_date, to_date)
    pdf_bytes = get_pdf(html)
    frappe.local.response.type = "download"
    frappe.local.response.filename = f"statement-{name}.pdf"
    frappe.local.response.filecontent = pdf_bytes
    frappe.local.response.content_type = "application/pdf"
    frappe.local.response.display_content_as = "attachment"


@frappe.whitelist(methods=["GET"])
def summary(customer: str) -> dict:
    """Aggregates for the customer detail tile strip."""
    check_read("Customer", customer)
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
