# apps/vansale/vansale/sf_trading/report/mode_of_payment_invoice_wise/mode_of_payment_invoice_wise.py
"""Mode of Payment Invoice Wise — how each Sales Invoice was actually settled.

A counter clerk or an accountant looking at an invoice wants one line that says
"Cash", "Card", "Credit" or "Cash / Card", plus the underlying mode names and the
vouchers that carry them. ERPNext keeps that information in four different places,
so this report stitches them together:

  1. **POS invoices** (`is_pos = 1`) settle inside the invoice itself — the
     `Sales Invoice Payment` child table. On Steel Force every POS invoice carries
     exactly one such row and is fully paid, so counter sales resolve to one mode.
  2. **Non-POS invoices** settle through **Payment Entries**, one per mode of payment.
     `vansale.sf_trading.api.sales_invoice_payment.create_payment_entries` deliberately splits
     a mixed collection into several PEs (one per mode), so a "Cash + Card" sale shows
     up as two PEs against the same invoice — that is where mixed modes come from.
  3. **Journal Entries** that credit the receivable against an invoice (knock-offs,
     write-offs, contra). These rarely carry `mode_of_payment`, so the cash/bank leg of
     the same journal names the mode; failing that the leg is classed as an Adjustment.
  4. Whatever is left unpaid is the **Credit** portion (`outstanding_amount`) — on a
     return invoice a negative balance is a **Refund Due**.
  5. Anything still unexplained lands in **Settled (no voucher)** so that every row adds
     up: `Invoice Total = Settled + No-voucher + Outstanding`. On this site that bucket is
     mostly ePromise-migrated history — returns and part-payments whose outstanding was
     written straight into the invoice with no Payment Entry behind it (checked
     2026-07-26: 23 of 1,411 credit sales and 387 of 474 returns in June–July). It is a
     genuine finding for the accounts team, not noise, so it gets its own column.

Two data facts on this site shape the code (verified against prod, 2026-07-26):

  * `Payment Entry.mode_of_payment` is **empty on ~1,500 references**. Those legs are
    resolved from the bank/cash account (`paid_to` / `paid_from`) through
    `Mode of Payment Account`; when an account maps to more than one mode the leg keeps
    the account name instead. Every inferred leg is flagged so accounts staff can fix
    the source voucher — the "Mode Not Set Only" filter lists exactly those invoices.
  * `Mode of Payment.type` and `custom_zatca_payment_means_code` are **not reliable**
    for classification (`Cash-SFSB` carries ZATCA 48 = card, `Swipe-SFSB` carries 10 =
    cash, `NBB-Bank Transfer` is typed `Cash`). Classification therefore reads the mode
    **name** first (see CLASS_KEYWORDS), then falls back to the type. If a
    `Mode of Payment-custom_payment_class` field is ever added, its value wins — no code
    change needed.

**Scope**: only invoices that carry a declared payment mode
(`Sales Invoice.custom_payment_mode` — Cash / Credit / Cheque) are reported. Invoices with
that field blank are skipped silently, so totals here are not the full sales figure for the
period; see INVOICE_TYPES below.

Three views, switched by the **View** filter:
  * Invoice Summary — one row per invoice: class ("Cash / Card"), mode detail, and an
    amount column per class
  * Payment Detail  — one row per payment leg: voucher, date, mode, reference no, amount
  * Mode Summary    — one row per mode of payment: invoices, vouchers, amount, share

Reads are batched: one query for invoices, one per leg source, one for the mode/account
maps. No per-row lookups, no SQL strings.
"""

import re

import frappe
from frappe import _
from frappe.utils import cint, flt, get_first_day, getdate, nowdate

CLASS_CASH = "Cash"
CLASS_CARD = "Card"
CLASS_WALLET = "BenefitPay"
CLASS_CHEQUE = "Cheque"
CLASS_BANK = "Bank Transfer"
CLASS_OTHER = "Other"
CLASS_ADJUSTMENT = "Adjustment"
CLASS_NO_VOUCHER = "Settled (no voucher)"
CLASS_CREDIT = "Credit"
CLASS_REFUND = "Refund Due"

#: Buckets that get their own amount column, in display order.
CLASS_COLUMNS = (
    CLASS_CASH,
    CLASS_CARD,
    CLASS_WALLET,
    CLASS_CHEQUE,
    CLASS_BANK,
    CLASS_OTHER,
    CLASS_ADJUSTMENT,
    CLASS_NO_VOUCHER,
    CLASS_CREDIT,
    CLASS_REFUND,
)

#: Mode-of-payment name keywords → class. Order matters: the first hit wins, so
#: "cheque" is tested before "bank" ("PDC Account" is a bank account) and "card"
#: before "bank" ("Al Salam Prepaid Card").
CLASS_KEYWORDS = (
    (CLASS_CHEQUE, ("cheque", "check", "pdc", "post dated", "postdated")),
    (CLASS_CARD, ("swipe", "card", "mada", "visa", "master", "amex", "pos machine")),
    (CLASS_WALLET, ("bpay", "benefit", "wallet", "stc pay", "apple pay", "google pay", "qr")),
    (CLASS_CASH, ("cash", "petty")),
    (CLASS_BANK, ("bank", "transfer", "wire", "draft", "iban", "online", "remit")),
)

