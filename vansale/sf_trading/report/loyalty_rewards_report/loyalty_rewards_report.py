# apps/vansale/vansale/sf_trading/report/loyalty_rewards_report/loyalty_rewards_report.py
"""Loyalty Rewards Report — every reward booked to the reward account, from both sides.

Steel Force does not use ERPNext's Loyalty Program (there are no Loyalty Program or
Loyalty Point Entry records). A "loyalty reward" is whatever lands on the account the
**`Loyalty Reward Entry` Journal Entry Template** posts to
(`52010300019 - Loyalty Rewards - SFB` on the live site). It gets there two ways:

* **Journal Entry** — created from the template, debiting the reward account and crediting
  petty cash / bank. The journal carries no party, so the customer is only knowable through
  the invoice named on each Accounts row (`Journal Entry Account-custom_loyalty_sales_invoice`).
  One journal may therefore reward several invoices, belonging to different customers — one
  report row per debit row, the same shape the payment side has always had. The old header
  field is read as a fallback for the journals booked before the row field existed. A debit row
  with no invoice is still listed, with blank invoice / customer columns, and the
  **Only Unlinked** filter isolates those rows so an accountant can attach the invoice by hand;
  the **Row #** column says which grid row to open.
* **Payment Entry** — the collection itself carries the reward as a row in the PE's
  **Deductions or Loss** table on that same account (the counter waives the fils-level
  remainder). Here the customer and the invoice are known exactly: the PE's party plus its
  **Payment References** allocation. One row per allocated invoice, with the allocated amount
  next to the reward. When a payment settles several invoices the reward follows the
  allocation shares and the last invoice absorbs the rounding remainder, so the rows still
  add up to the deduction.

The account list comes from the template itself, so re-pointing the template moves both
sides of the report with it. The **Source** filter isolates either side.

Two shapes, switched by the "Summarise by Customer" filter:
  * detail  — one row per reward voucher (per allocated invoice for payments)
  * summary — one row per customer: vouchers, invoices, reward split by source, invoice value, %

Reads are batched: one query for journals, one for their account rows, one joined query for
payment deductions, one for the payment allocations, one for the invoices. No per-row lookups,
no SQL strings.
"""

import frappe
from frappe import _
from frappe.query_builder import Order
from frappe.utils import flt, getdate

TEMPLATE = "Loyalty Reward Entry"
UNLINKED_LABEL = "(Not Linked)"

# the same fieldname on both doctypes, named twice so each read says which one it means
ROW_LINK_FIELD = "custom_loyalty_sales_invoice"  # Journal Entry Account — where it lives now
LEGACY_LINK_FIELD = "custom_loyalty_sales_invoice"  # Journal Entry header — pre-row journals

SOURCE_JOURNAL = "Journal Entry"
SOURCE_PAYMENT = "Payment Entry"

# BHD carries three decimals and the payment-side rewards are fractions of a fils
PRECISION = 3

EPOCH = getdate("1900-01-01")

DOCSTATUS_LABEL = {0: _("Draft"), 1: _("Submitted"), 2: _("Cancelled")}
DOCSTATUS_FILTER = {
    "Submitted": [1],
    "Draft": [0],
    "Cancelled": [2],
    "Draft + Submitted": [0, 1],
    "All": [0, 1, 2],
}


def execute(filters=None):
    filters = frappe._dict(filters or {})

    if not link_field_available():
        frappe.msgprint(
            _(
                "The <b>Loyalty Sales Invoice</b> field is not installed on the journal's "
                "Accounts table on this site yet, so reward journals are shown as unlinked "
                "unless the old header field carries a value. Run <code>bench migrate</code> "
                "to install it."
            ),
            title=_("Link field missing"),
            indicator="orange",
        )

    rows = get_data(filters)
    if filters.get("summarise_by_customer"):
        return get_summary_columns(), summarise(rows)
    return get_columns(), rows


# ── Shared helpers ────────────────────────────────────────────────────────────────

def link_field_available():
    """Is the row-level Loyalty Sales Invoice Custom Field installed on this site?

    The fixture ships with the app but only lands on `bench migrate`. Until then the
    column does not exist, so querying it would raise "Unknown column". The report stays
    usable in that state: the rows fall back to the journal header's legacy link, and
    anything without one is simply reported as unlinked.
    """
    return frappe.get_meta("Journal Entry Account").has_field(ROW_LINK_FIELD)


