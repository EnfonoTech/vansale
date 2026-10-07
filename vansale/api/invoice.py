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
from frappe.utils import cint, flt, getdate, nowdate

from vansale.api.datetime_util import naive_site_to_utc_iso, parse_client_ts
from vansale.api.sales_return import append_return_rows, resolve_return_reason, returned_qty_by_row
from vansale.api.me import cash_sale_settings, current_user_sales_person


def _user_default(allow: str) -> Optional[str]:
    return frappe.db.get_value(
        "User Permission",
        {"user": frappe.session.user, "allow": allow, "is_default": 1},
        "for_value",
    )


def _get_default_warehouse(company: str) -> Optional[str]:
    """Prefer the Van User's configured warehouse; fall back to the stock default.

    (ERPNext v15 Company has no `default_warehouse` column; reading it crashed
    for any user without a default Warehouse permission.)
    """
    return _user_default("Warehouse") or frappe.db.get_single_value(
        "Stock Settings", "default_warehouse"
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


def _resolve_tax_template(customer: Optional[str], company: str, posting_date) -> Optional[str]:
    """Resolve the Sales Taxes and Charges Template the way ERPNext does.

    Chain: Customer.tax_category (or the address's, per Accounts Settings
    `determine_address_tax_category_from`) → Tax Rule → template. That is
    `erpnext.accounts.party.set_taxes`, which is what the desk form calls, so a
    zero-rated / export / exempt customer gets the same treatment in the van as
    at the counter.

    Falls back to the company default. Previously `save` used the company
    default unconditionally, which silently charged standard VAT to
    zero-rated customers.
    """
    if customer:
        try:
            from erpnext.accounts.party import set_taxes

            cust = frappe.db.get_value(
                "Customer", customer, ["tax_category", "customer_group"], as_dict=True
            ) or {}
            template = set_taxes(
                party=customer,
                party_type="Customer",
                posting_date=posting_date,
                company=company,
                customer_group=cust.get("customer_group"),
                tax_category=cust.get("tax_category"),
            )
            if template:
                return template
        except Exception:
            # A Tax Rule misconfiguration must not block a sale in the field.
            frappe.log_error(frappe.get_traceback(), "vansale: tax template resolution failed")
    return _default_tax_template(company)


@frappe.whitelist(methods=["GET"])
def tax_info(customer: Optional[str] = None, posting_date: Optional[str] = None) -> dict:
    """Tax template + headline rate for the invoice form's live totals.

    The app used to hardcode 15% client-side. That is wrong for any non-KSA
    company, for zero-rated and exempt customers, and it hid the
    inclusive-vs-exclusive question entirely.

    `inclusive` reflects `included_in_print_rate` on the template rows: when
    true the price list rate ALREADY contains the tax, so the client must
    back it out rather than add on top. It is a property of the tax template,
    not a van setting — whoever configures the template decides.

    `rate` sums only `On Net Total` rows, which is the shape of a VAT line.
    Compound and "On Previous Row" templates cannot be collapsed to a single
    percentage, so `simple` comes back false and the client shows the
    server-computed figure after save instead of guessing.
    """
    company = _user_company()
    if not company:
        frappe.throw(_("No company configured for this user"))
    date = getdate(posting_date) if posting_date else nowdate()

    template = _resolve_tax_template(customer, company, date)
    rows: list[dict] = []
    rate = 0.0
    inclusive = False
    simple = True

    if template:
        from erpnext.controllers.accounts_controller import get_taxes_and_charges

        for r in get_taxes_and_charges("Sales Taxes and Charges Template", template) or []:
            charge_type = r.get("charge_type")
            row_rate = flt(r.get("rate"))
            rows.append({
                "description": r.get("description"),
                "charge_type": charge_type,
                "rate": row_rate,
                "included_in_print_rate": cint(r.get("included_in_print_rate")),
            })
            if cint(r.get("included_in_print_rate")):
                inclusive = True
            if charge_type == "On Net Total":
                rate += row_rate
            else:
                simple = False

    return {
        "template": template,
        "rate": rate,
        "inclusive": inclusive,
        "simple": simple,
        "taxes": rows,
    }


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

    # Cash / credit. Cash is posted per the "Cash sale posting" setting:
    # POS Invoice → is_pos + payments row; Payment Entry → normal invoice and a
    # Payment Entry against it on submit.
    pay_type = (payment_type or "").lower()
    pe_mode = pay_type == "cash" and _cash_via_payment_entry()
    if pay_type == "cash" and not pe_mode:
        doc.is_pos = 1
        # payments row filled after insert so grand_total is known.
    if pe_mode:
        _set_cash_mode(doc, mode_of_payment or "Cash")

    # Tax template — resolved through the customer's Tax Category / Tax Rule
    # so a zero-rated or exempt customer is not charged standard VAT. Falls
    # back to the company default. Must match what `tax_info` told the client,
    # or the preview and the posted document disagree.
    tax_template = _resolve_tax_template(customer, company, doc.posting_date)
    if tax_template:
        doc.taxes_and_charges = tax_template

    _append_items(doc, items, set_warehouse)
    _apply_template_taxes(doc)

    # Auto-tag sales person (commission tracking) if configured.
    sp = current_user_sales_person()
    if sp:
        doc.append("sales_team", {"sales_person": sp, "allocated_percentage": 100})

    # Invoice-level additional discount.
    if discount_amount is not None:
        doc.discount_amount = float(discount_amount)
        doc.apply_discount_on = apply_discount_on or "Grand Total"

    doc.insert(ignore_permissions=False)

    # Fill payment row only after insert so grand_total is computed. Drafts
    # get it too: it is the only place the chosen mode is stored, so editing
    # or submitting the draft later would otherwise fall back to "Cash".
    if pay_type == "cash" and not pe_mode:
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

    payment_entry = None
    if submit:
        doc.submit()
        payment_entry = _cash_payment_entry(doc)

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
        "payment_entry": payment_entry,
    }