#: Mode of Payment.type → class, used when no keyword matches.
TYPE_CLASS = {"Cash": CLASS_CASH, "Bank": CLASS_BANK, "General": CLASS_OTHER}

#: Account.account_type → class, used when a leg has no mode of payment at all.
ACCOUNT_TYPE_CLASS = {"Cash": CLASS_CASH, "Bank": CLASS_BANK}

#: Optional field on Mode of Payment. When present its value overrides the keyword
#: guess, so classification becomes configurable without a deploy.
CLASS_OVERRIDE_FIELD = "custom_payment_class"

CREDIT_LABEL = "Credit (unpaid)"
REFUND_LABEL = "Refund Due"
NO_VOUCHER_LABEL = "Settled without a payment voucher"
CHANGE_LABEL = "Change Returned"
UNSET_LABEL = "(mode not set)"
UNSET_SEPARATOR = " - "

#: A POS row can be keyed a cent away from the invoice total (BHD prints 3 decimals but
#: the counter types 2). Gaps at or below this are rounding, not a missing payment — and
#: not a Credit / Refund either: without this cut, a return left with 4 fils outstanding
#: reads as "Cash / Refund Due" and every such invoice is counted as mixed-mode (on the
#: UAT copy that was 381 "mixed" invoices instead of the real ~140).
ROUNDING_TOLERANCE = 0.05

DOCSTATUS_LABEL = {0: _("Draft"), 1: _("Submitted"), 2: _("Cancelled")}

#: The **Invoice Type** column is the counter's own declaration — the Select field
#: `Sales Invoice.custom_payment_mode` (Cash / Credit / Cheque), not something derived from
#: `is_pos` / `is_return`. The field is not mandatory, and invoices where nobody set it are
#: **left out of the report entirely** (quietly, no message): only declared invoices are in
#: scope. On UAT that is 954 of 2,604 July invoices — the rest carry no declaration at all.
#: The `Check` column compares the declaration against what the vouchers actually say.
INVOICE_TYPES = ("Cash", "Credit", "Cheque")

VIEW_SUMMARY = "Invoice Summary"
VIEW_DETAIL = "Payment Detail"
VIEW_MODE = "Mode Summary"

#: Invoice names are pushed through `in` filters; chunk them so the SQL stays sane
#: on wide date ranges.
CHUNK = 2000


def execute(filters=None):
    filters = frappe._dict(filters or {})
    validate_filters(filters)

    invoices = get_invoices(filters)
    if not invoices:
        return get_columns(), []

    legs = get_payment_legs(filters, list(invoices))
    rows = build_invoice_rows(invoices, legs)
    rows = apply_post_filters(filters, rows)

    report_chart, report_summary = chart(rows), summary(rows)

    view = filters.get("view") or VIEW_SUMMARY
    if view == VIEW_DETAIL:
        return get_detail_columns(), detail_rows(rows), None, report_chart, report_summary
    if view == VIEW_MODE:
        return get_mode_summary_columns(), mode_summary(rows), None, report_chart, report_summary
    return get_columns(), strip_internal(rows), None, report_chart, report_summary


def strip_internal(rows):
    """Drop the leg/aggregate scratch keys — they would otherwise ride along to the client."""
    for row in rows:
        for key in ("_legs", "_classes", "_modes", "_precision"):
            row.pop(key, None)
    return rows


# --------------------------------------------------------------------------------------
# filters
# --------------------------------------------------------------------------------------


def validate_filters(filters):
    if not filters.get("company"):
        frappe.throw(_("Company is required"))

    filters.from_date = getdate(filters.get("from_date") or get_first_day(nowdate()))
    filters.to_date = getdate(filters.get("to_date") or nowdate())
    if filters.from_date > filters.to_date:
        frappe.throw(_("From Date cannot be after To Date"))


def invoice_conditions(filters, si):
    """Invoice-level conditions shared by both date bases."""
    conds = [si.docstatus == 1, si.company == filters.company]

    if filters.get("customer"):
        conds.append(si.customer == filters.customer)
    if filters.get("branch"):
        conds.append(si.branch == filters.branch)
    if filters.get("sales_invoice"):
        conds.append(si.name == filters.sales_invoice)
    if filters.get("status"):
        conds.append(si.status == filters.status)
    if filters.get("sales_person"):
        # `custom_sales_person` holds a plain name ("Akhil"), not a link — exact match.
        conds.append(si.custom_sales_person == filters.sales_person)

    # Only invoices the counter declared a payment mode on are in scope. Silent by design —
    # an invoice with no declaration is simply not part of this report.
    conds += [si.custom_payment_mode.isnotnull(), si.custom_payment_mode != ""]

    if filters.get("invoice_type"):
        conds.append(si.custom_payment_mode == filters.invoice_type)

    return conds


def get_invoices(filters):
    """Return {invoice_name: row}.

    On the *Payment Date* basis the date range applies to the payment vouchers, so the
    invoice set is discovered from the vouchers first and the invoices are then read
    without a posting-date filter.
    """
    si = frappe.qb.DocType("Sales Invoice")
    query = (
        frappe.qb.from_(si)
        .select(
            si.name,
            si.posting_date,
            si.due_date,
            si.customer,
            si.customer_name,
            si.branch,
            si.status,
            si.currency,
            si.return_against,
            si.grand_total,
            si.rounded_total,
            si.disable_rounded_total,
            si.outstanding_amount,
            si.change_amount,
            si.custom_payment_mode,
            si.custom_sales_person,
        )
        .orderby(si.posting_date)
        .orderby(si.name)
    )
    for cond in invoice_conditions(filters, si):
        query = query.where(cond)

    if filters.get("date_basis") == "Payment Date":
        names = invoices_paid_in_range(filters)
        if not names:
            return {}
        rows = []
        for chunk in chunks(names):
            rows += query.where(si.name.isin(chunk)).run(as_dict=True)
    else:
        rows = query.where(si.posting_date[filters.from_date : filters.to_date]).run(as_dict=True)

    return {row.name: row for row in rows}


