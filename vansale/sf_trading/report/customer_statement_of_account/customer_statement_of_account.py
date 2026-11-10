# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Customer Statement of Account — the ledger Steel Force sends to a customer.

One row per receivable movement in the period with a running balance, closed by
an ageing band. Every figure is ERPNext's own: the movements come from the
General Ledger report and the ageing from the Accounts Receivable report — the
same pair `Process Statement Of Accounts` combines — so a printed statement
always reconciles with the party ledger and with the AR report. This module
only reshapes those rows for the statement layout and looks up the document
fields the layout prints (due date, LPO, cheque no, branch).
"""

import frappe
from frappe import _
from frappe.utils import cstr, flt, getdate

from erpnext import get_company_currency
from erpnext.accounts.party import get_party_account_currency
from erpnext.accounts.report.accounts_receivable.accounts_receivable import execute as get_ar_data
from erpnext.accounts.report.general_ledger.general_ledger import execute as get_gl_data

# Two-letter codes printed in the Type column, matching the legend on the
# statement: PY - Payment, IN - Invoice, CR - Credit, DB - Debit Note,
# TR - Return, AD - Financial Adjustment.
TYPE_CODES = {
    "Sales Invoice": "IN",
    "Payment Entry": "PY",
    "Journal Entry": "AD",
    "Delivery Note": "DN",
    "Dunning": "AD",
}

# A Journal Entry says what it is in its own voucher_type.
JOURNAL_TYPE_CODES = {
    "Credit Note": "CR",
    "Debit Note": "DB",
    "Bank Entry": "PY",
    "Cash Entry": "PY",
    "Contra Entry": "PY",
    "Write Off Entry": "AD",
    "Exchange Rate Revaluation": "AD",
}

DEFAULT_RANGES = [30, 60, 90, 120, 180, 360]

# `in` lists are chunked so a long statement can't build a query MariaDB refuses.
CHUNK = 500


def execute(filters=None):
    filters = frappe._dict(filters or {})
    validate_filters(filters)

    currency = get_statement_currency(filters)
    entries, opening, total, closing = get_ledger(filters, currency)
    ranges = get_ranges(filters)
    labels = get_range_labels(ranges)
    buckets = get_ageing(filters, ranges)

    data = build_statement(filters, currency, entries, opening, total, closing, labels, buckets)
    columns = get_columns(filters, currency)
    summary = get_report_summary(labels, buckets, currency)

    return columns, data, None, None, summary


def validate_filters(filters):
    for fieldname, label in (
        ("company", _("Company")),
        ("customer", _("Customer")),
        ("from_date", _("From Date")),
        ("to_date", _("To Date")),
    ):
        if not filters.get(fieldname):
            frappe.throw(_("{0} is mandatory").format(frappe.bold(label)))

    if getdate(filters.from_date) > getdate(filters.to_date):
        frappe.throw(_("From Date cannot be after To Date"))


def get_statement_currency(filters):
    """Print in the party account's currency, falling back to the company's."""
    return (
        filters.get("presentation_currency")
        or get_party_account_currency("Customer", filters.customer, filters.company)
        or get_company_currency(filters.company)
    )


def get_ledger(filters, currency):
    """Run ERPNext's General Ledger for this customer and split off its marker rows.

    General Ledger returns the movements framed by an Opening row, a Total row
    and a Closing row. Those three carry the balances the statement footer
    prints, so they are pulled out by their label rather than by position.
    """
    gl_filters = frappe._dict(
        {
            "company": filters.company,
            "from_date": filters.from_date,
            "to_date": filters.to_date,
            "party_type": "Customer",
            "party": [filters.customer],
            "presentation_currency": currency,
            "account": [filters.account] if filters.get("account") else None,
            "cost_center": filters.get("cost_center") or [],
            "project": [],
            "finance_book": filters.get("finance_book"),
            "categorize_by": "",
            "show_opening_entries": 0,
            "include_default_book_entries": 0,
            "show_remarks": 1,
            "ignore_err": 1 if filters.get("ignore_exchange_rate_revaluation_journals") else 0,
            "ignore_cr_dr_notes": 0,
        }
    )

    rows = get_gl_data(gl_filters)[1] or []
    entries = [row for row in rows if row.get("voucher_no")]

    def marker(label):
        # General Ledger writes its marker rows as account="'Opening'" etc.
        return next((row for row in rows if cstr(row.get("account")).strip("'") == label), None)

    return (
        entries,
        marker(_("Opening")),
        marker(_("Total")),
        marker(_("Closing (Opening + Total)")),
    )


def get_ranges(filters):
    """Ageing buckets, ascending, blanks falling back to the statement defaults."""
    ranges = []
    for index, default in enumerate(DEFAULT_RANGES, start=1):
        ranges.append(int(flt(filters.get("range" + str(index))) or default))

    return sorted(set(ranges))


def get_range_labels(ranges):
    labels = []
    lower = 0
    for limit in ranges:
        labels.append("{0}-{1} ".format(lower, limit) + _("Days"))
        lower = limit + 1

    labels.append(_("Above {0} Days").format(ranges[-1]))
    return labels


def get_ageing(filters, ranges):
    """Outstanding per bucket, aged by ERPNext's own Accounts Receivable report."""
    ar_filters = frappe._dict(
        {
            "company": filters.company,
            "report_date": filters.to_date,
            "ageing_based_on": filters.get("ageing_based_on") or "Due Date",
            "party_type": "Customer",
            "party": [filters.customer],
            "report_name": "Accounts Receivable",
            # The AR report ages into its own five columns; the statement re-buckets
            # by each row's `age`, so these only have to be valid.
            "range1": 30,
            "range2": 60,
            "range3": 90,
            "range4": 120,
        }
    )

    buckets = [0.0] * (len(ranges) + 1)
    for row in get_ar_data(ar_filters)[1] or []:
        if not row.get("voucher_no"):
            continue

        buckets[get_bucket_index(flt(row.get("age")), ranges)] += flt(row.get("outstanding"))

    return buckets


