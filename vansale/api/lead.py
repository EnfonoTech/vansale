"""Lead endpoints — the start of the sales cycle.

A van salesman captures a prospect in the field (`save`) and quotes it
(`quotation.save` with `quotation_to="Lead"`). The lead becomes a Customer
when its quotation is ordered (`quotation.make_order`), or earlier by hand
(`convert`) when the salesman wants to invoice it straight away.
"""

from __future__ import annotations

from typing import Optional

import frappe
from frappe import _
from frappe.utils import cint

from vansale.api.access import readable_doc
from vansale.api.datetime_util import naive_site_to_utc_iso
from vansale.api.outbox import claim
from vansale.api.selling import record_outbox, search_filters, stamp

# What the app lets a salesman set himself. Converted / Quotation are set by
# ERPNext as the cycle moves on; Opportunity is not part of the van flow.
OPEN_STATUSES = ("Lead", "Open", "Replied", "Interested", "Do Not Contact", "Lost Quotation")

_LIST_FIELDS = [
    "name", "lead_name", "company_name", "mobile_no", "email_id",
    "status", "source", "territory", "customer", "creation", "modified",
]


def _apply(doc, f: dict) -> None:
    """Copy the editable fields the client sent onto the Lead."""
    for key in ("company_name", "mobile_no", "email_id", "source", "territory", "city"):
        if key in f and f[key] is not None:
            doc.set(key, (f[key] or "").strip() or None)
    if f.get("lead_name"):
        # Lead.lead_name is derived from first/middle/last on validate; the
        # app has one name box, so it goes in first_name and the rest is cleared.
        doc.first_name = f["lead_name"].strip()
        doc.middle_name = None
        doc.last_name = None
    # A status ERPNext set itself (Quotation, Opportunity) comes back unchanged
    # from the form: that is no change, not a refusal (editing such a lead
    # always failed). Only moving it to a status the app may not set is refused.
    if f.get("status") and f["status"] != doc.status:
        if f["status"] not in OPEN_STATUSES:
            frappe.throw(_("Status {0} cannot be set from the app").format(f["status"]))
        doc.status = f["status"]


def _add_note(doc, note: Optional[str]) -> None:
    note = (note or "").strip()
    if note:
        doc.append("notes", {"note": note, "added_by": frappe.session.user, "added_on": frappe.utils.now_datetime()})


@frappe.whitelist(methods=["POST"])
def save(
    client_id: str,
    lead_name: Optional[str] = None,
    company_name: Optional[str] = None,
    mobile_no: Optional[str] = None,
    email_id: Optional[str] = None,
    source: Optional[str] = None,
    territory: Optional[str] = None,
    city: Optional[str] = None,
    note: Optional[str] = None,
    posting_ts: Optional[str] = None,
) -> dict:
    if not client_id:
        frappe.throw(_("client_id is required"))
    if not (lead_name or "").strip() and not (company_name or "").strip():
        frappe.throw(_("Enter the person's name or the company name"))

    existing = claim(client_id, "lead", "Lead")
    if existing:
        return {"name": existing, "idempotent_replay": True}

    doc = frappe.new_doc("Lead")
    doc.lead_owner = frappe.session.user
    doc.status = "Lead"
    _apply(doc, {
        "lead_name": lead_name, "company_name": company_name, "mobile_no": mobile_no,
        "email_id": email_id, "source": source, "territory": territory, "city": city,
    })
    _add_note(doc, note)
    doc.insert()

    record_outbox(client_id, "lead", "Lead", doc.name, posting_ts, {"lead_name": doc.lead_name})
    frappe.db.commit()
    return {"name": doc.name, "lead_name": doc.lead_name, "status": doc.status, "idempotent_replay": False}


@frappe.whitelist(methods=["POST"])
def update(
    name: str,
    lead_name: Optional[str] = None,
    company_name: Optional[str] = None,
    mobile_no: Optional[str] = None,
    email_id: Optional[str] = None,
    source: Optional[str] = None,
    territory: Optional[str] = None,
    city: Optional[str] = None,
    status: Optional[str] = None,
    note: Optional[str] = None,
) -> dict:
    doc = readable_doc("Lead", name)
    if doc.status == "Converted":
        frappe.throw(_("This lead is already a customer — edit the customer instead"))
    _apply(doc, {
        "lead_name": lead_name, "company_name": company_name, "mobile_no": mobile_no,
        "email_id": email_id, "source": source, "territory": territory, "city": city, "status": status,
    })
    _add_note(doc, note)
    doc.flags.ignore_version = True
    doc.save()
    frappe.db.commit()
    return {"name": doc.name, "status": doc.status, "modified": stamp(doc)}


