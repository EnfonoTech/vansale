"""Sales return (credit note) endpoints.

Returns are modelled as Sales Invoice with ``is_return=1``. Qty on each
line is negative; total must not exceed the original invoice's qty.
"""

from __future__ import annotations

from typing import Any, Optional

import frappe
from frappe import _
from frappe.utils import flt

from vansale.api.access import check_read, readable_doc
from vansale.api.outbox import claim
from vansale.api.datetime_util import naive_site_to_utc_iso, parse_client_ts

# Structured return reasons. Mirrors the `custom_return_reason` Select options
# shipped in `fixtures/custom_field.json` — keep the two in step.
RETURN_REASONS = (
    "Damaged",
    "Expired",
    "Wrong Item",
    "Customer Refused",
    "Short Delivery",
    "Other",
)


def _stock_qty(line) -> float:
    return flt(line.stock_qty) or flt(line.qty) * (flt(line.conversion_factor) or 1)


def returned_qty_by_row(original) -> dict[str, float]:
    """Stock qty already returned per original invoice row (submitted returns).

    In stock units because a line sold in cartons may be returned in pieces.
    Returns made before rows were linked (`sales_invoice_item` empty) are
    counted against that item's rows in invoice order.
    """
    returned = {line.name: 0.0 for line in original.items}
    unlinked: dict[str, float] = {}
    for r in frappe.db.sql(
        """
        SELECT sii.sales_invoice_item, sii.item_code, -sii.stock_qty AS qty
        FROM `tabSales Invoice Item` sii
        JOIN `tabSales Invoice` si ON si.name = sii.parent
        WHERE si.return_against = %s AND si.is_return = 1 AND si.docstatus = 1
        """,
        original.name,
        as_dict=True,
    ):
        if r.sales_invoice_item in returned:
            returned[r.sales_invoice_item] += flt(r.qty)
        else:
            unlinked[r.item_code] = unlinked.get(r.item_code, 0.0) + flt(r.qty)
    for line in original.items:
        take = min(unlinked.get(line.item_code, 0.0), _stock_qty(line) - returned[line.name])
        if take > 0:
            returned[line.name] += take
            unlinked[line.item_code] -= take
    return returned


def fully_returned(invoices: list[str]) -> set[str]:
    """Invoices with nothing left to return (every row returned on submitted
    credit notes). Same counting as `returned_qty_by_row`, batched."""
    if not invoices:
        return set()
    rows = frappe.db.sql(
        """SELECT parent, name, item_code, stock_qty AS qty FROM `tabSales Invoice Item`
           WHERE parent IN %(names)s ORDER BY parent, idx""",
        {"names": tuple(invoices)},
        as_dict=True,
    )
    returns = frappe.db.sql(
        """
        SELECT si.return_against AS invoice, sii.sales_invoice_item, sii.item_code, -sii.stock_qty AS qty
        FROM `tabSales Invoice Item` sii
        JOIN `tabSales Invoice` si ON si.name = sii.parent
        WHERE si.return_against IN %(names)s AND si.is_return = 1 AND si.docstatus = 1
        """,
        {"names": tuple(invoices)},
        as_dict=True,
    )
    left = {r.name: flt(r.qty) for r in rows}
    unlinked: dict[tuple[str, str], float] = {}
    for r in returns:
        if r.sales_invoice_item in left:
            left[r.sales_invoice_item] -= flt(r.qty)
        else:
            key = (r.invoice, r.item_code)
            unlinked[key] = unlinked.get(key, 0.0) + flt(r.qty)
    for r in rows:
        take = min(unlinked.get((r.parent, r.item_code), 0.0), left[r.name])
        if take > 0:
            left[r.name] -= take
            unlinked[(r.parent, r.item_code)] -= take
    by_invoice: dict[str, bool] = {}
    for r in rows:
        by_invoice[r.parent] = by_invoice.get(r.parent, True) and left[r.name] <= 1e-9
    return {inv for inv, done in by_invoice.items() if done}


