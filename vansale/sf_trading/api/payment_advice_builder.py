# apps/vansale/vansale/sf_trading/api/payment_advice_builder.py
"""Supplier-wise Payment Advice generator.

One filtered sweep of outstanding vouchers, grouped by party, turned into **one Payment
Advice per party**. This is the piece ERPNext's Payment Request cannot do: a PR is
one-document-per-request, so "pay these nine invoices for this supplier" has no home.

Both entry points share this module, and so will the automation in Phase 3 — the scheduler
calls `create_advices()` with the same payload the builder page sends, so automatic and
manual runs cannot drift apart:

  * the Payment Advice Builder desk page (preview, tick, create)
  * the Purchase Invoice list bulk action

Outstanding amounts come from `shape_reference_rows()`, which wraps ERPNext's own Payment
Entry engine — Payment-Ledger truthful, so part payments, credit notes and return invoices
are already netted.

Nothing here submits anything. Advices are created as drafts unless the caller explicitly
asks to submit, and submission still obeys the advice's approver rule.
"""

import json

import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, getdate, nowdate

from vansale.sf_trading.doctype.payment_advice.payment_advice import (
    PARTY_TYPES,
    PAY_PARTY_TYPES,
    RECEIVE_PARTY_TYPES,
    get_party_account,
    get_reference_amounts,
    shape_reference_rows,
)

# which side of the ledger a list-view action belongs to
SUPPLIER_DOCTYPES = ("Purchase Invoice", "Purchase Order")
CUSTOMER_DOCTYPES = ("Sales Invoice", "Sales Order")

# Skip reasons, kept as constants so the page and the tests speak the same language.
SKIP_NO_PARTY_ACCOUNT = "no_party_account"
SKIP_ALREADY_ADVISED = "already_advised"
SKIP_BELOW_FLOOR = "below_floor"
SKIP_ON_HOLD = "supplier_on_hold"
SKIP_DISABLED = "supplier_disabled"
SKIP_NO_ROWS = "nothing_outstanding"

SKIP_LABELS = {
    SKIP_NO_PARTY_ACCOUNT: _("No default payable/receivable account"),
    SKIP_ALREADY_ADVISED: _("Already allocated on a live Payment Advice"),
    SKIP_BELOW_FLOOR: _("Below the minimum advice total"),
    SKIP_ON_HOLD: _("Party is on hold"),
    SKIP_DISABLED: _("Party is disabled"),
    SKIP_NO_ROWS: _("Nothing outstanding after filters"),
}

# Anything at or below this is rounding residue, not a payable. ERPNext will happily return
# a 0.005 outstanding row; raising an advice for half a fils is noise.
DEFAULT_FLOOR = 1.0

ENQUEUE_THRESHOLD = 15  # parties per run before we push the work to a background job


# ── party discovery ──────────────────────────────────────────────────────────────

def _party_field(party_type):
    return {"Supplier": "supplier", "Customer": "customer"}.get(party_type, "supplier")


def _source_doctype(party_type):
    return "Purchase Invoice" if party_type in PAY_PARTY_TYPES else "Sales Invoice"


def _candidate_parties(filters):
    """Parties with something outstanding under the given filters."""
    party_type = filters.get("party_type") or "Supplier"
    doctype = _source_doctype(party_type)
    party_field = _party_field(party_type)

    conditions = {
        "docstatus": 1,
        "company": filters.get("company"),
        "outstanding_amount": [">", 0],
    }

    if filters.get("party"):
        conditions[party_field] = filters.get("party")
    if filters.get("branch"):
        conditions["branch"] = filters.get("branch")
    if filters.get("cost_center"):
        conditions["cost_center"] = filters.get("cost_center")
    if filters.get("currency"):
        conditions["currency"] = filters.get("currency")

    due_before = filters.get("due_before")
    if due_before:
        conditions["due_date"] = ["<=", getdate(due_before)]

    if filters.get("from_posting_date") and filters.get("to_posting_date"):
        conditions["posting_date"] = [
            "between",
            [getdate(filters["from_posting_date"]), getdate(filters["to_posting_date"])],
        ]

    parties = frappe.get_all(
        doctype,
        filters=conditions,
        group_by=party_field,
        order_by=party_field,
        pluck=party_field,
    )

    if filters.get("party_group"):
        group_field = "supplier_group" if party_type == "Supplier" else "customer_group"
        in_group = frappe.get_all(
            party_type,
            filters={group_field: filters["party_group"], "name": ["in", parties]},
            pluck="name",
        )
        parties = [p for p in parties if p in in_group]

    return parties