def legacy_link_available():
    """Is the superseded header field still on this site? It is the fallback for old journals."""
    return frappe.get_meta("Journal Entry").has_field(LEGACY_LINK_FIELD)


def _present_fields(doctype, fieldnames):
    """Only those fields the site actually has — `branch` / `epromise_vr_no` are local."""
    meta = frappe.get_meta(doctype)
    return [field for field in fieldnames if meta.has_field(field)]


def _docstatus_list(filters):
    return DOCSTATUS_FILTER.get(filters.get("status") or "Draft + Submitted", [0, 1])


def _date_range(filters):
    from_date = getdate(filters.get("from_date")) if filters.get("from_date") else None
    to_date = getdate(filters.get("to_date")) if filters.get("to_date") else None
    return from_date, to_date


def _template_accounts(template):
    """The accounts the reward template posts to — the bridge to the payment side."""
    return [
        row.account
        for row in frappe.get_all(
            "Journal Entry Template Account",
            filters={"parent": template},
            fields=["account"],
            order_by="idx asc",
        )
        if row.account
    ]


# ── Journal side ──────────────────────────────────────────────────────────────────

def _journals(filters):
    conditions = {
        "from_template": filters.get("journal_template") or TEMPLATE,
        "docstatus": ["in", _docstatus_list(filters)],
    }
    if filters.get("company"):
        conditions["company"] = filters.get("company")

    from_date, to_date = _date_range(filters)
    if from_date and to_date:
        conditions["posting_date"] = ["between", [from_date, to_date]]
    elif from_date:
        conditions["posting_date"] = [">=", from_date]
    elif to_date:
        conditions["posting_date"] = ["<=", to_date]

    # An invoice now lives on the accounts rows, which a parent filter cannot reach, so the
    # invoice and Only-Unlinked filters are applied per row after the fan-out. Narrowing the
    # journal set first is still worth it when one invoice is asked for.
    wanted_invoice = filters.get("sales_invoice")
    if wanted_invoice:
        names = set()
        if link_field_available():
            names |= set(
                frappe.get_all(
                    "Journal Entry Account",
                    filters={ROW_LINK_FIELD: wanted_invoice, "parenttype": SOURCE_JOURNAL},
                    pluck="parent",
                )
            )
        if legacy_link_available():
            names |= set(
                frappe.get_all("Journal Entry", filters={LEGACY_LINK_FIELD: wanted_invoice}, pluck="name")
            )
        if not names:
            return []
        conditions["name"] = ["in", list(names)]

    fields = ["name", "posting_date", "docstatus", "total_debit", "user_remark", "cheque_no", "company"]
    # workflow_state and epromise_vr_no are local to this site, exactly like the payment side's
    fields += _present_fields("Journal Entry", ["workflow_state", "epromise_vr_no"])
    fields += _present_fields("Journal Entry", [LEGACY_LINK_FIELD])

    return frappe.get_all(
        "Journal Entry",
        filters=conditions,
        fields=fields,
        order_by="posting_date desc, name desc",
    )


def _account_rows(journal_names):
    """Every debit row kept whole, plus the voucher's funding accounts, in one query.

    The debit rows are no longer folded into a single reward figure: each one carries its own
    amount and its own invoice, so each one becomes a report row.
    """
    detail = {}
    if not journal_names:
        return detail

    fields = ["parent", "name", "idx", "account", "debit", "debit_in_account_currency", "credit", "cost_center"]
    fields += _present_fields("Journal Entry Account", [ROW_LINK_FIELD])

    for row in frappe.get_all(
        "Journal Entry Account",
        filters={"parent": ["in", journal_names]},
        fields=fields,
        order_by="idx asc",
    ):
        bucket = detail.setdefault(
            row.parent,
            {"debit_rows": [], "funding_accounts": [], "cost_center": None},
        )
        if flt(row.debit) or flt(row.debit_in_account_currency):
            bucket["debit_rows"].append(row)
        elif flt(row.credit) and row.account not in bucket["funding_accounts"]:
            bucket["funding_accounts"].append(row.account)
        if not bucket["cost_center"] and row.cost_center:
            bucket["cost_center"] = row.cost_center

    return detail