def return_uom_factor(item_code: str, uom: str) -> Optional[float]:
    """Conversion factor of `uom` for the item (stock UOM = 1); None if the
    item has no such unit."""
    if uom == frappe.db.get_value("Item", item_code, "stock_uom"):
        return 1.0
    cf = frappe.db.get_value("UOM Conversion Detail", {"parent": item_code, "uom": uom}, "conversion_factor")
    return flt(cf) or None


def return_uoms(invoice) -> dict[str, list[dict]]:
    """Per invoice row, the units it may be returned in: the sold UOM first,
    then the item's smaller units (see `append_return_rows`)."""
    codes = list({i.item_code for i in invoice.items})
    stock = dict(frappe.get_all("Item", {"name": ["in", codes]}, ["name", "stock_uom"], as_list=True))
    units: dict[str, dict[str, float]] = {c: {stock.get(c): 1.0} for c in codes if stock.get(c)}
    for r in frappe.get_all(
        "UOM Conversion Detail",
        {"parent": ["in", codes], "parenttype": "Item"},
        ["parent", "uom", "conversion_factor"],
    ):
        units.setdefault(r.parent, {})[r.uom] = flt(r.conversion_factor) or 1.0
    out = {}
    for line in invoice.items:
        cf = flt(line.conversion_factor) or 1
        smaller = sorted(
            ((u, f) for u, f in units.get(line.item_code, {}).items() if u != line.uom and f < cf - 1e-9),
            key=lambda x: -x[1],
        )
        out[line.name] = [{"uom": line.uom, "conversion_factor": cf}] + [
            {"uom": u, "conversion_factor": f} for u, f in smaller
        ]
    return out


def append_return_rows(doc, original, items: list[dict[str, Any]]) -> None:
    """Add return lines to `doc`, each tied to one row of the original invoice.

    A line names its row with `sales_invoice_item`; without it, the first row
    of that item with qty left is used. Qty may not exceed what is left on the
    row after earlier returns (counted in stock units). A line may give a
    `uom`: the sold one or a smaller one (sold a carton, return pieces); the
    rate is the sale's, converted (carton rate / 12 per piece). ERPNext refuses
    a return rate above the sale's, so a bigger UOM is not allowed. Discount
    and warehouse come from the original row. Lines with qty 0 are skipped.
    """
    from vansale.api.me import rate_precision

    rows = {line.name: line for line in original.items}
    left = {
        name: _stock_qty(rows[name]) - done for name, done in returned_qty_by_row(original).items()
    }
    precision = rate_precision()
    for item in items:
        code = item.get("item_code")
        qty = abs(flt(item.get("qty")))
        if qty <= 0:
            continue
        row_name = item.get("sales_invoice_item")
        if row_name:
            if row_name not in rows:
                frappe.throw(_("Line {0} is not on invoice {1}").format(row_name, original.name))
            orig = rows[row_name]
        else:
            if not code:
                frappe.throw(_("item_code is required on every return line"))
            candidates = [l for l in original.items if l.item_code == code]
            if not candidates:
                frappe.throw(_("Item {0} not in original invoice").format(code))
            orig = next((l for l in candidates if left[l.name] > 0), candidates[0])
        orig_cf = flt(orig.conversion_factor) or 1
        uom = item.get("uom") or orig.uom
        cf = orig_cf if uom == orig.uom else return_uom_factor(orig.item_code, uom)
        if cf is None:
            frappe.throw(_("{0} is not a unit of item {1}").format(uom, orig.item_code))
        if cf > orig_cf + 1e-9:
            frappe.throw(
                _("Return {0} in {1} or a smaller unit, not {2}").format(orig.item_code, orig.uom, uom)
            )
        if qty * cf > left[orig.name] + 1e-9:
            frappe.throw(
                _("Cannot return {0} {1} of {2}: only {3} {1} left after earlier returns").format(
                    qty, uom, orig.item_code, flt(max(left[orig.name], 0) / cf, 3)
                )
            )
        left[orig.name] -= qty * cf

        row = doc.append("items", {})
        row.item_code = orig.item_code
        row.qty = -qty
        row.uom = uom
        row.conversion_factor = cf
        # The sale's price per stock unit, in the return's UOM.
        row.price_list_rate = flt(flt(orig.price_list_rate) / orig_cf * cf, precision)
        row.rate = flt(flt(orig.rate) / orig_cf * cf, precision)
        if orig.discount_percentage:
            row.discount_percentage = flt(orig.discount_percentage)
        row.warehouse = item.get("warehouse") or orig.warehouse or doc.set_warehouse
        row.sales_invoice_item = orig.name

    if not doc.get("items"):
        frappe.throw(_("Enter a return qty for at least one line"))

    # Same taxes as the sale (see invoice._apply_template_taxes).
    doc.taxes_and_charges = original.taxes_and_charges
    if doc.taxes_and_charges and not doc.get("taxes"):
        doc.append_taxes_from_master()