def get_bucket_index(age, ranges):
    for index, limit in enumerate(ranges):
        if age <= limit:
            return index

    return len(ranges)


def build_statement(filters, currency, entries, opening, total, closing, labels, buckets):
    details = get_voucher_details(entries)
    allocations = get_payment_allocations(entries)

    opening_balance = get_balance(opening)
    data = [
        {
            "row_type": "opening",
            "posting_date": filters.from_date,
            "remarks": _("Opening Balance"),
            "debit": 0.0,
            "credit": 0.0,
            "balance": opening_balance,
            "currency": currency,
        }
    ]

    debit_total = credit_total = 0.0
    for row in entries:
        voucher = details.get((row.get("voucher_type"), row.get("voucher_no"))) or frappe._dict()
        debit_total += flt(row.get("debit"))
        credit_total += flt(row.get("credit"))

        data.append(
            {
                "row_type": "entry",
                "posting_date": row.get("posting_date"),
                "document_date": voucher.get("document_date") or row.get("posting_date"),
                "due_date": voucher.get("due_date") or row.get("posting_date"),
                "branch": voucher.get("branch"),
                "voucher_type": row.get("voucher_type"),
                "voucher_no": row.get("voucher_no"),
                "type_code": get_type_code(row.get("voucher_type"), voucher),
                "allocations": allocations.get(row.get("voucher_no")),
                "cheque_no": voucher.get("cheque_no"),
                "reference_no": voucher.get("reference_no"),
                "reference_date": voucher.get("reference_date"),
                "remarks": row.get("remarks"),
                "debit": flt(row.get("debit")),
                "credit": flt(row.get("credit")),
                "balance": flt(row.get("balance")),
                "currency": currency,
            }
        )

    # Prefer General Ledger's own totals; fall back to the sum of what is printed
    # so the footer can never disagree with the rows above it.
    data.append(
        {
            "row_type": "total",
            "remarks": _("Total"),
            "debit": flt(total.get("debit")) if total else debit_total,
            "credit": flt(total.get("credit")) if total else credit_total,
            "balance": get_balance(closing) if closing else opening_balance + debit_total - credit_total,
            "currency": currency,
            "opening_balance": opening_balance,
            "ageing_labels": labels,
            "ageing_values": buckets,
        }
    )

    return data


def get_balance(row):
    if not row:
        return 0.0

    if row.get("balance") is not None:
        return flt(row.get("balance"))

    return flt(row.get("debit")) - flt(row.get("credit"))


def get_type_code(voucher_type, voucher):
    if voucher_type == "Sales Invoice":
        if voucher.get("is_return"):
            return "CR"
        if voucher.get("is_debit_note"):
            return "DB"
        return "IN"

    if voucher_type == "Journal Entry":
        return JOURNAL_TYPE_CODES.get(voucher.get("journal_type"), "AD")

    return TYPE_CODES.get(voucher_type) or cstr(voucher_type)[:2].upper()