def _journal_rows(filters):
    journals = _journals(filters)
    if not journals:
        return []

    accounts = _account_rows([journal.name for journal in journals])
    wanted_invoice = filters.get("sales_invoice")
    only_unlinked = filters.get("only_unlinked")

    rows = []
    for je in journals:
        detail = accounts.get(je.name) or {}
        funding = ", ".join(detail.get("funding_accounts") or [])
        legacy_invoice = je.get(LEGACY_LINK_FIELD)
        debit_rows = detail.get("debit_rows") or []

        # One row per debit row. No pro-rata split as on the payment side: each row already
        # owns both its amount and its invoice, so there is no remainder to absorb. A template
        # journal with no debit row still yields one row, so no voucher ever vanishes — that is
        # the only place the voucher-level total is still used.
        emitted = [
            _journal_row(
                je,
                funding,
                reward=flt(account_row.debit) or flt(account_row.debit_in_account_currency),
                reward_account=account_row.account,
                invoice=account_row.get(ROW_LINK_FIELD) or legacy_invoice,
                cost_center=account_row.cost_center or detail.get("cost_center"),
                row_idx=account_row.idx,
                journal_row=account_row.name,
            )
            for account_row in debit_rows
        ] or [
            _journal_row(
                je,
                funding,
                reward=je.total_debit,
                reward_account="",
                invoice=legacy_invoice,
                cost_center=detail.get("cost_center"),
                row_idx=None,
                journal_row=None,
            )
        ]

        for row in emitted:
            if wanted_invoice and row["sales_invoice"] != wanted_invoice:
                continue
            if only_unlinked and row["sales_invoice"]:
                continue
            rows.append(row)

    return rows


def _journal_row(je, funding, reward, reward_account, invoice, cost_center, row_idx, journal_row):
    """One report row for one debit row of a reward journal."""
    return {
        "source": SOURCE_JOURNAL,
        "voucher_no": je.name,
        "journal_entry": je.name,
        "payment_entry": None,
        "row_idx": row_idx,
        "journal_row": journal_row,
        "posting_date": je.posting_date,
        "status": DOCSTATUS_LABEL.get(je.docstatus, ""),
        "workflow_state": je.get("workflow_state"),
        "reward_amount": flt(reward, PRECISION),
        "reward_account": reward_account,
        "funding_account": funding,
        "cost_center": cost_center,
        "sales_invoice": invoice,
        # a journal does not allocate against an invoice — that column is a payment concept
        "allocated_amount": None,
        "payment_amount": None,
        "payment_type": None,
        "cheque_no": je.cheque_no,
        "epromise_vr_no": je.get("epromise_vr_no"),
        "remark": (je.user_remark or "").strip(),
        "party_customer": None,
        "party_customer_name": None,
        "branch": None,
    }


# ── Payment side ──────────────────────────────────────────────────────────────────

def _payment_deductions(filters, accounts):
    """Every Deductions-or-Loss row on the reward accounts, with its payment header."""
    payment = frappe.qb.DocType("Payment Entry")
    deduction = frappe.qb.DocType("Payment Entry Deduction")
    optional = _present_fields("Payment Entry", ["workflow_state", "epromise_vr_no", "branch"])

    query = (
        frappe.qb.from_(deduction)
        .inner_join(payment)
        .on(deduction.parent == payment.name)
        .select(
            deduction.parent.as_("payment_entry"),
            deduction.account,
            deduction.amount,
            deduction.cost_center,
            deduction.description,
            payment.posting_date,
            payment.docstatus,
            payment.payment_type,
            payment.party_type,
            payment.party,
            payment.party_name,
            payment.paid_amount,
            payment.received_amount,
            payment.paid_from,
            payment.paid_to,
            payment.reference_no,
            payment.remarks,
            payment.company,
            *[getattr(payment, field) for field in optional],
        )
        .where(deduction.parenttype == SOURCE_PAYMENT)
        .where(deduction.account.isin(accounts))
        .where(payment.docstatus.isin(_docstatus_list(filters)))
        .orderby(payment.posting_date, order=Order.desc)
        .orderby(deduction.parent, order=Order.desc)
        .orderby(deduction.idx)
    )

    if filters.get("company"):
        query = query.where(payment.company == filters.get("company"))

    from_date, to_date = _date_range(filters)
    if from_date:
        query = query.where(payment.posting_date >= from_date)
    if to_date:
        query = query.where(payment.posting_date <= to_date)

    return query.run(as_dict=True)