def resolve_return_reason(reason: Optional[str]) -> tuple[str, str]:
    """Split the client's `reason` into (structured option, remarks text).

    A reason is mandatory: a credit note with no stated cause is unauditable,
    and "why are returns up this month" is the first question the office asks.

    Older APKs send free text here rather than one of the options. Those are
    filed as "Other" with the text preserved in remarks instead of being
    rejected — refusing them would break returns on every phone that has not
    updated yet, mid-rollout.
    """
    text = (reason or "").strip()
    if not text:
        frappe.throw(_("A return reason is required"))
    if text in RETURN_REASONS:
        return text, text
    return "Other", text


def _record_outbox(client_id: str, ref_name: str, posting_ts: Optional[str], payload: dict) -> None:
    if not client_id:
        return
    if frappe.db.exists("Vansale Outbox", client_id):
        doc = frappe.get_doc("Vansale Outbox", client_id)
    else:
        doc = frappe.new_doc("Vansale Outbox")
        doc.client_id = client_id
    doc.event_type = "return"
    doc.user = frappe.session.user
    doc.client_ts = parse_client_ts(posting_ts) if posting_ts else None
    doc.drained_at = frappe.utils.now_datetime()
    doc.status = "processed"
    doc.ref_doctype = "Sales Invoice"
    doc.ref_name = ref_name
    doc.payload_json = frappe.as_json(payload)
    doc.save(ignore_permissions=True)


def build_return_against(original, items: list[dict[str, Any]], posting=None):
    """Unsaved credit note against `original` (shared by save, return_against, preview)."""
    from vansale.api.me import current_user_sales_person

    if original.docstatus != 1:
        frappe.throw(_("Original invoice must be submitted"))
    if int(original.is_return or 0):
        frappe.throw(_("Cannot return against a credit note"))
    posting = posting or frappe.utils.now_datetime()

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
    append_return_rows(doc, original, items)
    sp = current_user_sales_person()
    if sp:
        doc.append("sales_team", {"sales_person": sp, "allocated_percentage": 100})
    _decide_outstanding(doc, original)
    return doc


def _decide_outstanding(doc, original) -> None:
    """Unpaid original invoice (outstanding covers the credit) → the credit
    reduces that invoice's balance, nothing to refund. Paid (or not enough
    left) → the credit note keeps its own balance, refundable now or later.
    ERPNext itself forces the second case when the credit is larger."""
    doc.set_missing_values()
    doc.calculate_taxes_and_totals()
    credit = abs(flt(doc.rounded_total) or flt(doc.grand_total))
    doc.update_outstanding_for_self = 0 if flt(original.outstanding_amount) >= credit - 0.005 else 1


