"""Sales Invoice endpoints.

`save` is idempotent by `client_id` — if the client already queued an
invoice with this UUID and we succeed later, re-submitting the same
`client_id` returns the already-saved doc rather than creating a duplicate.
That's the contract the Phase 2 drain engine relies on.
"""

from __future__ import annotations

from typing import Any, Optional

import frappe
from frappe import _
from frappe.utils import cint, flt

from vansale.api.datetime_util import naive_site_to_utc_iso, parse_client_ts
from vansale.api.me import current_user_sales_person


def _user_default(allow: str) -> Optional[str]:
    return frappe.db.get_value(
        "User Permission",
        {"user": frappe.session.user, "allow": allow, "is_default": 1},
        "for_value",
    )


def _get_default_warehouse(company: str) -> Optional[str]:
    """Prefer the Van User's configured warehouse; fall back to company / stock default."""
    return (
        _user_default("Warehouse")
        or frappe.db.get_value("Company", company, "default_warehouse")
        or frappe.db.get_single_value("Stock Settings", "default_warehouse")
    )


def _user_company() -> str:
    return (
        _user_default("Company")
        or frappe.defaults.get_user_default("Company", frappe.session.user)
        or frappe.db.get_single_value("Global Defaults", "default_company")
    )


def _default_tax_template(company: str) -> Optional[str]:
    """Resolve the Company's default Sales Taxes and Charges Template.

    Some sites enforce taxes_and_charges as mandatory (either directly
    or via customisations like fateh_trading on this bench). Rather
    than surface a cryptic error to the van user we auto-pick the
    company's default.
    """
    return frappe.db.get_value(
        "Sales Taxes and Charges Template",
        {"company": company, "is_default": 1, "disabled": 0},
        "name",
    ) or frappe.db.get_value(
        "Sales Taxes and Charges Template",
        {"company": company, "disabled": 0},
        "name",
        order_by="modified desc",
    )


def _existing_by_client_id(client_id: str) -> Optional[str]:
    """Look up a prior submission of the same idempotency key."""
    if not client_id:
        return None
    name = frappe.db.get_value("Vansale Outbox", {"client_id": client_id}, "ref_name")
    if name and frappe.db.exists("Sales Invoice", name):
        return name
    return None


def _record_outbox(client_id: str, ref_name: str, posting_ts: Optional[str], payload: dict) -> None:
    if not client_id:
        return
    if frappe.db.exists("Vansale Outbox", client_id):
        doc = frappe.get_doc("Vansale Outbox", client_id)
    else:
        doc = frappe.new_doc("Vansale Outbox")
        doc.client_id = client_id
    doc.event_type = "invoice"
    doc.user = frappe.session.user
    doc.client_ts = parse_client_ts(posting_ts) if posting_ts else None
    doc.drained_at = frappe.utils.now_datetime()
    doc.status = "processed"
    doc.ref_doctype = "Sales Invoice"
    doc.ref_name = ref_name
    doc.payload_json = frappe.as_json(payload)
    doc.save(ignore_permissions=True)