def _party_state(party_type, party):
    """Hold / disabled state, so the preview can explain a skip instead of hiding it."""
    state = frappe._dict(on_hold=False, disabled=False, release_date=None)

    if party_type == "Supplier":
        values = frappe.db.get_value(
            "Supplier", party, ["on_hold", "hold_type", "release_date", "disabled"], as_dict=True
        ) or frappe._dict()
        release = values.get("release_date")
        # ERPNext holds a supplier until release_date; a past release date is not a hold
        holding = cint(values.get("on_hold")) and (
            not release or getdate(release) >= getdate(nowdate())
        )
        state.on_hold = bool(holding) and values.get("hold_type") in (None, "", "All", "Payments")
        state.disabled = bool(cint(values.get("disabled")))
        state.release_date = release
    elif party_type == "Customer":
        state.disabled = bool(cint(frappe.db.get_value("Customer", party, "disabled")))

    return state


def _already_advised(records):
    """Vouchers already carrying an allocation on a live (non-cancelled) advice."""
    if not records:
        return set()

    rows = frappe.get_all(
        "Payment Advice Reference",
        filters={
            "reference_record": ["in", records],
            "parenttype": "Payment Advice",
            "docstatus": ["!=", 2],
            "allocated_amount": [">", 0],
        },
        fields=["reference_record", "parent"],
    )
    return {r.reference_record for r in rows}


# ── preview ──────────────────────────────────────────────────────────────────────

@frappe.whitelist()
def get_builder_data(filters=None):
    """Grouped preview: one entry per party, with its outstanding vouchers and skip reason."""
    frappe.has_permission("Payment Advice", "create", throw=True)

    filters = frappe._dict(_as_dict(filters))
    if not filters.get("company"):
        frappe.throw(_("Company is required."))

    party_type = filters.get("party_type") or "Supplier"
    if party_type not in PARTY_TYPES:
        frappe.throw(_("Unsupported Party Type: %s") % party_type)

    floor = flt(filters.get("minimum_total") or DEFAULT_FLOOR)
    min_ageing = cint(filters.get("min_ageing"))

    groups = []
    for party in _candidate_parties(filters):
        group = _build_group(party_type, party, filters, floor, min_ageing)
        if group:
            groups.append(group)

    groups.sort(key=lambda g: -flt(g["total_outstanding"]))
    return {
        "party_type": party_type,
        "company": filters.get("company"),
        "currency": frappe.db.get_value("Company", filters.get("company"), "default_currency"),
        "floor": floor,
        "groups": groups,
        "totals": {
            "parties": len([g for g in groups if not g["skip"]]),
            "vouchers": sum(len(g["rows"]) for g in groups if not g["skip"]),
            "outstanding": flt(
                sum(flt(g["total_outstanding"]) for g in groups if not g["skip"]), 3
            ),
            "skipped": len([g for g in groups if g["skip"]]),
        },
        "skip_labels": SKIP_LABELS,
    }