def invoices_paid_in_range(filters):
    """Invoice names touched by a POS payment / Payment Entry / Journal Entry in range."""
    names = set()
    docstatus = payment_docstatus(filters)

    si = frappe.qb.DocType("Sales Invoice")
    sip = frappe.qb.DocType("Sales Invoice Payment")
    pos = (
        frappe.qb.from_(sip)
        .inner_join(si)
        .on(si.name == sip.parent)
        .select(sip.parent)
        .where(si.posting_date[filters.from_date : filters.to_date])
    )
    for cond in invoice_conditions(filters, si):
        pos = pos.where(cond)
    names.update(row.parent for row in pos.run(as_dict=True))

    per = frappe.qb.DocType("Payment Entry Reference")
    pe = frappe.qb.DocType("Payment Entry")
    payments = (
        frappe.qb.from_(per)
        .inner_join(pe)
        .on(pe.name == per.parent)
        .select(per.reference_name)
        .where(per.reference_doctype == "Sales Invoice")
        .where(pe.docstatus.isin(docstatus))
        .where(pe.company == filters.company)
        .where(pe.posting_date[filters.from_date : filters.to_date])
    )
    names.update(row.reference_name for row in payments.run(as_dict=True))

    jea = frappe.qb.DocType("Journal Entry Account")
    je = frappe.qb.DocType("Journal Entry")
    journals = (
        frappe.qb.from_(jea)
        .inner_join(je)
        .on(je.name == jea.parent)
        .select(jea.reference_name)
        .where(jea.reference_type == "Sales Invoice")
        .where(je.docstatus.isin(docstatus))
        .where(je.company == filters.company)
        .where(je.posting_date[filters.from_date : filters.to_date])
    )
    names.update(row.reference_name for row in journals.run(as_dict=True))

    return [name for name in names if name]


def payment_docstatus(filters):
    return [0, 1] if cint(filters.get("include_draft_payments")) else [1]


def chunks(items, size=CHUNK):
    items = list(items)
    for start in range(0, len(items), size):
        yield items[start : start + size]


# --------------------------------------------------------------------------------------
# payment legs
# --------------------------------------------------------------------------------------


def get_payment_legs(filters, invoice_names):
    """Return {invoice: [leg, …]} across POS rows, Payment Entries and Journal Entries."""
    legs = {}
    sources = (
        pos_legs(invoice_names)
        + payment_entry_legs(filters, invoice_names)
        + journal_legs(filters, invoice_names)
    )
    for leg in sources:
        legs.setdefault(leg["invoice"], []).append(leg)

    for rows in legs.values():
        rows.sort(key=lambda leg: (leg["payment_date"] or getdate("1900-01-01"), leg["voucher_no"]))
    return legs


def pos_legs(invoice_names):
    """Payments recorded inside a POS invoice — settled on the invoice date."""
    sip = frappe.qb.DocType("Sales Invoice Payment")
    rows = []
    for chunk in chunks(invoice_names):
        rows += (
            frappe.qb.from_(sip)
            .select(sip.parent, sip.mode_of_payment, sip.amount, sip.account)
            .where(sip.parent.isin(chunk))
            .where(sip.amount != 0)
            .run(as_dict=True)
        )

    return [
        {
            "invoice": row.parent,
            "voucher_type": "Sales Invoice",
            "voucher_no": row.parent,
            "payment_date": None,  # filled from the invoice posting date
            "mode_of_payment": row.mode_of_payment,
            "amount": flt(row.amount),
            "account": row.account,
            "reference_no": None,
            "docstatus": 1,
            "source": "POS",
        }
        for row in rows
    ]


def payment_entry_legs(filters, invoice_names):
    per = frappe.qb.DocType("Payment Entry Reference")
    pe = frappe.qb.DocType("Payment Entry")
    docstatus = payment_docstatus(filters)

    rows = []
    for chunk in chunks(invoice_names):
        rows += (
            frappe.qb.from_(per)
            .inner_join(pe)
            .on(pe.name == per.parent)
            .select(
                per.parent.as_("voucher_no"),
                per.reference_name.as_("invoice"),
                per.allocated_amount,
                pe.mode_of_payment,
                pe.posting_date,
                pe.reference_no,
                pe.payment_type,
                pe.paid_to,
                pe.paid_from,
                pe.docstatus,
            )
            .where(per.reference_doctype == "Sales Invoice")
            .where(per.reference_name.isin(chunk))
            .where(pe.docstatus.isin(docstatus))
            .run(as_dict=True)
        )

    legs = []
    for row in rows:
        # On a refund (payment_type "Pay") the money leaves through paid_from.
        account = row.paid_from if row.payment_type == "Pay" else row.paid_to
        legs.append(
            {
                "invoice": row.invoice,
                "voucher_type": "Payment Entry",
                "voucher_no": row.voucher_no,
                "payment_date": getdate(row.posting_date) if row.posting_date else None,
                "mode_of_payment": row.mode_of_payment,
                "amount": flt(row.allocated_amount),
                "account": account,
                "reference_no": row.reference_no,
                "docstatus": row.docstatus,
                "source": "Payment Entry",
            }
        )
    return legs