def get_voucher_details(entries):
    """Fetch, in one query per doctype, the fields the statement layout prints."""
    names = {}
    for row in entries:
        names.setdefault(row.get("voucher_type"), set()).add(row.get("voucher_no"))

    details = {}

    for row in fetch(
        "Sales Invoice",
        names.get("Sales Invoice"),
        ["name", "posting_date", "due_date", "po_no", "po_date", "branch", "is_return", "is_debit_note"],
    ):
        details[("Sales Invoice", row.name)] = frappe._dict(
            document_date=row.posting_date,
            due_date=row.due_date,
            branch=row.branch,
            reference_no=row.po_no,
            reference_date=row.po_date,
            is_return=row.is_return,
            is_debit_note=row.is_debit_note,
        )

    for row in fetch(
        "Payment Entry",
        names.get("Payment Entry"),
        ["name", "posting_date", "reference_no", "reference_date", "branch", "mode_of_payment"],
    ):
        details[("Payment Entry", row.name)] = frappe._dict(
            document_date=row.posting_date,
            due_date=row.posting_date,
            branch=row.branch,
            cheque_no=row.reference_no,
            reference_date=row.reference_date,
        )

    for row in fetch(
        "Journal Entry",
        names.get("Journal Entry"),
        ["name", "posting_date", "voucher_type", "cheque_no", "cheque_date", "bill_no", "due_date"],
    ):
        details[("Journal Entry", row.name)] = frappe._dict(
            document_date=row.posting_date,
            due_date=row.due_date or row.posting_date,
            cheque_no=row.cheque_no,
            reference_no=row.bill_no,
            reference_date=row.cheque_date,
            journal_type=row.voucher_type,
        )

    return details


def get_payment_allocations(entries):
    """How many invoices each payment settles — blank on an on-account payment."""
    names = sorted({row.get("voucher_no") for row in entries if row.get("voucher_type") == "Payment Entry"})

    allocations = {}
    for batch in chunks(names):
        for row in frappe.get_all(
            "Payment Entry Reference",
            parent_doctype="Payment Entry",
            filters={"parent": ["in", batch], "docstatus": 1},
            fields=["parent", "count(name) as allocations"],
            group_by="parent",
        ):
            allocations[row.parent] = row.allocations

    return allocations


def fetch(doctype, names, fields):
    rows = []
    for batch in chunks(sorted(names or [])):
        rows.extend(frappe.get_all(doctype, filters={"name": ["in", batch]}, fields=fields))

    return rows


def chunks(names):
    for start in range(0, len(names), CHUNK):
        yield names[start : start + CHUNK]


def get_report_summary(labels, buckets, currency):
    summary = [
        {"label": label, "value": value, "datatype": "Currency", "currency": currency}
        for label, value in zip(labels, buckets, strict=True)
        if value
    ]

    summary.append(
        {
            "label": _("Total Outstanding"),
            "value": sum(buckets),
            "datatype": "Currency",
            "currency": currency,
            "indicator": "orange",
        }
    )

    return summary


def get_columns(filters, currency):
    return [
        {"label": _("Date"), "fieldname": "posting_date", "fieldtype": "Date", "width": 95},
        {"label": _("Doc. Date"), "fieldname": "document_date", "fieldtype": "Date", "width": 95},
        {"label": _("Due Date"), "fieldname": "due_date", "fieldtype": "Date", "width": 95},
        {"label": _("Branch"), "fieldname": "branch", "fieldtype": "Data", "width": 70},
        {
            "label": _("Document No"),
            "fieldname": "voucher_no",
            "fieldtype": "Dynamic Link",
            "options": "voucher_type",
            "width": 150,
        },
        {"label": _("Type"), "fieldname": "type_code", "fieldtype": "Data", "width": 60},
        {"label": _("Inv."), "fieldname": "allocations", "fieldtype": "Int", "width": 55},
        {"label": _("Cheque No"), "fieldname": "cheque_no", "fieldtype": "Data", "width": 110},
        {"label": _("Reference"), "fieldname": "reference_no", "fieldtype": "Data", "width": 120},
        {"label": _("Ref. Date"), "fieldname": "reference_date", "fieldtype": "Date", "width": 95},
        {
            "label": _("Debit ({0})").format(currency),
            "fieldname": "debit",
            "fieldtype": "Currency",
            "options": "currency",
            "width": 120,
        },
        {
            "label": _("Credit ({0})").format(currency),
            "fieldname": "credit",
            "fieldtype": "Currency",
            "options": "currency",
            "width": 120,
        },
        {
            "label": _("Balance ({0})").format(currency),
            "fieldname": "balance",
            "fieldtype": "Currency",
            "options": "currency",
            "width": 130,
        },
        {"label": _("Remarks"), "fieldname": "remarks", "fieldtype": "Data", "width": 220},
        {"label": _("Voucher Type"), "fieldname": "voucher_type", "fieldtype": "Data", "hidden": 1},
    ]