def _payment_allocations(payment_names):
    """Sales Invoice allocations of those payments, in one query."""
    allocations = {}
    if not payment_names:
        return allocations

    for row in frappe.get_all(
        "Payment Entry Reference",
        filters={"parent": ["in", payment_names], "reference_doctype": "Sales Invoice"},
        fields=["parent", "reference_name", "allocated_amount"],
        order_by="parent asc, idx asc",
    ):
        allocations.setdefault(row.parent, []).append(row)

    return allocations


def _split_reward(total, references):
    """Spread one payment's reward across the invoices it settles.

    Returns (invoice, allocated_amount, reward) per invoice. Almost every collection
    settles a single invoice, so the split is usually a no-op. Where it is not, the reward
    follows the allocated amounts and the last invoice absorbs the rounding remainder, so
    the rows still add up to the deduction booked on the payment.
    """
    total = flt(total, PRECISION)
    if not references:
        return [(None, None, total)]
    if len(references) == 1:
        return [(references[0].reference_name, flt(references[0].allocated_amount), total)]

    allocated_total = sum(flt(ref.allocated_amount) for ref in references)
    split, running = [], 0.0
    for ref in references[:-1]:
        share = flt(ref.allocated_amount) / allocated_total if allocated_total else 1.0 / len(references)
        amount = flt(total * share, PRECISION)
        running += amount
        split.append((ref.reference_name, flt(ref.allocated_amount), amount))

    last = references[-1]
    split.append((last.reference_name, flt(last.allocated_amount), flt(total - running, PRECISION)))
    return split


def _payment_rows(filters):
    accounts = _template_accounts(filters.get("journal_template") or TEMPLATE)
    if not accounts:
        return []

    deductions = _payment_deductions(filters, accounts)
    if not deductions:
        return []

    payments = {}
    for row in deductions:
        bucket = payments.setdefault(
            row.payment_entry,
            {"head": row, "reward": 0.0, "accounts": [], "cost_center": None, "descriptions": []},
        )
        bucket["reward"] += flt(row.amount)
        if row.account not in bucket["accounts"]:
            bucket["accounts"].append(row.account)
        if not bucket["cost_center"] and row.cost_center:
            bucket["cost_center"] = row.cost_center
        description = (row.description or "").strip()
        if description and description not in bucket["descriptions"]:
            bucket["descriptions"].append(description)

    allocations = _payment_allocations(list(payments))
    wanted_invoice = filters.get("sales_invoice")

    rows = []
    for name, bucket in payments.items():
        head = bucket["head"]
        is_receive = head.payment_type == "Receive"
        remark = "; ".join(bucket["descriptions"]) or (head.remarks or "").strip()

        for invoice, allocated, reward in _split_reward(bucket["reward"], allocations.get(name) or []):
            if wanted_invoice and invoice != wanted_invoice:
                continue
            rows.append(
                {
                    "source": SOURCE_PAYMENT,
                    "voucher_no": name,
                    "journal_entry": None,
                    "payment_entry": name,
                    "posting_date": head.posting_date,
                    "status": DOCSTATUS_LABEL.get(head.docstatus, ""),
                    "workflow_state": head.get("workflow_state"),
                    "reward_amount": reward,
                    "reward_account": ", ".join(bucket["accounts"]),
                    "funding_account": head.paid_to if is_receive else head.paid_from,
                    "cost_center": bucket["cost_center"],
                    "sales_invoice": invoice,
                    "allocated_amount": allocated,
                    "payment_amount": flt(head.received_amount if is_receive else head.paid_amount),
                    "payment_type": head.payment_type,
                    "cheque_no": head.reference_no,
                    "epromise_vr_no": head.get("epromise_vr_no"),
                    "remark": remark,
                    "party_customer": head.party if head.party_type == "Customer" else None,
                    "party_customer_name": head.party_name if head.party_type == "Customer" else None,
                    "branch": head.get("branch"),
                }
            )

    return rows


# ── Invoice enrichment ────────────────────────────────────────────────────────────

def _invoices(invoice_names):
    """Sales Invoice header data for the referenced invoices, in one query."""
    if not invoice_names:
        return {}

    rows = frappe.get_all(
        "Sales Invoice",
        filters={"name": ["in", list(invoice_names)]},
        fields=[
            "name",
            "customer",
            "customer_name",
            "posting_date",
            "grand_total",
            "base_grand_total",
            "outstanding_amount",
            "branch",
            "status",
            "currency",
        ],
    )
    return {row.name: row for row in rows}