def _cash_via_payment_entry() -> bool:
    return cash_sale_settings()["posting"] == "Payment Entry"


def _set_cash_mode(doc, mode_of_payment: str) -> None:
    """Payment Entry posting: no POS payments table, so keep the chosen mode on
    the invoice until submit creates the Payment Entry."""
    from vansale.api.payment import _resolve_accounts

    _resolve_accounts(doc.company, mode_of_payment)  # fail now, not at submit
    doc.is_pos = 0
    doc.set("payments", [])
    if doc.meta.has_field("custom_vansale_payment_mode"):
        doc.custom_vansale_payment_mode = mode_of_payment


def _cash_payment_entry(inv) -> Optional[str]:
    """After submit: Payment Entry for a cash sale in "Payment Entry" posting.

    Covers the invoice's outstanding amount with the mode stored on it, and is
    submitted or left as a draft per the "Payment Entry status" setting. Runs
    in the invoice's transaction, so a failure rolls the sale back too.
    """
    mode = inv.get("custom_vansale_payment_mode")
    amount = flt(inv.outstanding_amount)
    if not mode or amount <= 0:
        return None
    from vansale.api.payment import build_payment_entry, submit_if_configured

    pe = build_payment_entry(
        inv.company,
        inv.customer,
        amount,
        mode,
        inv.posting_date,
        # Bank-type modes need a reference; the invoice is the natural one.
        reference_no=inv.name,
        reference_date=inv.posting_date,
        remarks=_("Cash sale {0}").format(inv.name),
    )
    pe.append("references", {
        "reference_doctype": "Sales Invoice",
        "reference_name": inv.name,
        "total_amount": flt(inv.grand_total),
        "outstanding_amount": amount,
        "allocated_amount": amount,
    })
    pe.insert()
    submit_if_configured(pe)
    return pe.name


def _append_items(doc, items: list[dict[str, Any]], set_warehouse: Optional[str]) -> None:
    """Add the client's lines to the invoice.

    A missing or zero qty used to be posted as qty 1, so a line the driver
    had zeroed out was still billed. Reject it instead.
    """
    for item in items:
        if not item.get("item_code"):
            frappe.throw(_("item_code is required on every line"))
        qty = flt(item.get("qty"))
        if qty <= 0:
            frappe.throw(_("Quantity must be greater than 0 for item {0}").format(item["item_code"]))
        row = doc.append("items", {})
        row.item_code = item["item_code"]
        row.qty = qty
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