def journal_legs(filters, invoice_names):
    """Journal Entry rows that settle an invoice.

    `credit - debit` on the receivable row is what the journal knocked off the invoice
    (a return invoice is knocked off with a debit, hence the sign).
    """
    jea = frappe.qb.DocType("Journal Entry Account")
    je = frappe.qb.DocType("Journal Entry")
    docstatus = payment_docstatus(filters)

    rows = []
    for chunk in chunks(invoice_names):
        rows += (
            frappe.qb.from_(jea)
            .inner_join(je)
            .on(je.name == jea.parent)
            .select(
                jea.parent.as_("voucher_no"),
                jea.reference_name.as_("invoice"),
                jea.debit_in_account_currency.as_("debit"),
                jea.credit_in_account_currency.as_("credit"),
                je.posting_date,
                je.mode_of_payment,
                je.cheque_no,
                je.docstatus,
            )
            .where(jea.reference_type == "Sales Invoice")
            .where(jea.reference_name.isin(chunk))
            .where(je.docstatus.isin(docstatus))
            .run(as_dict=True)
        )
    if not rows:
        return []

    bank_accounts = journal_bank_accounts({row.voucher_no for row in rows})

    legs = []
    for row in rows:
        amount = flt(row.credit) - flt(row.debit)
        if not amount:
            continue
        legs.append(
            {
                "invoice": row.invoice,
                "voucher_type": "Journal Entry",
                "voucher_no": row.voucher_no,
                "payment_date": getdate(row.posting_date) if row.posting_date else None,
                "mode_of_payment": row.mode_of_payment,
                "amount": amount,
                "account": bank_accounts.get(row.voucher_no),
                "reference_no": row.cheque_no,
                "docstatus": row.docstatus,
                "source": "Journal Entry",
            }
        )
    return legs


def journal_bank_accounts(journal_names):
    """{journal: cash/bank account} — the money side of a settlement journal."""
    jea = frappe.qb.DocType("Journal Entry Account")
    account = frappe.qb.DocType("Account")

    found = {}
    for chunk in chunks(journal_names):
        rows = (
            frappe.qb.from_(jea)
            .inner_join(account)
            .on(account.name == jea.account)
            .select(jea.parent, jea.account)
            .where(jea.parent.isin(chunk))
            .where(account.account_type.isin(["Cash", "Bank"]))
            .run(as_dict=True)
        )
        for row in rows:
            found.setdefault(row.parent, row.account)
    return found


# --------------------------------------------------------------------------------------
# classification
# --------------------------------------------------------------------------------------


def mode_meta():
    """Mode / account maps, built once per request."""
    cached = getattr(frappe.local, "_sf_mop_meta", None)
    if cached:
        return cached

    fields = ["name", "type"]
    if class_override_available():
        fields.append(CLASS_OVERRIDE_FIELD)

    modes = {}
    for row in frappe.get_all("Mode of Payment", fields=fields):
        modes[row.name] = {
            "type": row.get("type"),
            "class": (row.get(CLASS_OVERRIDE_FIELD) or "").strip() or None,
        }

    by_account = {}
    for row in frappe.get_all("Mode of Payment Account", fields=["parent", "default_account"]):
        if row.default_account:
            by_account.setdefault(row.default_account, set()).add(row.parent)

    accounts = {
        row.name: row.account_type
        for row in frappe.get_all("Account", fields=["name", "account_type"])
    }

    meta = {"modes": modes, "by_account": by_account, "accounts": accounts}
    frappe.local._sf_mop_meta = meta
    return meta


def class_override_available():
    return frappe.get_meta("Mode of Payment").has_field(CLASS_OVERRIDE_FIELD)


def resolve_leg_mode(leg):
    """Set `mode_label` and `payment_class` on a leg.

    `mode_missing` is decided by the caller from the raw voucher value — a leg whose
    mode had to be inferred from the bank account still counts as missing.
    """
    meta = mode_meta()
    mode = (leg.get("mode_of_payment") or "").strip()

    if not mode and leg.get("account"):
        candidates = meta["by_account"].get(leg["account"]) or set()
        if len(candidates) == 1:
            mode = next(iter(candidates))

    if mode:
        leg["mode_of_payment"] = mode
        leg["mode_label"] = mode
        leg["payment_class"] = classify_mode(mode)
        return leg

    if leg.get("account"):
        leg["mode_label"] = UNSET_LABEL + UNSET_SEPARATOR + leg["account"]
        leg["payment_class"] = classify_account(leg["account"])
    elif leg["source"] == "Journal Entry":
        leg["mode_label"] = CLASS_ADJUSTMENT
        leg["payment_class"] = CLASS_ADJUSTMENT
    else:
        leg["mode_label"] = UNSET_LABEL
        leg["payment_class"] = CLASS_OTHER
    return leg