def _attach_invoice_detail(rows):
    invoices = _invoices({row["sales_invoice"] for row in rows if row.get("sales_invoice")})

    for row in rows:
        invoice = invoices.get(row["sales_invoice"]) if row.get("sales_invoice") else None
        invoice_total = flt(invoice.base_grand_total) if invoice else 0.0
        reward = flt(row["reward_amount"])
        # the payment side knows its customer even when the invoice row is missing
        party = row.pop("party_customer", None)
        party_name = row.pop("party_customer_name", None)

        row["invoice_date"] = invoice.posting_date if invoice else None
        row["invoice_total"] = invoice_total
        row["invoice_outstanding"] = flt(invoice.outstanding_amount) if invoice else 0.0
        row["invoice_status"] = invoice.status if invoice else None
        row["customer"] = (invoice.customer if invoice else None) or party
        row["customer_name"] = (
            (invoice.customer_name if invoice else None)
            or party_name
            or (None if row.get("sales_invoice") else UNLINKED_LABEL)
        )
        row["branch"] = (invoice.branch if invoice else None) or row.get("branch")
        row["reward_pct"] = flt(reward / invoice_total * 100, 2) if invoice_total else 0.0

    return rows


# ── Build ─────────────────────────────────────────────────────────────────────────

def get_data(filters):
    source = filters.get("source")

    rows = []
    if source != SOURCE_PAYMENT:
        rows.extend(_journal_rows(filters))
    if source != SOURCE_JOURNAL and not filters.get("only_unlinked"):
        # a payment-side reward always names its invoice, so it can never be "unlinked"
        rows.extend(_payment_rows(filters))

    if not rows:
        return []

    _attach_invoice_detail(rows)

    min_amount = flt(filters.get("min_amount"))
    wanted_customer = filters.get("customer")
    wanted_cost_center = filters.get("cost_center")

    data = [
        row
        for row in rows
        if not (min_amount and flt(row["reward_amount"]) < min_amount)
        and not (wanted_customer and row.get("customer") != wanted_customer)
        and not (wanted_cost_center and row.get("cost_center") != wanted_cost_center)
    ]

    data.sort(
        key=lambda row: (
            getdate(row["posting_date"]) if row.get("posting_date") else EPOCH,
            row["voucher_no"],
            # sibling rows of one voucher read in grid order, not an arbitrary one
            -(row.get("row_idx") or 0),
        ),
        reverse=True,
    )
    return data


def summarise(rows):
    """Customer-wise roll-up; reward rows with no invoice collect under "(Not Linked)".

    A voucher is counted once per customer bucket it touches, so one journal that rewards two
    customers' invoices counts as a voucher for each of them — and rows of a part-linked journal
    can legitimately sit in both a real customer's bucket and "(Not Linked)".
    """
    buckets = {}
    for row in rows:
        key = row.get("customer") or UNLINKED_LABEL
        bucket = buckets.setdefault(
            key,
            {
                "customer": row.get("customer"),
                "customer_name": row.get("customer_name") or key,
                # distinct vouchers, not rows: one voucher now spans several rows on both sides
                "vouchers": set(),
                "invoices": set(),
                "reward_amount": 0.0,
                "journal_reward": 0.0,
                "payment_reward": 0.0,
                "invoice_total": 0.0,
            },
        )
        # keyed on the pair so a journal and a payment that share a name cannot collide
        bucket["vouchers"].add((row.get("source"), row.get("voucher_no")))
        reward = flt(row["reward_amount"])
        bucket["reward_amount"] += reward
        if row.get("source") == SOURCE_PAYMENT:
            bucket["payment_reward"] += reward
        else:
            bucket["journal_reward"] += reward
        if row.get("sales_invoice") and row["sales_invoice"] not in bucket["invoices"]:
            bucket["invoices"].add(row["sales_invoice"])
            # count each invoice's value once, however many vouchers reference it
            bucket["invoice_total"] += flt(row["invoice_total"])

    summary = []
    for bucket in buckets.values():
        invoice_total = flt(bucket["invoice_total"])
        summary.append(
            {
                "customer": bucket["customer"],
                "customer_name": bucket["customer_name"],
                "journals": len(bucket["vouchers"]),
                "invoices": len(bucket["invoices"]),
                "reward_amount": flt(bucket["reward_amount"], PRECISION),
                "journal_reward": flt(bucket["journal_reward"], PRECISION),
                "payment_reward": flt(bucket["payment_reward"], PRECISION),
                "invoice_total": invoice_total,
                "reward_pct": flt(bucket["reward_amount"] / invoice_total * 100, 2) if invoice_total else 0.0,
            }
        )

    summary.sort(key=lambda row: -row["reward_amount"])
    return summary


