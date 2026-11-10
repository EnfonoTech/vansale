# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Header details printed on a Customer Statement of Account.

The statement layout carries a customer block (name, IDs, address, terms,
credit limit) and Steel Force's letterhead artwork. None of that comes out of
the ledger, so the report's client script pulls it from here into hidden
filters, which the print template then reads.
"""

import re

import frappe
from frappe import _
from frappe.contacts.doctype.address.address import get_address_display, get_default_address
from frappe.utils import cstr

from erpnext.selling.doctype.customer.customer import get_credit_limit

IMG_SRC = re.compile(r"""<img[^>]+src=["']([^"']+)["']""", re.IGNORECASE)


@frappe.whitelist()
def get_statement_header(customer, company):
    """Return the statement header as hidden-filter values.

    Keys match the hidden filters declared in customer_statement_of_account.js;
    the print template reads them off `filters`.
    """
    frappe.has_permission("Customer", "read", doc=customer, throw=True)

    doc = frappe.get_cached_doc("Customer", customer)
    header_image, footer_image = get_letter_head_images(company)

    return {
        "soa_customer_name": doc.customer_name or doc.name,
        "soa_customer_name_ar": doc.get("customer_name_in_arabic")
        or doc.get("custom_customer_name_arabic")
        or "",
        "soa_customer_id": doc.name,
        "soa_address": get_customer_address(customer),
        "soa_vat_no": doc.tax_id or doc.get("custom_vat_registration_number") or "",
        "soa_cr_no": doc.get("custom_commercial_registration_number") or "",
        "soa_payment_terms": doc.payment_terms or "",
        "soa_credit_limit": get_credit_limit(customer, company) or 0,
        "soa_collector": get_collector(customer),
        "soa_company_name": company,
        "soa_header_image": header_image,
        "soa_footer_image": footer_image,
    }


def get_customer_address(customer):
    """Primary address as one line, mirroring what ERPNext prints elsewhere."""
    address = get_default_address("Customer", customer)
    if not address:
        return ""

    display = get_address_display(frappe.get_cached_doc("Address", address).as_dict()) or ""
    return cstr(display).replace("<br>", ", ").strip(", ")


def get_collector(customer):
    """The sales person on the customer — the statement prints them as collector."""
    return (
        frappe.db.get_value(
            "Sales Team",
            {"parent": customer, "parenttype": "Customer"},
            "sales_person",
            order_by="allocated_percentage desc",
        )
        or ""
    )


def get_letter_head_images(company, letter_head=None):
    """Header and footer artwork from the company's letter head, if it has any.

    Steel Force's letter head is a pair of images rather than markup, so the
    statement reuses them instead of rebuilding the branding in the template.

    `letter_head` names one explicitly; without it the site default is used.
    """
    row = None
    if letter_head:
        row = frappe.db.get_value(
            "Letter Head", letter_head, ["content", "footer"], as_dict=True
        )
    if not row:
        row = frappe.db.get_value(
            "Letter Head", {"disabled": 0, "is_default": 1}, ["content", "footer"], as_dict=True
        )
    if not row:
        return "", ""

    return first_image(row.content), first_image(row.footer)


@frappe.whitelist()
def get_letter_head_artwork(letter_head: str | None = None, company: str | None = None):
    """The two images a statement needs when no letter head was picked in the print dialog.

    The print wrapper draws the letter head only when With Letter head is ticked, and the
    footer band only when Repeat Header and Footer is ticked as well, so a statement
    exported with the dialog left alone had no artwork at either end. The print format
    calls this and draws both ends itself.

    Returns nothing but branding artwork already published under /files, so it is readable
    by any signed-in user - the same artwork every printed document carries.
    """
    header_image, footer_image = get_letter_head_images(company, letter_head=letter_head)
    return {"header_image": header_image, "footer_image": footer_image}


def first_image(html):
    """First <img> source, made absolute.

    wkhtmltopdf renders the header and footer as documents of their own, with
    no site as their base, so a site-relative src would silently come out blank.
    """
    match = IMG_SRC.search(cstr(html))
    if not match:
        return ""

    src = match.group(1)
    return frappe.utils.get_url(src) if src.startswith("/") else src


# ---------------------------------------------------------------------------
# ePromise voucher numbers
# ---------------------------------------------------------------------------

# Every doctype the migration stamped with the number the voucher carried in
# ePromise. The field holds "<source>|<number>", e.g. R01|501000375, and staff
# know these documents by the number after the pipe rather than by the name
# ERPNext generated for them on import.
EPROMISE_VR_DOCTYPES = (
    "Sales Invoice",
    "Purchase Invoice",
    "Purchase Receipt",
    "Payment Entry",
    "Journal Entry",
    "Stock Entry",
)

EPROMISE_VR_FIELD = "epromise_vr"


def epromise_number(value) -> str:
    """The number a user recognises out of an ePromise VR.

    "R01|501000375" -> "501000375". The last segment is taken rather than the
    second, so an unexpected extra separator still yields the number and not a
    fragment of the prefix. A value with no separator is returned as it stands.
    """
    text = cstr(value).strip()
    if not text:
        return ""

    return text.rsplit("|", 1)[-1].strip()


@frappe.whitelist()
def get_epromise_references(vouchers):
    """Map printed vouchers to their ePromise number, in one round trip.

    `vouchers` is a JSON list of {"voucher_type", "voucher_no"}. The reply is
    keyed "<voucher_type>::<voucher_no>" so two doctypes sharing a name cannot
    collide, and only carries entries that actually have a number — anything
    missing keeps the name the caller already has.

    Reads are grouped per doctype and skip any doctype the caller may not read,
    so this exposes nothing the report itself would not already show.
    """
    if isinstance(vouchers, str):
        vouchers = frappe.parse_json(vouchers)

    wanted = {}
    for row in vouchers or []:
        voucher_type = cstr((row or {}).get("voucher_type"))
        voucher_no = cstr((row or {}).get("voucher_no"))
        if voucher_type in EPROMISE_VR_DOCTYPES and voucher_no:
            wanted.setdefault(voucher_type, set()).add(voucher_no)

    references = {}
    for voucher_type, names in wanted.items():
        if not frappe.has_permission(voucher_type, "read"):
            continue

        meta = frappe.get_meta(voucher_type)
        if not meta.has_field(EPROMISE_VR_FIELD):
            continue

        for record in frappe.get_all(
            voucher_type,
            filters={"name": ("in", list(names))},
            fields=["name", EPROMISE_VR_FIELD],
        ):
            number = epromise_number(record.get(EPROMISE_VR_FIELD))
            if number:
                references[f"{voucher_type}::{record.name}"] = number

    return references