def classify_mode(mode):
    info = mode_meta()["modes"].get(mode) or {}
    if info.get("class"):
        return info["class"]

    name = (mode or "").lower()
    for payment_class, keywords in CLASS_KEYWORDS:
        if any(keyword in name for keyword in keywords):
            return payment_class

    return TYPE_CLASS.get(info.get("type"), CLASS_OTHER)


def classify_account(account):
    name = (account or "").lower()
    for payment_class, keywords in CLASS_KEYWORDS:
        if any(keyword in name for keyword in keywords):
            return payment_class
    return ACCOUNT_TYPE_CLASS.get(mode_meta()["accounts"].get(account), CLASS_OTHER)


# --------------------------------------------------------------------------------------
# row building
# --------------------------------------------------------------------------------------


def precision_for(currency):
    """Decimals the currency prints with — BHD is 3, most others 2."""
    cache = getattr(frappe.local, "_sf_currency_precision", None)
    if cache is None:
        cache = frappe.local._sf_currency_precision = {}
    if currency in cache:
        return cache[currency]

    number_format = frappe.db.get_value("Currency", currency, "number_format") or "#,###.##"
    cache[currency] = len(number_format.split(".")[-1]) if "." in number_format else 0
    return cache[currency]


def document_total(invoice, precision):
    """The payable face value of the invoice.

    `rounded_total` is only meaningful when rounding is enabled — with
    `disable_rounded_total` set, ERPNext leaves the rounding *residue* in the field
    (several July returns here hold -0.004 against a -300.014 grand total). ERPNext's own
    rule is the same CASE: see
    `frappe/erpnext: erpnext/controllers/accounts_controller.py:3529`.
    """
    if cint(invoice.get("disable_rounded_total")) or not flt(invoice.get("rounded_total")):
        return flt(invoice.get("grand_total"), precision)
    return flt(invoice.get("rounded_total"), precision)


def build_invoice_rows(invoices, legs):
    rows = []
    for name, invoice in invoices.items():
        precision = precision_for(invoice.currency)
        invoice_legs = legs.get(name) or []

        # Change handed back at the counter is money that left again — ERPNext keeps it in
        # `change_amount`, outside the payments table, so it needs its own (negative) leg
        # or the invoice looks over-collected.
        change = flt(invoice.change_amount, precision)
        if change:
            invoice_legs.append(
                {
                    "invoice": name,
                    "voucher_type": "Sales Invoice",
                    "voucher_no": name,
                    "payment_date": getdate(invoice.posting_date),
                    "mode_of_payment": None,
                    "mode_label": CHANGE_LABEL,
                    "payment_class": CLASS_CASH,
                    "amount": -change,
                    "account": None,
                    "reference_no": None,
                    "docstatus": 1,
                    "source": "POS",
                    "mode_missing": 0,
                    "_resolved": 1,
                }
            )

        for leg in invoice_legs:
            if leg.get("_resolved"):
                continue
            leg["mode_missing"] = 0 if (leg.get("mode_of_payment") or "").strip() else 1
            if leg["source"] == "POS" and not leg.get("payment_date"):
                leg["payment_date"] = getdate(invoice.posting_date)
            resolve_leg_mode(leg)

        settled = sum(flt(leg["amount"]) for leg in invoice_legs)
        outstanding = flt(invoice.outstanding_amount, precision)
        invoice_total = document_total(invoice, precision)

        by_class = {}
        by_mode = {}
        for leg in invoice_legs:
            amount = flt(leg["amount"], precision)
            if not amount:
                continue
            by_class[leg["payment_class"]] = flt(by_class.get(leg["payment_class"])) + amount
            by_mode[leg["mode_label"]] = flt(by_mode.get(leg["mode_label"])) + amount

        if outstanding > ROUNDING_TOLERANCE:
            by_class[CLASS_CREDIT] = flt(by_class.get(CLASS_CREDIT)) + outstanding
            by_mode[CREDIT_LABEL] = flt(by_mode.get(CREDIT_LABEL)) + outstanding
        elif outstanding < -ROUNDING_TOLERANCE:
            by_class[CLASS_REFUND] = flt(by_class.get(CLASS_REFUND)) + outstanding
            by_mode[REFUND_LABEL] = flt(by_mode.get(REFUND_LABEL)) + outstanding

        # Whatever the vouchers do not explain. Mostly ePromise-migrated history whose
        # outstanding was written straight onto the invoice; keeps every row balanced.
        no_voucher = flt(invoice_total - outstanding - settled, precision)
        if abs(no_voucher) > ROUNDING_TOLERANCE:
            by_class[CLASS_NO_VOUCHER] = flt(by_class.get(CLASS_NO_VOUCHER)) + no_voucher
            by_mode[NO_VOUCHER_LABEL] = flt(by_mode.get(NO_VOUCHER_LABEL)) + no_voucher
        else:
            no_voucher = 0.0

        ordered_classes = sorted(by_class.items(), key=lambda item: -abs(item[1]))
        ordered_modes = sorted(by_mode.items(), key=lambda item: -abs(item[1]))

        row = {
            "invoice": name,
            "posting_date": invoice.posting_date,
            "due_date": invoice.due_date,
            "invoice_type": invoice.custom_payment_mode,
            "customer": invoice.customer,
            "customer_name": invoice.customer_name,
            "branch": invoice.branch,
            "status": invoice.status,
            "currency": invoice.currency,
            "grand_total": invoice_total,
            "paid_total": flt(settled, precision),
            "outstanding": outstanding,
            "no_voucher": no_voucher,
            "payment_class": " / ".join(label for label, _amount in ordered_classes)
            or _("Not Settled"),
            "mode_of_payment": " | ".join(
                label + ": " + format_amount(amount, precision) for label, amount in ordered_modes
            ),
            "payments_count": len([leg for leg in invoice_legs if flt(leg["amount"])]),
            "payment_refs": ", ".join(
                sorted({leg["voucher_no"] for leg in invoice_legs if leg["source"] != "POS"})
            ),
            "reference_nos": ", ".join(
                sorted({leg["reference_no"] for leg in invoice_legs if leg.get("reference_no")})
            ),
            "last_payment_date": max(
                (leg["payment_date"] for leg in invoice_legs if leg.get("payment_date")),
                default=None,
            ),
            "mode_mismatch": mismatch_label(invoice.custom_payment_mode, by_class),
            "mode_not_set": 1 if any(leg["mode_missing"] for leg in invoice_legs) else 0,
            "is_mixed": 1 if len(ordered_classes) > 1 else 0,
            "sales_person": invoice.custom_sales_person,
            "return_against": invoice.return_against,
            "_legs": invoice_legs,
            "_classes": by_class,
            "_modes": by_mode,
            "_precision": precision,
        }
        for payment_class in CLASS_COLUMNS:
            row[class_fieldname(payment_class)] = flt(by_class.get(payment_class), precision)

        rows.append(row)

    rows.sort(key=lambda row: (row["posting_date"], row["invoice"]))
    return rows