# ── Columns ───────────────────────────────────────────────────────────────────────

def get_columns():
    return [
        {"fieldname": "source", "label": _("Source"), "fieldtype": "Data", "width": 110},
        {"fieldname": "voucher_no", "label": _("Voucher"), "fieldtype": "Dynamic Link",
         "options": "source", "width": 165},
        # which Accounts row of the journal this reward sits on — the handle for fixing a
        # missing invoice. Blank on the payment side.
        {"fieldname": "row_idx", "label": _("Row #"), "fieldtype": "Int", "width": 70},
        {"fieldname": "posting_date", "label": _("Date"), "fieldtype": "Date", "width": 95},
        {"fieldname": "reward_amount", "label": _("Reward"), "fieldtype": "Currency", "width": 120},
        {"fieldname": "sales_invoice", "label": _("Sales Invoice"), "fieldtype": "Link",
         "options": "Sales Invoice", "width": 170},
        {"fieldname": "allocated_amount", "label": _("Allocated to Invoice"), "fieldtype": "Currency",
         "width": 145},
        {"fieldname": "customer", "label": _("Customer"), "fieldtype": "Link",
         "options": "Customer", "width": 130},
        {"fieldname": "customer_name", "label": _("Customer Name"), "fieldtype": "Data", "width": 210},
        {"fieldname": "invoice_total", "label": _("Invoice Amount"), "fieldtype": "Currency", "width": 130},
        {"fieldname": "reward_pct", "label": _("Reward % of Invoice"), "fieldtype": "Percent", "width": 130},
        {"fieldname": "invoice_outstanding", "label": _("Invoice Outstanding"), "fieldtype": "Currency",
         "width": 140},
        {"fieldname": "invoice_date", "label": _("Invoice Date"), "fieldtype": "Date", "width": 95},
        {"fieldname": "invoice_status", "label": _("Invoice Status"), "fieldtype": "Data", "width": 110},
        {"fieldname": "payment_amount", "label": _("Payment Amount"), "fieldtype": "Currency", "width": 130},
        {"fieldname": "status", "label": _("Voucher Status"), "fieldtype": "Data", "width": 110},
        {"fieldname": "workflow_state", "label": _("Workflow State"), "fieldtype": "Data", "width": 120},
        {"fieldname": "reward_account", "label": _("Reward Account"), "fieldtype": "Data", "width": 220},
        {"fieldname": "funding_account", "label": _("Paid From / To"), "fieldtype": "Data", "width": 220},
        {"fieldname": "cost_center", "label": _("Cost Center"), "fieldtype": "Link",
         "options": "Cost Center", "width": 130},
        {"fieldname": "branch", "label": _("Branch"), "fieldtype": "Link", "options": "Branch", "width": 90},
        {"fieldname": "cheque_no", "label": _("Ref / Cheque No"), "fieldtype": "Data", "width": 110},
        {"fieldname": "epromise_vr_no", "label": _("ePromise VR"), "fieldtype": "Data", "width": 110},
        {"fieldname": "remark", "label": _("Remark"), "fieldtype": "Small Text", "width": 260},
    ]


def get_summary_columns():
    return [
        {"fieldname": "customer", "label": _("Customer"), "fieldtype": "Link",
         "options": "Customer", "width": 140},
        {"fieldname": "customer_name", "label": _("Customer Name"), "fieldtype": "Data", "width": 240},
        {"fieldname": "journals", "label": _("Reward Vouchers"), "fieldtype": "Int", "width": 130},
        {"fieldname": "invoices", "label": _("Invoices"), "fieldtype": "Int", "width": 100},
        {"fieldname": "reward_amount", "label": _("Total Reward"), "fieldtype": "Currency", "width": 140},
        {"fieldname": "journal_reward", "label": _("Reward via Journal"), "fieldtype": "Currency",
         "width": 150},
        {"fieldname": "payment_reward", "label": _("Reward via Payment"), "fieldtype": "Currency",
         "width": 150},
        {"fieldname": "invoice_total", "label": _("Total Invoice Amount"), "fieldtype": "Currency",
         "width": 160},
        {"fieldname": "reward_pct", "label": _("Reward % of Invoices"), "fieldtype": "Percent", "width": 150},
    ]