@frappe.whitelist(methods=["POST"])
def save(
    client_id: str,
    customer: str,
    items: list[dict[str, Any]],
    posting_ts: Optional[str] = None,
    warehouse: Optional[str] = None,
    remarks: Optional[str] = None,
    update_stock: int = 1,
    submit: int = 1,
    payment_type: Optional[str] = None,       # "cash" | "credit" — drives is_pos + payments
    mode_of_payment: Optional[str] = None,    # used when payment_type == "cash"
    discount_amount: Optional[float] = None,  # invoice-level additional discount
    apply_discount_on: Optional[str] = None,  # "Grand Total" | "Net Total"
) -> dict:
    if not client_id:
        frappe.throw(_("client_id is required"))
    if not customer:
        frappe.throw(_("Customer is required"))
    if not items:
        frappe.throw(_("At least one item is required"))

    existing = _existing_by_client_id(client_id)
    if existing:
        doc = frappe.get_doc("Sales Invoice", existing)
        return {
            "name": doc.name,
            "grand_total": float(doc.grand_total or 0),
            "status": doc.status,
            "modified": naive_site_to_utc_iso(doc.modified),
            "idempotent_replay": True,
        }

    company = _user_company()
    set_warehouse = warehouse or _get_default_warehouse(company)

    posting = parse_client_ts(posting_ts) if posting_ts else frappe.utils.now_datetime()

    doc = frappe.new_doc("Sales Invoice")
    doc.customer = customer
    doc.company = company
    doc.set_posting_time = 1
    doc.posting_date = posting.date()
    doc.posting_time = posting.strftime("%H:%M:%S")
    doc.update_stock = int(bool(update_stock))
    doc.set_warehouse = set_warehouse
    doc.remarks = remarks
    doc.custom_client_id = client_id  # custom field added via fixture

    # Cash / credit: cash → is_pos + fully paid via mode_of_payment.
    pay_type = (payment_type or "").lower()
    if pay_type == "cash":
        doc.is_pos = 1
        # payments row filled after insert so grand_total is known.

    # Tax template — auto-apply if the site enforces mandatory taxes
    # and the caller didn't supply one.
    tax_template = _default_tax_template(company)
    if tax_template:
        doc.taxes_and_charges = tax_template

    for item in items:
        if not item.get("item_code"):
            frappe.throw(_("item_code is required on every line"))
        row = doc.append("items", {})
        row.item_code = item["item_code"]
        row.qty = float(item.get("qty") or 1)
        if item.get("uom"):
            row.uom = item["uom"]
        if item.get("conversion_factor"):
            row.conversion_factor = float(item["conversion_factor"])
        # Price — prefer price_list_rate so ERPNext computes discount_percentage.
        if item.get("price_list_rate") is not None:
            row.price_list_rate = float(item["price_list_rate"])
        if item.get("rate") is not None:
            row.rate = float(item["rate"])
        if item.get("discount_percentage") is not None:
            row.discount_percentage = float(item["discount_percentage"])
        if item.get("discount_amount") is not None:
            row.discount_amount = float(item["discount_amount"])
        if set_warehouse:
            row.warehouse = item.get("warehouse") or set_warehouse

    # Auto-tag sales person (commission tracking) if configured.
    sp = current_user_sales_person()
    if sp:
        doc.append("sales_team", {"sales_person": sp, "allocated_percentage": 100})

    # Invoice-level additional discount.
    if discount_amount is not None:
        doc.discount_amount = float(discount_amount)
        doc.apply_discount_on = apply_discount_on or "Grand Total"

    doc.insert(ignore_permissions=False)

    # Fill payment row only after insert so grand_total is computed.
    if pay_type == "cash" and submit:
        mop = mode_of_payment or "Cash"
        account = _default_mop_account(mop, company)
        if not account:
            frappe.throw(_("No default account configured for Mode of Payment {0}").format(mop))
        # clear any auto-added payments rows from Sales Invoice defaults
        doc.set("payments", [])
        doc.append("payments", {
            "mode_of_payment": mop,
            "account": account,
            "amount": float(doc.grand_total or 0),
        })
        doc.save()

    if submit:
        doc.submit()

    _record_outbox(client_id, doc.name, posting_ts, {
        "customer": customer,
        "items": items,
        "warehouse": set_warehouse,
        "payment_type": pay_type or None,
        "mode_of_payment": mode_of_payment,
    })
    frappe.db.commit()

    return {
        "name": doc.name,
        "grand_total": float(doc.grand_total or 0),
        "outstanding_amount": float(doc.outstanding_amount or 0),
        "status": doc.status,
        "docstatus": int(doc.docstatus or 0),
        "modified": naive_site_to_utc_iso(doc.modified),
        "idempotent_replay": False,
    }


def _default_mop_account(mop: str, company: str) -> Optional[str]:
    """Resolve the Mode of Payment's account for the given company."""
    acc = frappe.db.get_value(
        "Mode of Payment Account",
        {"parent": mop, "company": company},
        "default_account",
    )
    if acc:
        return acc
    # Fallback — any account on the MoP row
    rows = frappe.get_all(
        "Mode of Payment Account",
        filters={"parent": mop},
        fields=["default_account", "company"],
    )
    for r in rows:
        if r.get("default_account"):
            return r["default_account"]
    return None