def mismatch_label(declared, by_class):
    """`Sales Invoice.custom_payment_mode` is what the counter *declared*.

    It is filled on a minority of invoices (Cash / Credit / Cheque). When it disagrees
    with what the vouchers actually say, flag it — that is the audit the accounts team
    wants out of this report.
    """
    declared = (declared or "").strip()
    if not declared or not by_class:
        return None

    actual = {label for label, amount in by_class.items() if amount}
    expected = {"Cash": CLASS_CASH, "Cheque": CLASS_CHEQUE, "Credit": CLASS_CREDIT}.get(declared)
    if expected and actual == {expected}:
        return None
    return _("Mismatch")


def class_fieldname(payment_class):
    """"Settled (no voucher)" → `amt_settled_no_voucher` — fieldnames stay plain."""
    return "amt_" + re.sub(r"[^a-z0-9]+", "_", payment_class.lower()).strip("_")


def format_amount(amount, precision):
    return "{:,.{}f}".format(flt(amount, precision), precision)


def apply_post_filters(filters, rows):
    """Filters that can only be answered once the legs are aggregated."""
    mode = filters.get("mode_of_payment")
    payment_class = filters.get("payment_class")
    only_mixed = cint(filters.get("only_mixed"))
    only_unset = cint(filters.get("only_unset_mode"))

    kept = []
    for row in rows:
        if mode and not any(leg.get("mode_of_payment") == mode for leg in row["_legs"]):
            continue
        if payment_class == "Mixed":
            if not row["is_mixed"]:
                continue
        elif payment_class and not flt(row["_classes"].get(payment_class)):
            continue
        if only_mixed and not row["is_mixed"]:
            continue
        if only_unset and not row["mode_not_set"]:
            continue
        kept.append(row)
    return kept


# --------------------------------------------------------------------------------------
# views
# --------------------------------------------------------------------------------------


def detail_rows(rows):
    """One row per payment leg, plus a Credit / Refund line for the unsettled part."""
    out = []
    for row in rows:
        precision = row["_precision"]
        for leg in row["_legs"]:
            if not flt(leg["amount"]):
                continue
            out.append(
                {
                    "invoice": row["invoice"],
                    "posting_date": row["posting_date"],
                    "invoice_type": row["invoice_type"],
                    "customer": row["customer"],
                    "customer_name": row["customer_name"],
                    "branch": row["branch"],
                    "voucher_type": leg["voucher_type"],
                    "voucher_no": leg["voucher_no"],
                    "payment_date": leg.get("payment_date"),
                    "mode_of_payment": leg["mode_label"],
                    "payment_class": leg["payment_class"],
                    "reference_no": leg.get("reference_no"),
                    "account": leg.get("account"),
                    "amount": flt(leg["amount"], precision),
                    "docstatus_label": DOCSTATUS_LABEL.get(cint(leg.get("docstatus")), ""),
                    "mode_not_set": leg["mode_missing"],
                    "currency": row["currency"],
                    "grand_total": row["grand_total"],
                    "outstanding": row["outstanding"],
                }
            )

        for label, payment_class in (
            (CREDIT_LABEL, CLASS_CREDIT),
            (REFUND_LABEL, CLASS_REFUND),
            (NO_VOUCHER_LABEL, CLASS_NO_VOUCHER),
        ):
            amount = flt(row["_classes"].get(payment_class), precision)
            if not amount:
                continue
            out.append(
                {
                    "invoice": row["invoice"],
                    "posting_date": row["posting_date"],
                    "invoice_type": row["invoice_type"],
                    "customer": row["customer"],
                    "customer_name": row["customer_name"],
                    "branch": row["branch"],
                    "voucher_type": "Sales Invoice",
                    "voucher_no": row["invoice"],
                    "payment_date": None,
                    "mode_of_payment": label,
                    "payment_class": payment_class,
                    "amount": amount,
                    "docstatus_label": DOCSTATUS_LABEL[1],
                    "mode_not_set": 0,
                    "currency": row["currency"],
                    "grand_total": row["grand_total"],
                    "outstanding": row["outstanding"],
                }
            )
    return out