def refund_owed(cn) -> float:
    """What may still be paid back on a credit note: its open credit less
    refunds already made as drafts (they don't reduce the balance until the
    office submits them, and must not be paid twice)."""
    from vansale.api.payment import pending_by_invoice

    if not cn.is_return or cn.docstatus != 1:
        return 0.0
    owed = abs(min(flt(cn.outstanding_amount), 0.0))
    drafts = abs(pending_by_invoice([cn.name]).get(cn.name, 0.0))
    return max(owed - drafts, 0.0)


def refund_credit_note(cn, refund: Optional[dict]) -> Optional[str]:
    """Pay the customer back for a credit note (Payment Entry "Pay"), at the
    return or later; submitted or a draft per the cash-sale / refund status."""
    from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry
    from vansale.api.payment import _needs_reference, _resolve_accounts, check_mode_allowed, submit_if_configured

    if not refund or not refund.get("mode_of_payment"):
        return None
    owed = refund_owed(cn)
    if owed <= 0.005:
        frappe.throw(_("Nothing to refund on {0}: no credit left to pay back").format(cn.name))
    amount = flt(refund.get("amount")) or owed
    if amount > owed + 0.005:
        frappe.throw(_("Refund ({0}) is more than the credit ({1})").format(amount, owed))
    mode = refund["mode_of_payment"]
    check_mode_allowed(mode)
    _receivable, account = _resolve_accounts(cn.company, mode)

    pe = get_payment_entry("Sales Invoice", cn.name)
    pe.mode_of_payment = mode
    pe.paid_from = account
    pe.paid_from_account_currency = frappe.db.get_value("Account", account, "account_currency")
    pe.paid_amount = amount
    pe.received_amount = amount
    pe.references[0].allocated_amount = -amount
    if _needs_reference(cn.company, mode):
        pe.reference_no = refund.get("reference_no") or cn.name
        pe.reference_date = cn.posting_date
    pe.remarks = _("Refund for {0}").format(cn.name)
    pe.insert()
    submit_if_configured(pe)
    return pe.name


@frappe.whitelist(methods=["POST"])
def refund(
    client_id: str,
    credit_note: str,
    mode_of_payment: str,
    amount: Optional[float] = None,
    reference_no: Optional[str] = None,
    posting_ts: Optional[str] = None,
) -> dict:
    """Pay out a credit note later — a return kept as customer credit at the
    time. Same Payment Entry as "Refund now" on the return screens."""
    from vansale.api.payment import _record_outbox

    if not client_id:
        frappe.throw(_("client_id is required"))
    existing = claim(client_id, "payment", "Payment Entry")
    if existing:
        return {"payment_entry": existing, "idempotent_replay": True}
    cn = readable_doc("Sales Invoice", credit_note)
    if not cn.is_return or cn.docstatus != 1:
        frappe.throw(_("{0} is not a submitted credit note").format(credit_note))
    pe = refund_credit_note(
        cn, {"mode_of_payment": mode_of_payment, "amount": amount, "reference_no": reference_no}
    )
    _record_outbox(client_id, pe, posting_ts, {"credit_note": cn.name, "amount": amount, "mode": mode_of_payment})
    frappe.db.commit()
    return {
        "payment_entry": pe,
        "docstatus": frappe.db.get_value("Payment Entry", pe, "docstatus"),
        "idempotent_replay": False,
    }


def _set_reason(doc, reason_option: str, reason_text: str, note: Optional[str]) -> None:
    extra = (note or "").strip()
    doc.remarks = f"{reason_text} — {extra}" if extra and extra != reason_text else reason_text
    # Guarded: a site that has not migrated the fixture yet still takes returns,
    # it just loses the structured breakdown until the next migrate.
    if doc.meta.has_field("custom_return_reason"):
        doc.custom_return_reason = reason_option