@frappe.whitelist(methods=["POST"])
def update_draft(
    name: str,
    items: list[dict[str, Any]],
    remarks: Optional[str] = None,
    discount_amount: Optional[float] = None,
    apply_discount_on: Optional[str] = None,
    submit: int = 0,
    payment_type: Optional[str] = None,
    mode_of_payment: Optional[str] = None,
    warehouse: Optional[str] = None,
) -> dict:
    """In-place update a draft Sales Invoice.

    Van User roles have write permission on their own Sales Invoice drafts
    (they created the docs) but standard Frappe doesn't grant them delete
    permission — so the old "delete draft + resave" edit path threw
    ``PermissionError: Insufficient Permission for Sales Invoice``. This
    endpoint mutates the existing doc: clears + rebuilds ``items``,
    re-applies discount, optionally submits. Owner check keeps users from
    editing other salespeople's drafts.
    """
    if not name:
        frappe.throw(_("name required"))
    if not items:
        frappe.throw(_("At least one item is required"))

    doc = frappe.get_doc("Sales Invoice", name)
    if int(doc.docstatus or 0) != 0:
        frappe.throw(_("Only draft invoices can be edited"))
    # Owner check — if you created it, you can edit it. Avoids the "no
    # delete perm" error while still preventing cross-user edits.
    if doc.owner != frappe.session.user:
        # Fall back to role-based write perm — System / Accounts Manager
        # should still be able to edit any draft.
        if not frappe.has_permission("Sales Invoice", "write", doc=doc):
            frappe.throw(_("You cannot edit this draft"))

    set_warehouse = warehouse or doc.set_warehouse or _get_default_warehouse(doc.company)
    doc.set_warehouse = set_warehouse
    if remarks is not None:
        doc.remarks = remarks

    # payment_type swap: cash <-> credit. When moving to cash, set is_pos
    # so the POS flow activates on the next save (payments row filled
    # after save, same as `save()`).
    pay_type = (payment_type or "").lower()
    if pay_type == "cash":
        doc.is_pos = 1
    elif pay_type == "credit":
        doc.is_pos = 0
        doc.set("payments", [])

    # Rebuild items table. Clearing + appending keeps the child-row
    # docnames consistent with Frappe's expectations on save().
    doc.set("items", [])
    for item in items:
        if not item.get("item_code"):
            frappe.throw(_("item_code is required on every line"))
        row = doc.append("items", {})
        row.item_code = item["item_code"]
        row.qty = float(item.get("qty") or 1)
        if item.get("uom"):
            row.uom = item["uom"]
        if item.get("conversion_factor"):
            row.conversion_factor = float(item["conversion_factor"])
        if item.get("price_list_rate") is not None:
            row.price_list_rate = float(item["price_list_rate"])
        if item.get("rate") is not None:
            row.rate = float(item["rate"])
        if item.get("discount_percentage") is not None:
            row.discount_percentage = float(item["discount_percentage"])
        if item.get("discount_amount") is not None:
            row.discount_amount = float(item["discount_amount"])
        if set_warehouse:
            row.warehouse = item.get("warehouse") or set_warehouse

    if discount_amount is not None:
        doc.discount_amount = float(discount_amount)
        doc.apply_discount_on = apply_discount_on or "Grand Total"

    # ignore_version bypasses Frappe's optimistic-lock check (the
    # "Document has been modified after you have opened it" error).
    # We freshly loaded the doc via `frappe.get_doc` above so there's
    # no stale client-side modified timestamp to collide with — the
    # error was being thrown by ERPNext hooks that touch the parent
    # row (e.g. tax/total recalculation) between our load and save.
    doc.flags.ignore_version = True
    doc.save(ignore_permissions=False)

    if pay_type == "cash" and submit:
        mop = mode_of_payment or "Cash"
        account = _default_mop_account(mop, doc.company)
        if not account:
            frappe.throw(_("No default account configured for Mode of Payment {0}").format(mop))
        doc.set("payments", [])
        doc.append("payments", {
            "mode_of_payment": mop,
            "account": account,
            "amount": float(doc.grand_total or 0),
        })
        doc.flags.ignore_version = True
        doc.save()

    if submit:
        doc.submit()

    frappe.db.commit()
    return {
        "name": doc.name,
        "grand_total": float(doc.grand_total or 0),
        "outstanding_amount": float(doc.outstanding_amount or 0),
        "status": doc.status,
        "docstatus": int(doc.docstatus or 0),
        "modified": naive_site_to_utc_iso(doc.modified),
    }