def mode_summary(rows):
    """One row per mode label: how many invoices, how many vouchers, how much."""
    totals = {}

    def bucket_for(label, payment_class, currency):
        return totals.setdefault(
            label,
            {
                "mode_of_payment": label,
                "payment_class": payment_class,
                "invoices": 0,
                "transactions": 0,
                "amount": 0.0,
                "currency": currency,
            },
        )

    for row in rows:
        for label, amount in row["_modes"].items():
            bucket = bucket_for(label, class_of_label(label), row["currency"])
            bucket["invoices"] += 1
            bucket["amount"] = flt(bucket["amount"]) + flt(amount)
        for leg in row["_legs"]:
            if flt(leg["amount"]):
                bucket_for(leg["mode_label"], leg["payment_class"], row["currency"])[
                    "transactions"
                ] += 1

    grand_total = sum(abs(flt(bucket["amount"])) for bucket in totals.values()) or 1.0
    out = sorted(totals.values(), key=lambda bucket: -abs(flt(bucket["amount"])))
    for bucket in out:
        bucket["share"] = flt(abs(flt(bucket["amount"])) * 100.0 / grand_total, 2)
    return out


def class_of_label(label):
    fixed = {
        CREDIT_LABEL: CLASS_CREDIT,
        REFUND_LABEL: CLASS_REFUND,
        NO_VOUCHER_LABEL: CLASS_NO_VOUCHER,
        CHANGE_LABEL: CLASS_CASH,
        CLASS_ADJUSTMENT: CLASS_ADJUSTMENT,
    }
    if label in fixed:
        return fixed[label]
    if label.startswith(UNSET_LABEL):
        return classify_account(label.split(UNSET_SEPARATOR, 1)[-1])
    return classify_mode(label)


# --------------------------------------------------------------------------------------
# columns / chart / summary
# --------------------------------------------------------------------------------------


def currency_column():
    return {
        "fieldname": "currency",
        "label": _("Currency"),
        "fieldtype": "Link",
        "options": "Currency",
        "width": 80,
        "hidden": 1,
    }


def money_column(fieldname, label, width=110):
    return {
        "fieldname": fieldname,
        "label": label,
        "fieldtype": "Currency",
        "options": "currency",
        "width": width,
    }


def get_columns():
    columns = [
        {
            "fieldname": "invoice",
            "label": _("Sales Invoice"),
            "fieldtype": "Link",
            "options": "Sales Invoice",
            "width": 150,
        },
        {"fieldname": "posting_date", "label": _("Date"), "fieldtype": "Date", "width": 95},
        {"fieldname": "invoice_type", "label": _("Invoice Type"), "fieldtype": "Data", "width": 110},
        {
            "fieldname": "payment_class",
            "label": _("Mode of Payment"),
            "fieldtype": "Data",
            "width": 150,
        },
        {"fieldname": "mode_of_payment", "label": _("Mode Detail"), "fieldtype": "Data", "width": 280},
        {
            "fieldname": "customer",
            "label": _("Customer"),
            "fieldtype": "Link",
            "options": "Customer",
            "width": 130,
        },
        {"fieldname": "customer_name", "label": _("Customer Name"), "fieldtype": "Data", "width": 190},
        {
            "fieldname": "branch",
            "label": _("Branch"),
            "fieldtype": "Link",
            "options": "Branch",
            "width": 90,
        },
        {"fieldname": "status", "label": _("Status"), "fieldtype": "Data", "width": 100},
        money_column("grand_total", _("Invoice Total"), 120),
        money_column("paid_total", _("Settled (vouchers)"), 130),
        money_column("outstanding", _("Outstanding")),
    ]

    for payment_class in CLASS_COLUMNS:
        columns.append(money_column(class_fieldname(payment_class), _(payment_class)))

    columns += [
        {"fieldname": "payments_count", "label": _("Payments"), "fieldtype": "Int", "width": 80},
        {
            "fieldname": "last_payment_date",
            "label": _("Last Payment"),
            "fieldtype": "Date",
            "width": 105,
        },
        {"fieldname": "payment_refs", "label": _("Payment Entries"), "fieldtype": "Data", "width": 200},
        {
            "fieldname": "reference_nos",
            "label": _("Cheque / Ref No"),
            "fieldtype": "Data",
            "width": 130,
        },
        {"fieldname": "mode_mismatch", "label": _("Check"), "fieldtype": "Data", "width": 90},
        {"fieldname": "due_date", "label": _("Due Date"), "fieldtype": "Date", "width": 95},
        {"fieldname": "sales_person", "label": _("Sales Person"), "fieldtype": "Data", "width": 110},
        currency_column(),
    ]
    return columns