def _build_group(party_type, party, filters, floor, min_ageing):
    state = _party_state(party_type, party)
    party_account = get_party_account(party_type, party, filters.get("company"))

    rows = _outstanding_rows(party_type, party, filters, party_account, min_ageing)
    advised = _already_advised([r["reference_record"] for r in rows])

    fresh = [r for r in rows if r["reference_record"] not in advised]
    total = flt(sum(flt(r["net_payable_amount"]) for r in fresh), 3)

    skip = None
    if not party_account:
        skip = SKIP_NO_PARTY_ACCOUNT
    elif state.disabled:
        skip = SKIP_DISABLED
    elif state.on_hold and not cint(filters.get("ignore_on_hold")):
        skip = SKIP_ON_HOLD
    elif not fresh:
        skip = SKIP_ALREADY_ADVISED if rows else SKIP_NO_ROWS
    elif total < floor:
        skip = SKIP_BELOW_FLOOR

    return {
        "party": party,
        "party_name": frappe.db.get_value(
            party_type, party, "supplier_name" if party_type == "Supplier" else "customer_name"
        )
        or party,
        "party_account": party_account,
        "bank_account": _party_bank_account(party_type, party),
        "rows": fresh,
        "already_advised": sorted(advised),
        "voucher_count": len(fresh),
        "total_outstanding": total,
        "oldest_ageing": max([cint(r["ageing"]) for r in fresh], default=0),
        "currencies": sorted({r["currency"] for r in fresh if r.get("currency")}),
        "on_hold": state.on_hold,
        "release_date": state.release_date,
        "skip": skip,
        "skip_label": SKIP_LABELS.get(skip) if skip else None,
    }


def _outstanding_rows(party_type, party, filters, party_account, min_ageing):
    """Outstanding vouchers for one party, via ERPNext's Payment Entry engine."""
    if not party_account:
        return []

    from erpnext.accounts.doctype.payment_entry.payment_entry import (
        get_outstanding_reference_documents,
    )

    args = {
        "company": filters.get("company"),
        "party_type": party_type,
        "party": party,
        "party_account": party_account,
        "payment_type": "Pay" if party_type in PAY_PARTY_TYPES else "Receive",
        "posting_date": nowdate(),
        "get_outstanding_invoices": True,
        "get_orders_to_be_billed": cint(filters.get("include_orders")),
        "cost_center": filters.get("cost_center"),
        "to_due_date": getdate(filters["due_before"]) if filters.get("due_before") else None,
        "from_posting_date": filters.get("from_posting_date"),
        "to_posting_date": filters.get("to_posting_date"),
    }

    try:
        vouchers = get_outstanding_reference_documents(args) or []
    except Exception:
        # a party-level problem (blocked supplier, missing account currency) must not kill
        # the whole sweep — the group simply reports nothing outstanding
        frappe.log_error(frappe.get_traceback(), "sf_trading: outstanding fetch failed for %s" % party)
        return []

    rows = shape_reference_rows(
        vouchers,
        cost_center=filters.get("cost_center"),
        from_amount=filters.get("from_amount"),
        to_amount=filters.get("to_amount"),
        company=filters.get("company"),
    )

    if min_ageing:
        rows = [r for r in rows if cint(r["ageing"]) >= min_ageing]

    return rows


def _party_bank_account(party_type, party):
    return frappe.db.get_value(
        "Bank Account", {"party_type": party_type, "party": party, "is_default": 1}, "name"
    ) or frappe.db.get_value("Bank Account", {"party_type": party_type, "party": party}, "name")


# ── creation ─────────────────────────────────────────────────────────────────────

@frappe.whitelist()
def create_advices(selections, options=None):
    """Create one Payment Advice per selected party.

    `selections` is a list of {party, references: [...], payment_amount?} — exactly the shape
    `get_builder_data()` returns, so the page can hand back what it was given after the user
    ticks rows. Large batches are pushed to a background job.
    """
    frappe.has_permission("Payment Advice", "create", throw=True)

    selections = _as_list(selections)
    options = frappe._dict(_as_dict(options))

    if not selections:
        frappe.throw(_("Select at least one party."))

    if len(selections) > ENQUEUE_THRESHOLD and not options.get("run_now"):
        job = frappe.enqueue(
            "vansale.sf_trading.api.payment_advice_builder.create_advices_bulk",
            queue="long",
            timeout=1800,
            enqueue_after_commit=True,
            job_name="payment_advice_builder_%s" % frappe.session.user,
            selections=selections,
            options=dict(options),
            user=frappe.session.user,
        )
        return {
            "queued": True,
            "job": getattr(job, "id", None),
            "parties": len(selections),
            "message": _("Creating %s advices in the background. You will be notified when it finishes.")
            % len(selections),
        }

    return _create_many(selections, options)