@frappe.whitelist(methods=["GET"])
def list_mine(limit: int = 50, search: Optional[str] = None, status: Optional[str] = None) -> list[dict]:
    filters: dict = {"owner": frappe.session.user}
    if status:
        filters["status"] = status
    rows = frappe.get_all(
        "Lead",
        filters=filters,
        or_filters=search_filters(search, ("lead_name", "company_name", "mobile_no", "email_id")),
        fields=_LIST_FIELDS,
        order_by="modified desc",
        limit=cint(limit) or 50,
    )
    for r in rows:
        r["modified"] = naive_site_to_utc_iso(r.get("modified"))
        r["creation"] = naive_site_to_utc_iso(r.get("creation"))
    return rows


@frappe.whitelist(methods=["GET"])
def detail(name: str) -> dict:
    doc = readable_doc("Lead", name)
    quotations = frappe.get_all(
        "Quotation",
        filters={"quotation_to": "Lead", "party_name": doc.name, "docstatus": ["<", 2]},
        fields=["name", "status", "grand_total", "transaction_date", "docstatus"],
        order_by="creation desc",
    )
    return {
        "name": doc.name,
        "lead_name": doc.lead_name,
        "company_name": doc.company_name,
        "mobile_no": doc.mobile_no,
        "email_id": doc.email_id,
        "source": doc.source,
        "territory": doc.territory,
        "city": doc.city,
        "status": doc.status,
        "customer": linked_customer(doc),
        "notes": [
            {"note": n.note, "added_by": n.added_by, "added_on": str(n.added_on) if n.added_on else None}
            for n in (doc.get("notes") or [])
        ],
        "quotations": quotations,
        "modified": stamp(doc),
    }


@frappe.whitelist(methods=["GET"])
def options() -> dict:
    """Pick lists for the lead form."""
    return {
        "sources": frappe.get_all("Lead Source", pluck="name", order_by="name"),
        "territories": frappe.get_all("Territory", filters={"is_group": 0}, pluck="name", order_by="name"),
        "statuses": list(OPEN_STATUSES),
    }


def linked_customer(lead) -> Optional[str]:
    """The Customer made from this lead. ERPNext records the link on the
    Customer (`lead_name`), not always on the Lead's own `customer` field."""
    return lead.customer or frappe.db.get_value("Customer", {"lead_name": lead.name}, "name")


def ensure_customer(lead) -> tuple[str, bool]:
    """The lead's Customer, creating it (ERPNext `make_customer`) if it has none.

    The Customer `before_insert` hook assigns it to the salesman, so it shows
    up in his customer list at once. ERPNext marks the lead Converted when the
    Customer is saved. Returns (customer name, created now?).
    """
    existing = linked_customer(lead)
    if existing:
        return existing, False

    from erpnext.crm.doctype.lead.lead import make_customer

    from vansale.api.customer import _default_leaf

    customer = make_customer(lead.name)
    # ERPNext fills group / territory from Selling Settings, which may be empty
    # or a group node ("Cannot select a Group type Customer Group"). Use the
    # same defaults as a customer created in the app: the van's, else Selling
    # Settings, never a group.
    for field, doctype, van_field in (
        ("customer_group", "Customer Group", "default_customer_group"),
        ("territory", "Territory", "default_territory"),
    ):
        value = customer.get(field)
        if not value or frappe.db.get_value(doctype, value, "is_group"):
            customer.set(field, _default_leaf(doctype, van_field, field))
    from vansale import steelforce

    # Steel Force: the same rules as a customer made in the app (mobile, no
    # second customer of the same name). Not the B2B Creator rule: a lead
    # carries no VAT number, so it never becomes a B2B customer there.
    steelforce.check_new_customer(
        customer.customer_name, False, customer.get("mobile_no") or lead.get("mobile_no") or lead.get("phone")
    )
    steelforce.on_new_customer(customer)
    customer.insert()
    return customer.name, True


@frappe.whitelist(methods=["POST"])
def convert(client_id: str, name: str) -> dict:
    """Turn the lead into a Customer."""
    if not client_id:
        frappe.throw(_("client_id is required"))
    lead = readable_doc("Lead", name)
    if linked_customer(lead):
        return {"customer": linked_customer(lead), "idempotent_replay": True}

    existing = claim(client_id, "lead", "Customer")
    if existing:
        return {"customer": existing, "idempotent_replay": True}

    customer, _created = ensure_customer(lead)
    record_outbox(client_id, "lead", "Customer", customer, None, {"converted_lead": lead.name})
    frappe.db.commit()
    return {"customer": customer, "customer_name": frappe.db.get_value("Customer", customer, "customer_name"), "idempotent_replay": False}