def get_detail_columns():
    return [
        {
            "fieldname": "invoice",
            "label": _("Sales Invoice"),
            "fieldtype": "Link",
            "options": "Sales Invoice",
            "width": 150,
        },
        {"fieldname": "posting_date", "label": _("Invoice Date"), "fieldtype": "Date", "width": 100},
        {"fieldname": "invoice_type", "label": _("Invoice Type"), "fieldtype": "Data", "width": 110},
        {
            "fieldname": "customer",
            "label": _("Customer"),
            "fieldtype": "Link",
            "options": "Customer",
            "width": 130,
        },
        {"fieldname": "customer_name", "label": _("Customer Name"), "fieldtype": "Data", "width": 180},
        {
            "fieldname": "branch",
            "label": _("Branch"),
            "fieldtype": "Link",
            "options": "Branch",
            "width": 90,
        },
        {
            "fieldname": "mode_of_payment",
            "label": _("Mode of Payment"),
            "fieldtype": "Data",
            "width": 200,
        },
        {"fieldname": "payment_class", "label": _("Class"), "fieldtype": "Data", "width": 110},
        money_column("amount", _("Amount"), 120),
        {"fieldname": "voucher_type", "label": _("Voucher Type"), "fieldtype": "Data", "width": 120},
        {
            "fieldname": "voucher_no",
            "label": _("Voucher No"),
            "fieldtype": "Dynamic Link",
            "options": "voucher_type",
            "width": 160,
        },
        {"fieldname": "payment_date", "label": _("Payment Date"), "fieldtype": "Date", "width": 100},
        {"fieldname": "reference_no", "label": _("Cheque / Ref No"), "fieldtype": "Data", "width": 130},
        {
            "fieldname": "account",
            "label": _("Cash / Bank Account"),
            "fieldtype": "Link",
            "options": "Account",
            "width": 200,
        },
        {
            "fieldname": "docstatus_label",
            "label": _("Voucher Status"),
            "fieldtype": "Data",
            "width": 110,
        },
        money_column("grand_total", _("Invoice Total"), 120),
        money_column("outstanding", _("Outstanding")),
        currency_column(),
    ]


def get_mode_summary_columns():
    return [
        {
            "fieldname": "mode_of_payment",
            "label": _("Mode of Payment"),
            "fieldtype": "Data",
            "width": 240,
        },
        {"fieldname": "payment_class", "label": _("Class"), "fieldtype": "Data", "width": 130},
        {"fieldname": "invoices", "label": _("Invoices"), "fieldtype": "Int", "width": 100},
        {"fieldname": "transactions", "label": _("Vouchers"), "fieldtype": "Int", "width": 100},
        money_column("amount", _("Amount"), 150),
        {"fieldname": "share", "label": _("Share %"), "fieldtype": "Percent", "width": 100},
        currency_column(),
    ]


def class_totals(rows):
    totals = {payment_class: 0.0 for payment_class in CLASS_COLUMNS}
    for row in rows:
        for payment_class in CLASS_COLUMNS:
            totals[payment_class] += flt(row["_classes"].get(payment_class))
    return totals


def material(amount):
    """Worth putting on a card or a chart bar.

    Float sums leave residue (a fully-vouchered month came back as -2.7e-15 in the
    no-voucher bucket, which would otherwise draw an empty "Settled (no voucher)" card).
    """
    return abs(flt(amount)) > ROUNDING_TOLERANCE


def chart(rows):
    totals = class_totals(rows)
    labels = [payment_class for payment_class in CLASS_COLUMNS if material(totals[payment_class])]
    if not labels:
        return None
    return {
        "data": {
            "labels": [_(label) for label in labels],
            "datasets": [
                {"name": _("Amount"), "values": [flt(totals[label], 3) for label in labels]}
            ],
        },
        "type": "bar",
        "fieldtype": "Currency",
    }


def summary(rows):
    if not rows:
        return None

    currency = rows[0]["currency"]
    totals = class_totals(rows)
    cards = [
        {"label": _("Invoices"), "value": len(rows), "datatype": "Int"},
        {
            "label": _("Invoiced"),
            "value": sum(flt(row["grand_total"]) for row in rows),
            "datatype": "Currency",
            "currency": currency,
        },
        {
            "label": _("Settled"),
            "value": sum(flt(row["paid_total"]) for row in rows),
            "datatype": "Currency",
            "currency": currency,
        },
    ]

    for payment_class in (CLASS_CASH, CLASS_CARD, CLASS_WALLET, CLASS_CHEQUE, CLASS_BANK):
        if material(totals[payment_class]):
            cards.append(
                {
                    "label": _(payment_class),
                    "value": totals[payment_class],
                    "datatype": "Currency",
                    "currency": currency,
                }
            )

    if material(totals[CLASS_CREDIT]):
        cards.append(
            {
                "label": _("Credit Outstanding"),
                "value": totals[CLASS_CREDIT],
                "datatype": "Currency",
                "currency": currency,
                "indicator": "Red",
            }
        )

    if material(totals[CLASS_NO_VOUCHER]):
        cards.append(
            {
                "label": _("Settled (no voucher)"),
                "value": totals[CLASS_NO_VOUCHER],
                "datatype": "Currency",
                "currency": currency,
                "indicator": "Orange",
            }
        )

    mixed = len([row for row in rows if row["is_mixed"]])
    cards.append(
        {"label": _("Mixed Mode Invoices"), "value": mixed, "datatype": "Int", "indicator": "Orange"}
    )

    unset = len([row for row in rows if row["mode_not_set"]])
    if unset:
        cards.append(
            {"label": _("Mode Not Set"), "value": unset, "datatype": "Int", "indicator": "Red"}
        )
    return cards