@frappe.whitelist(methods=["POST"])
def save(
    client_id: str,
    original_invoice: str,
    items: list[dict[str, Any]],
    reason: Optional[str] = None,
    note: Optional[str] = None,
    posting_ts: Optional[str] = None,
    submit: int = 1,
    refund: Optional[dict] = None,
) -> dict:
    if not client_id:
        frappe.throw(_("client_id is required"))
    if not original_invoice:
        frappe.throw(_("Original invoice required"))
    if not items:
        frappe.throw(_("At least one line is required"))

    # Validated before the idempotency check so a replay cannot smuggle a
    # reason-less return through on the second attempt.
    reason_option, reason_text = resolve_return_reason(reason)

    existing = claim(client_id, "return", "Sales Invoice")
    if existing:
        doc = frappe.get_doc("Sales Invoice", existing)
        return {
            "name": doc.name,
            "grand_total": float(doc.grand_total or 0),
            "status": doc.status,
            "idempotent_replay": True,
        }

    original = readable_doc("Sales Invoice", original_invoice)
    posting = parse_client_ts(posting_ts) if posting_ts else frappe.utils.now_datetime()
    doc = build_return_against(original, items, posting)
    _set_reason(doc, reason_option, reason_text, note)
    doc.custom_client_id = client_id

    doc.insert(ignore_permissions=False)
    refund_entry = None
    if submit:
        doc.submit()
        refund_entry = refund_credit_note(doc, refund)

    _record_outbox(client_id, doc.name, posting_ts, {
        "original_invoice": original_invoice,
        "items": items,
        "reason": reason,
        "note": note,
    })
    frappe.db.commit()

    return {
        "name": doc.name,
        "grand_total": float(doc.grand_total or 0),
        "status": doc.status,
        "modified": naive_site_to_utc_iso(doc.modified),
        "idempotent_replay": False,
    }


ZATCA_REFERENCES_FIELD = "custom_return_against_additional_references"


def _last_invoices_selling(customer: str, item_codes: list[str]) -> dict[str, str]:
    """item_code → the customer's most recent submitted (non-return) invoice that sold it."""
    rows = frappe.db.sql(
        """
        SELECT sii.item_code, si.name
        FROM `tabSales Invoice Item` sii
        JOIN `tabSales Invoice` si ON si.name = sii.parent
        WHERE si.customer = %(customer)s AND si.docstatus = 1 AND si.is_return = 0
          AND sii.item_code IN %(items)s
        ORDER BY si.posting_date DESC, si.creation DESC
        """,
        {"customer": customer, "items": tuple(item_codes)},
    )
    found: dict[str, str] = {}
    for item_code, invoice in rows:
        found.setdefault(item_code, invoice)
    return found


def _bulk_lines(items) -> list[dict]:
    return [i for i in (items or []) if i.get("item_code") and flt(i.get("qty")) > 0]


def _check_references(customer: str, references: list[str]) -> list[str]:
    """User-chosen ZATCA references: the customer's own submitted sales."""
    refs = sorted({r for r in references if r})
    if not refs:
        frappe.throw(_("Choose at least one original invoice (ZATCA needs a reference)"))
    valid = set(
        frappe.get_all(
            "Sales Invoice",
            filters={"name": ["in", refs], "customer": customer, "docstatus": 1, "is_return": 0},
            pluck="name",
        )
    )
    bad = [r for r in refs if r not in valid]
    if bad:
        frappe.throw(_("Not a submitted invoice of this customer: {0}").format(", ".join(bad)))
    return refs


def default_references(customer: str, item_codes: list[str]) -> tuple[list[str], list[str]]:
    """(the customer's latest invoice per item, items never sold to the customer)."""
    if not item_codes:
        return [], []
    last = _last_invoices_selling(customer, sorted(set(item_codes)))
    return sorted(set(last.values())), sorted(set(item_codes) - set(last))