@frappe.whitelist(methods=["POST"])
def submit_draft(name: str, mode_of_payment: Optional[str] = None) -> dict:
    """Submit an existing draft Sales Invoice, loading it from the database.

    NEVER route this through ``frappe.client.submit``. That endpoint does
    ``frappe.get_doc(<client dict>)``, which builds a fresh in-memory doc
    from the payload instead of loading the stored one. Two consequences:

    1. ``_original_modified`` is never populated from the row, so
       ``Document.check_if_latest`` sees a mismatch and raises
       ``TimestampMismatchError`` — the "Document has been modified after
       you have opened it" toast the field reported.
    2. If that check ever passed, ``db_update`` would write the payload
       doc verbatim — blanking ``items``, taxes and totals on submit.

    So the timestamp error was protecting the data, not corrupting it.
    Loading by name fixes both.

    Cash (``is_pos``) drafts need their ``payments`` row filled before
    submit or ERPNext rejects the doc, so mirror ``update_draft``'s
    behaviour when the row is missing.
    """
    if not name:
        frappe.throw(_("name required"))

    doc = frappe.get_doc("Sales Invoice", name)
    if cint(doc.docstatus) != 0:
        frappe.throw(_("Only draft invoices can be submitted"))
    # Owner check first — Van Users hold write/submit on their own drafts
    # but not on other salespeople's (same rule as `update_draft`).
    if doc.owner != frappe.session.user:
        if not frappe.has_permission("Sales Invoice", "submit", doc=doc):
            frappe.throw(_("You cannot submit this invoice"))

    if cint(doc.is_pos) and not doc.get("payments"):
        mop = mode_of_payment or "Cash"
        account = _default_mop_account(mop, doc.company)
        if not account:
            frappe.throw(_("No default account configured for Mode of Payment") + ": " + mop)
        doc.append("payments", {
            "mode_of_payment": mop,
            "account": account,
            "amount": flt(doc.grand_total),
        })
        doc.save()

    doc.submit()
    frappe.db.commit()
    return {
        "name": doc.name,
        "grand_total": flt(doc.grand_total),
        "outstanding_amount": flt(doc.outstanding_amount),
        "status": doc.status,
        "docstatus": cint(doc.docstatus),
        "modified": naive_site_to_utc_iso(doc.modified),
    }


@frappe.whitelist(methods=["POST"])
def return_against(
    client_id: str,
    original_name: str,
    items: list[dict[str, Any]],
    posting_ts: Optional[str] = None,
    remarks: Optional[str] = None,
    submit: int = 1,
) -> dict:
    """Create a Sales Return (Credit Note) against an existing submitted invoice.

    Each `items[i]` must contain `item_code` and `qty` (positive number — we
    negate). Optionally `rate`, `uom`, `warehouse` — otherwise copied from
    the original line. Idempotent by `client_id` like normal invoice save.
    """
    if not client_id:
        frappe.throw(_("client_id is required"))
    if not original_name:
        frappe.throw(_("original_name is required"))
    if not items:
        frappe.throw(_("At least one return line is required"))

    existing = _existing_by_client_id(client_id)
    if existing:
        doc = frappe.get_doc("Sales Invoice", existing)
        return {
            "name": doc.name,
            "grand_total": float(doc.grand_total or 0),
            "status": doc.status,
            "modified": naive_site_to_utc_iso(doc.modified),
            "idempotent_replay": True,
        }

    original = frappe.get_doc("Sales Invoice", original_name)
    if original.docstatus != 1:
        frappe.throw(_("Original invoice must be submitted"))
    if int(original.is_return or 0):
        frappe.throw(_("Cannot return against a credit note"))

    orig_line_by_code: dict[str, Any] = {}
    for line in original.items:
        orig_line_by_code.setdefault(line.item_code, line)

    posting = parse_client_ts(posting_ts) if posting_ts else frappe.utils.now_datetime()

    doc = frappe.new_doc("Sales Invoice")
    doc.customer = original.customer
    doc.company = original.company
    doc.currency = original.currency
    doc.selling_price_list = original.selling_price_list
    doc.price_list_currency = original.price_list_currency
    doc.plc_conversion_rate = original.plc_conversion_rate
    doc.conversion_rate = original.conversion_rate
    doc.is_return = 1
    doc.return_against = original.name
    doc.update_stock = int(original.update_stock or 0)
    doc.set_warehouse = original.set_warehouse
    doc.set_posting_time = 1
    doc.posting_date = posting.date()
    doc.posting_time = posting.strftime("%H:%M:%S")
    doc.taxes_and_charges = original.taxes_and_charges
    doc.remarks = remarks or _("Return against {0}").format(original.name)
    doc.custom_client_id = client_id

    for item in items:
        code = item.get("item_code")
        if not code:
            frappe.throw(_("item_code is required on every return line"))
        qty = float(item.get("qty") or 0)
        if qty <= 0:
            frappe.throw(_("Return qty must be positive for {0}").format(code))
        orig = orig_line_by_code.get(code)
        row = doc.append("items", {})
        row.item_code = code
        row.qty = -qty
        row.uom = item.get("uom") or (orig.uom if orig else None)
        row.conversion_factor = float(item.get("conversion_factor") or (orig.conversion_factor if orig else 1) or 1)
        row.rate = float(item.get("rate") if item.get("rate") is not None else (orig.rate if orig else 0))
        if orig is not None and item.get("rate") is None:
            row.price_list_rate = float(orig.price_list_rate or 0)
            if orig.discount_percentage:
                row.discount_percentage = float(orig.discount_percentage or 0)
        row.warehouse = item.get("warehouse") or (orig.warehouse if orig else doc.set_warehouse)
        if orig is not None:
            row.sales_invoice_item = orig.name  # links back to source row

    # Keep sales person tagging on returns for reporting consistency.
    sp = current_user_sales_person()
    if sp:
        doc.append("sales_team", {"sales_person": sp, "allocated_percentage": 100})

    doc.insert(ignore_permissions=False)
    if submit:
        doc.submit()

    _record_outbox(client_id, doc.name, posting_ts, {
        "return_against": original.name,
        "items": items,
    })
    frappe.db.commit()

    return {
        "name": doc.name,
        "grand_total": float(doc.grand_total or 0),
        "outstanding_amount": float(doc.outstanding_amount or 0),
        "status": doc.status,
        "docstatus": int(doc.docstatus or 0),
        "modified": naive_site_to_utc_iso(doc.modified),
        "idempotent_replay": False,
        "is_return": 1,
    }


