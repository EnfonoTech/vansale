import re

import frappe
from frappe import _
from frappe.utils import cint

VAT_OVERRIDE_ROLES = {"Sales Manager", "Sales Master Manager", "System Manager"}


def _can_override_vat_duplicate():
    user = frappe.session.user
    if user == "Administrator":
        return True
    return bool(set(frappe.get_roles(user)) & VAT_OVERRIDE_ROLES)


def _get_default_customer_group():
    cg = frappe.db.get_single_value("Selling Settings", "customer_group")
    if cg and not cint(frappe.db.get_value("Customer Group", cg, "is_group")):
        return cg
    leaf = frappe.get_all(
        "Customer Group", filters={"is_group": 0}, pluck="name", limit=1, order_by="name asc"
    )
    return (leaf[0] if leaf else None) or "All Customer Groups"


def _get_default_territory():
    return (
        frappe.db.get_single_value("Selling Settings", "territory") or "All Territories"
    )


@frappe.whitelist()
def create_customer_with_address(
    customer_name,
    mobile_no=None,
    buyer_kind=None,
    email_id=None,
    company=None,
    country=None,
    default_currency=None,
    tax_id=None,
    commercial_registration_number=None,
    address_type=None,
    address_line1=None,
    address_line2=None,
    custom_building_number=None,
    city=None,
    state=None,
    pincode=None,
    district=None,
    allow_duplicate_vat=0,
    duplicate_vat_reason=None,
    attachment=None,
):
    if not customer_name:
        frappe.throw(_("Customer Name is required"))
    if not mobile_no:
        frappe.throw(_("Mobile No is required"))

    allow_duplicate_vat = int(allow_duplicate_vat or 0)
    is_b2b = (buyer_kind or "").startswith("B2B")

    # Resolve company and country
    if not company:
        company = frappe.defaults.get_user_default("company")
    company_country = (
        frappe.db.get_value("Company", company, "country") if company else ""
    ) or ""
    is_saudi = company_country.strip().lower() == "saudi arabia"

    if is_saudi and len(re.sub(r"\D", "", str(mobile_no))) < 10:
        frappe.throw(_("Mobile number must have at least 10 digits."))

    if not country:
        country = company_country
    if not default_currency and company:
        default_currency = frappe.db.get_value("Company", company, "default_currency")

    # B2B validations
    if is_b2b:
        vat = (tax_id or "").strip()
        if not vat:
            frappe.throw(_("VAT Registration Number is required for B2B customers."))
        if is_saudi:
            if not re.match(r"^3\d{13}3$", vat):
                frappe.throw(
                    _("VAT Registration Number must be exactly 15 digits, starting and ending with 3.")
                )
            for label, value in (
                (_("Address Line 1"), address_line1),
                (_("Building Number"), custom_building_number),
                (_("District / Area"), district),
                (_("City"), city),
                (_("Postal Code"), pincode),
            ):
                if not value:
                    frappe.throw(
                        _("{0} is required for B2B customers in Saudi Arabia.").format(label)
                    )
            if pincode and len(re.sub(r"\D", "", str(pincode))) != 5:
                frappe.throw(_("Postal Code must be exactly 5 digits."))

    # VAT duplicate check
    if tax_id:
        vat = str(tax_id).strip()
        if allow_duplicate_vat:
            if not _can_override_vat_duplicate():
                frappe.throw(
                    _("You do not have permission to override the VAT duplicate check.")
                )
            if not (duplicate_vat_reason and duplicate_vat_reason.strip()):
                frappe.throw(_("Duplicate VAT Reason is required when overriding."))
        else:
            clash = frappe.db.exists(
                "Customer", {"custom_vat_registration_number": vat}
            )
            if clash:
                frappe.throw(
                    _("VAT already used by Customer: {0}.").format(clash)
                )

    # Duplicate name check
    if frappe.db.exists("Customer", {"customer_name": customer_name}):
        frappe.throw(_("Customer '{0}' already exists.").format(customer_name))

    customer_type = "Company" if is_b2b else "Individual"
    customer = frappe.get_doc({
        "doctype": "Customer",
        "customer_name": customer_name,
        "customer_type": customer_type,
        "customer_group": _get_default_customer_group(),
        "territory": _get_default_territory(),
        "default_currency": default_currency,
        "tax_id": tax_id or None,
        "mobile_no": mobile_no,
        "email_id": email_id or None,
        "custom_company": company or None,
        "custom_vat_registration_number": tax_id or None,
        "custom_commercial_registration_number": commercial_registration_number or None,
    })
    customer.insert(ignore_permissions=True)

    # Link attachment immediately after insert so customer_override.validate finds
    # it on the subsequent customer.save() (primary address set) and doesn't throw.
    if attachment:
        file_rec = frappe.db.get_value("File", {"file_url": attachment}, "name")
        if file_rec:
            frappe.db.set_value("File", file_rec, {
                "attached_to_doctype": "Customer",
                "attached_to_name": customer.name,
            })

    address_name = None
    if any([address_line1, city]):
        address = frappe.get_doc({
            "doctype": "Address",
            "address_title": customer_name,
            "address_type": address_type or "Billing",
            "address_line1": address_line1 or "",
            "address_line2": address_line2 or "",
            "city": city or "",
            "state": state or "",
            "pincode": pincode or "",
            "country": country or "",
            "is_primary_address": 1,
            "is_shipping_address": 1,
        })
        if custom_building_number and frappe.db.has_column("Address", "custom_building_number"):
            address.custom_building_number = custom_building_number
        if district and frappe.db.has_column("Address", "custom_area"):
            address.custom_area = district

        address.append("links", {
            "link_doctype": "Customer",
            "link_name": customer.name,
            "link_title": customer.customer_name,
        })
        address.insert(ignore_permissions=True)
        address_name = address.name

        customer.customer_primary_address = address_name
        customer.save(ignore_permissions=True)

    return {
        "customer": customer.name,
        "address": address_name,
        "message": _("Customer {0} created successfully.").format(customer.name),
    }