def build_bulk_return(customer: str, items: list[dict[str, Any]], references: Optional[list[str]] = None,
                      posting=None, preview: bool = False):
    """Unsaved credit note without an original invoice (shared by save + preview).

    Lines priced like a sale unless a rate is given; stock into the van
    warehouse. ZATCA references (ksa_compliance field) are chosen by the user
    and required. `preview` skips the reference checks.
    """
    from vansale.api.invoice import (
        _apply_template_taxes,
        _get_default_warehouse,
        _resolve_tax_template,
        _user_company,
    )
    from vansale.api.item import _customer_price_list, _fetch_price, _item_uoms, check_item_allowed
    from vansale.api.me import current_user_sales_person

    lines = _bulk_lines(items)
    if not lines and not preview:
        frappe.throw(_("Enter a return qty for at least one item"))
    check_read("Customer", customer)
    for code in {i["item_code"] for i in lines}:
        check_item_allowed(code)

    # ZATCA references: always chosen by the user (no default).
    refs: list[str] = []
    if not preview and frappe.get_meta("Sales Invoice").has_field(ZATCA_REFERENCES_FIELD):
        refs = _check_references(customer, references or [])

    company = _user_company()
    warehouse = _get_default_warehouse(company)
    posting = posting or frappe.utils.now_datetime()
    doc = frappe.new_doc("Sales Invoice")
    doc.customer = customer
    doc.company = company
    doc.is_return = 1
    doc.update_stock = 1
    doc.set_warehouse = warehouse
    doc.set_posting_time = 1
    doc.posting_date = posting.date()
    doc.posting_time = posting.strftime("%H:%M:%S")
    doc.taxes_and_charges = _resolve_tax_template(customer, company, doc.posting_date)

    price_list = _customer_price_list(customer)
    for line in lines:
        item = frappe.get_doc("Item", line["item_code"])
        uoms = dict(_item_uoms(item))
        uom = line.get("uom") or item.stock_uom
        if uom not in uoms:
            frappe.throw(_("UOM {0} is not set on item {1}").format(uom, item.name))
        conversion_factor = uoms[uom]
        if line.get("rate") not in (None, ""):
            rate = flt(line["rate"])
        else:
            rate, _customer_specific = _fetch_price(item.name, price_list, uom, item.stock_uom, conversion_factor, customer)
        doc.append("items", {
            "item_code": item.name,
            "qty": -abs(flt(line["qty"])),
            "uom": uom,
            "conversion_factor": conversion_factor,
            "rate": rate,
            "price_list_rate": rate,
            "warehouse": warehouse,
        })
    _apply_template_taxes(doc)
    for invoice in refs:
        doc.append(ZATCA_REFERENCES_FIELD, {"sales_invoice": invoice})
    sp = current_user_sales_person()
    if sp:
        doc.append("sales_team", {"sales_person": sp, "allocated_percentage": 100})
    return doc


@frappe.whitelist(methods=["POST"])
def save_without_invoice(
    client_id: str,
    customer: str,
    items: list[dict[str, Any]],
    reason: Optional[str] = None,
    note: Optional[str] = None,
    posting_ts: Optional[str] = None,
    submit: int = 1,
    references: Optional[list[str]] = None,
    refund: Optional[dict] = None,
) -> dict:
    """Bulk return: credit note for returned goods without one original
    invoice, when the "Return without invoice" setting allows it. See
    `build_bulk_return` for pricing, warehouse and ZATCA references."""
    from vansale.api.me import return_without_invoice_allowed

    if not return_without_invoice_allowed():
        frappe.throw(_("Bulk returns are not enabled for your van"))
    if not client_id:
        frappe.throw(_("client_id is required"))
    if not customer:
        frappe.throw(_("Customer is required"))
    reason_option, reason_text = resolve_return_reason(reason)

    existing = claim(client_id, "return", "Sales Invoice")
    if existing:
        doc = frappe.get_doc("Sales Invoice", existing)
        return {"name": doc.name, "grand_total": float(doc.grand_total or 0), "status": doc.status,
                "idempotent_replay": True}

    posting = parse_client_ts(posting_ts) if posting_ts else frappe.utils.now_datetime()
    doc = build_bulk_return(customer, items, references, posting)
    _set_reason(doc, reason_option, reason_text, note)
    doc.custom_client_id = client_id
    doc.insert(ignore_permissions=False)
    refund_entry = None
    if submit:
        doc.submit()
        refund_entry = refund_credit_note(doc, refund)

    refs = [r.sales_invoice for r in doc.get(ZATCA_REFERENCES_FIELD) or []]
    _record_outbox(client_id, doc.name, posting_ts, {
        "customer": customer,
        "items": items,
        "reason": reason,
        "references": refs,
    })
    frappe.db.commit()
    return {
        "name": doc.name,
        "grand_total": float(doc.grand_total or 0),
        "status": doc.status,
        "docstatus": int(doc.docstatus or 0),
        "references": refs,
        "refund_entry": refund_entry,
        "modified": naive_site_to_utc_iso(doc.modified),
        "idempotent_replay": False,
    }