@frappe.whitelist(methods=["GET"])
def list_mine(
    limit: int = 50,
    customer: Optional[str] = None,
    is_return: Optional[int] = None,
) -> list[dict]:
    """List the current user's Sales Invoices.

    `is_return` filter is optional: pass ``1`` to retrieve only credit notes
    (Sales Returns), ``0`` for regular invoices. Omit to include both. The
    returned rows always carry the `is_return` + `return_against` fields so
    the UI can render the "linked original invoice" ribbon without a
    second round-trip.
    """
    filters: dict = {"owner": frappe.session.user, "docstatus": ["in", [0, 1]]}
    if customer:
        filters["customer"] = customer
    if is_return is not None:
        filters["is_return"] = int(is_return)
    rows = frappe.get_all(
        "Sales Invoice",
        filters=filters,
        fields=[
            "name",
            "customer",
            "customer_name",
            "grand_total",
            "outstanding_amount",
            "status",
            "posting_date",
            "posting_time",
            "is_return",
            "return_against",
            "docstatus",
            "modified",
        ],
        order_by="posting_date desc, posting_time desc",
        limit=int(limit),
    )
    for r in rows:
        r["modified"] = naive_site_to_utc_iso(r.get("modified"))
    return rows


@frappe.whitelist(methods=["GET"])
def detail(name: str) -> dict:
    doc = frappe.get_doc("Sales Invoice", name)
    taxes = [
        {
            "description": t.description,
            "rate": float(t.rate or 0),
            "tax_amount": float(t.tax_amount or 0),
            "total": float(t.total or 0),
        }
        for t in (doc.taxes or [])
    ]
    sales_persons = [
        {
            "sales_person": sp.sales_person,
            "allocated_percentage": float(sp.allocated_percentage or 0),
        }
        for sp in (doc.sales_team or [])
    ]
    return {
        "name": doc.name,
        "customer": doc.customer,
        "customer_name": doc.customer_name,
        "company": doc.company,
        "currency": doc.currency,
        "posting_date": str(doc.posting_date) if doc.posting_date else None,
        "posting_time": str(doc.posting_time) if doc.posting_time else None,
        "due_date": str(doc.due_date) if doc.due_date else None,
        "is_return": int(doc.is_return or 0),
        "grand_total": float(doc.grand_total or 0),
        "net_total": float(doc.net_total or 0),
        "total_taxes_and_charges": float(doc.total_taxes_and_charges or 0),
        "discount_amount": float(doc.discount_amount or 0),
        "outstanding_amount": float(doc.outstanding_amount or 0),
        "paid_amount": float((doc.grand_total or 0) - (doc.outstanding_amount or 0)),
        "status": doc.status,
        "docstatus": int(doc.docstatus or 0),
        "remarks": doc.remarks,
        "items": [
            {
                "item_code": i.item_code,
                "item_name": i.item_name,
                "qty": float(i.qty or 0),
                "rate": float(i.rate or 0),
                "price_list_rate": float(i.price_list_rate or 0),
                "discount_percentage": float(i.discount_percentage or 0),
                "discount_amount": float(i.discount_amount or 0),
                "amount": float(i.amount or 0),
                "uom": i.uom,
                "warehouse": i.warehouse,
            }
            for i in doc.items
        ],
        "taxes": taxes,
        "sales_persons": sales_persons,
        "modified": naive_site_to_utc_iso(doc.modified),
    }