def create_advices_bulk(selections, options=None, user=None):
    """Background entry point — same work, then tell the user it landed."""
    result = _create_many(_as_list(selections), frappe._dict(_as_dict(options)))

    if user:
        created = len(result["created"])
        frappe.publish_realtime(
            event="sf_invoice_overdue_alert",  # reuses the live chime + toast + bell channel
            message={
                "title": _("Payment Advices created"),
                "message": _("%(count)s advice(s) created, %(total)s total")
                % {
                    "count": created,
                    "total": frappe.utils.fmt_money(result["total_amount"], precision=3),
                },
                "count": created,
                "outstanding": result["total_amount"],
                "report": "Payment Advice",
            },
            user=user,
            after_commit=True,
        )
    return result


def _create_many(selections, options):
    created, failed = [], []
    total = 0.0

    for selection in selections:
        selection = frappe._dict(selection)
        try:
            advice = _create_one(selection, options)
            created.append({"advice": advice.name, "party": advice.party, "amount": flt(advice.payment_amount)})
            total += flt(advice.payment_amount)
        except Exception as exc:
            frappe.db.rollback()
            failed.append({"party": selection.get("party"), "error": str(exc)})
            frappe.log_error(frappe.get_traceback(), "sf_trading: advice creation failed")
        else:
            frappe.db.commit()

    return {
        "queued": False,
        "created": created,
        "failed": failed,
        "total_amount": flt(total, 3),
    }


def _create_one(selection, options):
    """Build and insert a single Payment Advice from one party's selected references."""
    references = _as_list(selection.get("references"))
    if not references:
        frappe.throw(_("No references selected for %s") % selection.get("party"))

    party_type = options.get("party_type") or "Supplier"
    company = options.get("company")

    advice = frappe.new_doc("Payment Advice")
    advice.update(
        {
            "company": company,
            "payment_advice_type": "Outward" if party_type in PAY_PARTY_TYPES else "Inward",
            "transaction_date": options.get("transaction_date") or nowdate(),
            "party_type": party_type,
            "party": selection.get("party"),
            "mode_of_payment": options.get("mode_of_payment"),
            "bank_account": options.get("bank_account") or selection.get("bank_account"),
            "cost_center": options.get("cost_center"),
            "project": options.get("project"),
            "approver": options.get("approver"),
            "remarks": options.get("remarks"),
            "auto_generated": cint(options.get("auto_generated")),
        }
    )

    for row in references:
        row = frappe._dict(row)
        advice.append(
            "payment_advice_reference",
            {
                "reference_doctype": row.get("reference_doctype"),
                "reference_record": row.get("reference_record"),
                "bill_no": row.get("bill_no"),
                "date": row.get("date"),
                "amount": flt(row.get("amount")),
                "settled_amount": flt(row.get("settled_amount")),
                "net_payable_amount": flt(row.get("net_payable_amount")),
                "payment_term": row.get("payment_term"),
                "currency": row.get("currency"),
                "exchange_rate": flt(row.get("exchange_rate")) or 1.0,
                "cost_center": row.get("cost_center") or options.get("cost_center"),
            },
        )

    payable = flt(sum(flt(r.net_payable_amount) for r in advice.payment_advice_reference), 3)
    requested = flt(selection.get("payment_amount"))
    advice.payment_amount = min(requested, payable) if requested else payable

    advice.insert()

    if cint(options.get("submit")):
        advice.submit()

    return advice


# ── Purchase Invoice list bulk action ────────────────────────────────────────────