@frappe.whitelist(methods=["GET"])
def reference_options(customer: str, items: Optional[str] = None) -> dict:
    """For the bulk-return screen: whether ZATCA references apply, the default
    references for the chosen items, items never sold to the customer, and the
    customer's recent invoices to pick from."""
    check_read("Customer", customer)
    if not frappe.get_meta("Sales Invoice").has_field(ZATCA_REFERENCES_FIELD):
        return {"enabled": False, "defaults": [], "never_sold": [], "invoices": []}
    item_codes = frappe.parse_json(items) if items else []
    defaults, never_sold = default_references(customer, item_codes)
    invoices = frappe.get_all(
        "Sales Invoice",
        filters={"customer": customer, "docstatus": 1, "is_return": 0},
        fields=["name", "posting_date", "grand_total"],
        order_by="posting_date desc, creation desc",
        limit=50,
    )
    for inv in invoices:
        inv["posting_date"] = str(inv["posting_date"])
    return {"enabled": True, "defaults": defaults, "never_sold": never_sold, "invoices": invoices}


@frappe.whitelist(methods=["POST"])
def preview(
    items: list[dict[str, Any]],
    original_invoice: Optional[str] = None,
    customer: Optional[str] = None,
) -> dict:
    """Totals of a return before saving it — net, VAT and total as ERPNext
    will post them (the document is built and calculated, never saved)."""
    if not _bulk_lines(items):
        return {"net_total": 0.0, "tax": 0.0, "grand_total": 0.0, "refundable": False}
    if original_invoice:
        doc = build_return_against(readable_doc("Sales Invoice", original_invoice), items)
    elif customer:
        doc = build_bulk_return(customer, items, preview=True)
    else:
        frappe.throw(_("Customer or original invoice required"))
    if not doc.get("items"):
        return {"net_total": 0.0, "tax": 0.0, "grand_total": 0.0, "refundable": False}
    doc.set_missing_values()
    doc.calculate_taxes_and_totals()
    # Refund possible when the credit keeps its own balance: always for a
    # bulk return, for an invoice return only if the invoice was (mostly) paid.
    refundable = not original_invoice or bool(doc.update_outstanding_for_self)
    return {
        "net_total": abs(flt(doc.net_total)),
        "tax": abs(flt(doc.total_taxes_and_charges)),
        "grand_total": abs(flt(doc.rounded_total) or flt(doc.grand_total)),
        "refundable": refundable,
        "original_outstanding": (
            flt(frappe.db.get_value("Sales Invoice", original_invoice, "outstanding_amount"))
            if original_invoice else None
        ),
    }


@frappe.whitelist(methods=["GET"])
def list_mine(limit: int = 50) -> list[dict]:
    rows = frappe.get_all(
        "Sales Invoice",
        filters={"is_return": 1, "docstatus": 1, "owner": frappe.session.user},
        fields=["name", "customer", "return_against", "grand_total", "posting_date", "modified"],
        order_by="posting_date desc",
        limit=int(limit),
    )
    for r in rows:
        r["modified"] = naive_site_to_utc_iso(r.get("modified"))
    return rows