def _apply_template_taxes(doc) -> None:
    """Fill the taxes table from `taxes_and_charges`, as the desk form does.

    On an API insert ERPNext only does this when Accounts Settings
    `add_taxes_from_taxes_and_charges_template` is on. With it off, a credit
    invoice got VAT only from item tax templates, so items without one were
    sold with no VAT while the app showed 15%.
    """
    if doc.get("taxes_and_charges") and not doc.get("taxes"):
        doc.append_taxes_from_master()


def _default_mop_account(mop: str, company: str) -> Optional[str]:
    """Resolve the Mode of Payment's account for the given company."""
    # Only this company's account: borrowing another company's account
    # posted the payment to the wrong books.
    return frappe.db.get_value(
        "Mode of Payment Account",
        {"parent": mop, "company": company},
        "default_account",
    )


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
    pe_mode = pay_type == "cash" and _cash_via_payment_entry()
    if pe_mode:
        _set_cash_mode(doc, mode_of_payment or "Cash")
    elif pay_type == "cash":
        doc.is_pos = 1
    elif pay_type == "credit":
        doc.is_pos = 0
        doc.set("payments", [])
    if pay_type != "cash" and doc.meta.has_field("custom_vansale_payment_mode"):
        doc.custom_vansale_payment_mode = None

    # Rebuild items table. Clearing + appending keeps the child-row
    # docnames consistent with Frappe's expectations on save().
    doc.set("items", [])
    _append_items(doc, items, set_warehouse)
    _apply_template_taxes(doc)

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

    if pay_type == "cash" and not pe_mode:
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

    payment_entry = None
    if submit:
        doc.submit()
        payment_entry = _cash_payment_entry(doc)

    frappe.db.commit()
    return {
        "payment_entry": payment_entry,
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
    payment_entry = _cash_payment_entry(doc)
    frappe.db.commit()
    return {
        "payment_entry": payment_entry,
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
    reason: Optional[str] = None,
    note: Optional[str] = None,
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

    # A stated cause is mandatory — a credit note nobody can explain is
    # unauditable, and "why are returns up this month" is the first question
    # the office asks. Resolved BEFORE the idempotency check so a replay
    # cannot smuggle a reason-less return through on the second attempt.
    # `remarks` is the legacy single free-text field older APKs send; it is
    # accepted as the reason source so returns keep working mid-rollout.
    reason_option, reason_text = resolve_return_reason(reason or remarks)

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
    extra = (note or "").strip()
    doc.remarks = f"{reason_text} — {extra}" if extra and extra != reason_text else reason_text
    if frappe.get_meta("Sales Invoice").has_field("custom_return_reason"):
        doc.custom_return_reason = reason_option
    doc.custom_client_id = client_id

    append_return_rows(doc, original, items)

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
    returned = returned_qty_by_row(doc) if doc.docstatus == 1 and not doc.is_return else {}
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
        "is_pos": int(doc.is_pos or 0),
        "payment_type": "cash" if (doc.is_pos or doc.get("custom_vansale_payment_mode")) else "credit",
        "mode_of_payment": (
            doc.payments[0].mode_of_payment if doc.get("payments") else doc.get("custom_vansale_payment_mode")
        ),
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
                "name": i.name,
                "item_code": i.item_code,
                "item_name": i.item_name,
                "qty": float(i.qty or 0),
                "returned_qty": returned.get(i.name, 0.0),
                "rate": float(i.rate or 0),
                "price_list_rate": float(i.price_list_rate or 0),
                "discount_percentage": float(i.discount_percentage or 0),
                "discount_amount": float(i.discount_amount or 0),
                "amount": float(i.amount or 0),
                "uom": i.uom,
                "conversion_factor": float(i.conversion_factor or 1),
                "stock_uom": i.stock_uom,
                "warehouse": i.warehouse,
            }
            for i in doc.items
        ],
        "taxes": taxes,
        "sales_persons": sales_persons,
        "modified": naive_site_to_utc_iso(doc.modified),
    }