@frappe.whitelist()
def create_advices_from_documents(documents, options=None):
    """Group hand-picked documents by their party and raise one advice each.

    Serves the list-view action on Purchase Invoice, Sales Invoice, Purchase Order and Sales
    Order. Amounts come from get_reference_amounts(), so an order nets off advance_paid and a
    foreign invoice is read in company currency — the same figures the form would produce.
    """
    frappe.has_permission("Payment Advice", "create", throw=True)

    documents = _as_list(documents)
    if not documents:
        frappe.throw(_("Select at least one document."))

    options = frappe._dict(_as_dict(options))
    doctype = options.get("doctype") or "Purchase Invoice"

    party_type = "Supplier" if doctype in SUPPLIER_DOCTYPES else "Customer"
    party_field = _party_field(party_type)
    if not frappe.get_meta(doctype).has_field(party_field):
        frappe.throw(_("%s cannot be paid through a Payment Advice.") % _(doctype))

    fields = ["name", party_field + " as party", "company", "cost_center"]
    meta = frappe.get_meta(doctype)
    for optional in ("posting_date", "transaction_date", "due_date", "schedule_date",
                     "status", "bill_no", "mode_of_payment"):
        if meta.has_field(optional):
            fields.append(optional)

    rows = frappe.get_all(doctype, filters={"name": ["in", documents], "docstatus": 1}, fields=fields)
    if not rows:
        frappe.throw(_("None of the selected documents are submitted."))

    companies = {r.company for r in rows if r.company}
    if len(companies) > 1:
        frappe.throw(_("Select documents of a single company."))

    already = _already_advised([r.name for r in rows])
    skipped_advised, skipped_nothing_due = [], []

    today = getdate(nowdate())
    grouped = {}
    for row in rows:
        if row.name in already:
            skipped_advised.append(row.name)
            continue

        total, payable = get_reference_amounts(doctype, row.name, meta)
        if payable <= 0:
            skipped_nothing_due.append(row.name)
            continue

        due = row.get("due_date") or row.get("schedule_date") or row.get("posting_date") or row.get("transaction_date")
        grouped.setdefault(row.party, []).append(
            {
                "reference_doctype": doctype,
                "reference_record": row.name,
                "bill_no": row.get("bill_no"),
                "date": row.get("posting_date") or row.get("transaction_date"),
                "amount": total,
                "settled_amount": flt(total - payable, 3),
                "net_payable_amount": payable,
                "cost_center": row.get("cost_center"),
                "reference_status": row.get("status"),
                "ageing": max(0, (today - getdate(due)).days) if due else 0,
            }
        )

    if not grouped:
        reasons = []
        if skipped_advised:
            reasons.append(_("already on a live advice: %s") % ", ".join(skipped_advised))
        if skipped_nothing_due:
            reasons.append(_("nothing left to pay: %s") % ", ".join(skipped_nothing_due))
        frappe.throw(_("No advice could be raised — %s") % "; ".join(reasons or [_("no payable documents")]))

    options.update({"company": companies.pop() if companies else options.get("company"),
                    "party_type": party_type})
    result = _create_many(
        [{"party": party, "references": refs} for party, refs in grouped.items()], options
    )
    result["skipped_already_advised"] = skipped_advised
    result["skipped_nothing_due"] = skipped_nothing_due
    return result


@frappe.whitelist()
def create_advices_from_invoices(invoices, options=None):
    """Backwards-compatible alias for the original invoice-only entry point."""
    return create_advices_from_documents(invoices, options)


# ── helpers ──────────────────────────────────────────────────────────────────────

def _as_dict(value):
    if not value:
        return {}
    if isinstance(value, str):
        return json.loads(value)
    return dict(value)


def _as_list(value):
    if not value:
        return []
    if isinstance(value, str):
        return json.loads(value)
    return list(value)


def get_due_cutoff(offset_days=0):
    """Cut-off used by both the builder default and the automation's due_date_offset."""
    return add_days(getdate(nowdate()), cint(offset_days))
