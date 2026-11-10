# apps/vansale/vansale/sf_trading/api/business_dashboard.py
"""Data behind the Business Dashboard page.

Everything is read from GL Entry rather than from the source documents. A sale can be a Sales
Invoice, a POS invoice or a journal; money can move by Payment Entry, by journal, or by a POS
settlement with no Payment Entry at all. The ledger is the one place all of them agree, so the
dashboard and the Trial Balance can never tell different stories.

Cash and bank are read the same way: the balance of the accounts typed Cash and Bank, not a
sum of payment documents. On this site over a thousand Payment Entries carry no mode of
payment, so any figure built from modes alone would be short by whatever those moved.

Nothing here writes. The data-quality section reports what looks wrong and names the documents;
it does not correct anything, because these are posted accounting entries and rewriting them to
make a chart tidy would put the dashboard out of step with the ledger.
"""

import frappe
from frappe import _
from frappe.utils import add_months, cint, flt, getdate, nowdate

# How a period is bucketed for the trend charts
GRANULARITY = {
    "Daily": "%Y-%m-%d",
    "Weekly": "%x-W%v",
    "Monthly": "%Y-%m",
}


def _dates(from_date, to_date):
    to_date = getdate(to_date or nowdate())
    from_date = getdate(from_date or add_months(to_date, -3))
    if from_date > to_date:
        from_date, to_date = to_date, from_date
    return from_date, to_date


def _company(company=None):
    return company or frappe.defaults.get_user_default("Company") or frappe.db.get_value(
        "Company", {}, "name"
    )


def _money_accounts(company):
    """The accounts that actually hold money."""
    return frappe.get_all(
        "Account",
        filters={"company": company, "is_group": 0, "account_type": ["in", ["Cash", "Bank"]]},
        fields=["name", "account_type", "account_name"],
        order_by="account_type asc, name asc",
    )


def _cc_clause(cost_center, params):
    if not cost_center:
        return ""
    params["cost_center"] = cost_center
    return " AND gle.cost_center = %(cost_center)s"


@frappe.whitelist()
def get_dashboard(
    company=None,
    from_date=None,
    to_date=None,
    granularity="Monthly",
    cost_center=None,
    mode_of_payment=None,
):
    """Everything the dashboard draws, in one round trip."""
    company = _company(company)
    if not company:
        frappe.throw(_("No company found."))
    frappe.has_permission("GL Entry", "read", throw=True)

    from_date, to_date = _dates(from_date, to_date)
    granularity = granularity if granularity in GRANULARITY else "Monthly"

    return {
        "meta": {
            "company": company,
            "currency": frappe.db.get_value("Company", company, "default_currency"),
            "from_date": str(from_date),
            "to_date": str(to_date),
            "granularity": granularity,
            "generated_on": frappe.utils.now_datetime().strftime("%d %b %Y %H:%M"),
        },
        "kpi": _kpis(company, from_date, to_date, cost_center),
        "money": _money_position(company, to_date),
        "trend": _trend(company, from_date, to_date, granularity, cost_center),
        "expenses": _expense_breakdown(company, from_date, to_date, cost_center),
        "cashflow": _cashflow(company, from_date, to_date, granularity, mode_of_payment),
        "outstanding": _outstanding(company, to_date),
        "insights": _insights(company, from_date, to_date, cost_center),
        "quality": _data_quality(company, from_date, to_date),
    }


# ── headline numbers ──────────────────────────────────────────────────────────

def _kpis(company, from_date, to_date, cost_center):
    params = {"company": company, "from_date": from_date, "to_date": to_date}
    cc = _cc_clause(cost_center, params)

    rows = frappe.db.sql(
        """
        SELECT acc.root_type AS root_type,
               ROUND(SUM(gle.credit - gle.debit), 3) AS credit_net,
               ROUND(SUM(gle.debit - gle.credit), 3) AS debit_net
        FROM `tabGL Entry` gle
        INNER JOIN `tabAccount` acc ON acc.name = gle.account
        WHERE gle.company = %(company)s AND gle.is_cancelled = 0
          AND gle.posting_date BETWEEN %(from_date)s AND %(to_date)s
          AND acc.root_type IN ('Income', 'Expense')
        """
        + cc
        + " GROUP BY acc.root_type",
        params,
        as_dict=True,
    )

    sales = expenses = 0.0
    for r in rows:
        if r.root_type == "Income":
            sales = flt(r.credit_net, 3)          # income is a credit
        else:
            expenses = flt(r.debit_net, 3)        # expense is a debit

    # the same window one year earlier, for the trend arrow
    prev_from, prev_to = add_months(from_date, -12), add_months(to_date, -12)
    prev = frappe.db.sql(
        """
        SELECT ROUND(SUM(gle.credit - gle.debit), 3) AS sales
        FROM `tabGL Entry` gle
        INNER JOIN `tabAccount` acc ON acc.name = gle.account
        WHERE gle.company = %(company)s AND gle.is_cancelled = 0
          AND gle.posting_date BETWEEN %(from_date)s AND %(to_date)s
          AND acc.root_type = 'Income'
        """,
        {"company": company, "from_date": prev_from, "to_date": prev_to},
        as_dict=True,
    )
    prev_sales = flt(prev[0].sales, 3) if prev and prev[0].sales else 0.0

    profit = flt(sales - expenses, 3)
    return {
        "sales": sales,
        "expenses": expenses,
        "profit": profit,
        "margin_pct": round(profit / sales * 100, 1) if sales else 0.0,
        "sales_prev_year": prev_sales,
        "sales_growth_pct": (
            round((sales - prev_sales) / prev_sales * 100, 1) if prev_sales else None
        ),
    }


def _money_position(company, as_on):
    """Cash in hand, bank, and the total actually available - balances, not movements.

    Read as at the end of the period rather than for the period: an opening balance is money
    you have, and a dashboard showing only the period's movement would tell a business with a
    full bank account that it had none.
    """
    accounts = _money_accounts(company)
    if not accounts:
        return {"cash": 0.0, "bank": 0.0, "total": 0.0, "accounts": [], "negative": []}

    balances = frappe.db.sql(
        """
        SELECT gle.account AS account, ROUND(SUM(gle.debit - gle.credit), 3) AS balance
        FROM `tabGL Entry` gle
        WHERE gle.company = %(company)s AND gle.is_cancelled = 0
          AND gle.posting_date <= %(as_on)s AND gle.account IN %(accounts)s
        GROUP BY gle.account
        """,
        {"company": company, "as_on": as_on, "accounts": tuple(a.name for a in accounts)},
        as_dict=True,
    )
    by_account = {b.account: flt(b.balance, 3) for b in balances}

    detail, cash, bank = [], 0.0, 0.0
    for a in accounts:
        bal = by_account.get(a.name, 0.0)
        if a.account_type == "Cash":
            cash += bal
        else:
            bank += bal
        detail.append({
            "account": a.name,
            "label": a.account_name or a.name,
            "type": a.account_type,
            "balance": bal,
        })

    detail.sort(key=lambda d: -abs(d["balance"]))
    return {
        "cash": flt(cash, 3),
        "bank": flt(bank, 3),
        "total": flt(cash + bank, 3),
        "accounts": detail,
        # an account in overdraft is worth calling out rather than netting away silently
        "negative": [d for d in detail if d["balance"] < 0],
    }


# ── trends ────────────────────────────────────────────────────────────────────

def _trend(company, from_date, to_date, granularity, cost_center):
    params = {"company": company, "from_date": from_date, "to_date": to_date,
              "fmt": GRANULARITY[granularity]}
    cc = _cc_clause(cost_center, params)

    rows = frappe.db.sql(
        """
        SELECT DATE_FORMAT(gle.posting_date, %(fmt)s) AS bucket,
               MIN(gle.posting_date) AS starts,
               ROUND(SUM(CASE WHEN acc.root_type = 'Income'
                              THEN gle.credit - gle.debit ELSE 0 END), 3) AS sales,
               ROUND(SUM(CASE WHEN acc.root_type = 'Expense'
                              THEN gle.debit - gle.credit ELSE 0 END), 3) AS expenses
        FROM `tabGL Entry` gle
        INNER JOIN `tabAccount` acc ON acc.name = gle.account
        WHERE gle.company = %(company)s AND gle.is_cancelled = 0
          AND gle.posting_date BETWEEN %(from_date)s AND %(to_date)s
          AND acc.root_type IN ('Income', 'Expense')
        """
        + cc
        + " GROUP BY bucket ORDER BY starts",
        params,
        as_dict=True,
    )
    for r in rows:
        r["profit"] = flt(flt(r.sales) - flt(r.expenses), 3)
    return rows


def _expense_breakdown(company, from_date, to_date, cost_center):
    """By account, and rolled up to the parent group, which is what people mean by category."""
    params = {"company": company, "from_date": from_date, "to_date": to_date}
    cc = _cc_clause(cost_center, params)

    rows = frappe.db.sql(
        """
        SELECT gle.account AS account, acc.parent_account AS category,
               ROUND(SUM(gle.debit - gle.credit), 3) AS amount
        FROM `tabGL Entry` gle
        INNER JOIN `tabAccount` acc ON acc.name = gle.account
        WHERE gle.company = %(company)s AND gle.is_cancelled = 0
          AND gle.posting_date BETWEEN %(from_date)s AND %(to_date)s
          AND acc.root_type = 'Expense'
        """
        + cc
        + " GROUP BY gle.account, acc.parent_account HAVING amount <> 0 ORDER BY amount DESC",
        params,
        as_dict=True,
    )

    by_category: dict = {}
    for r in rows:
        label = (r.category or _("Uncategorised")).split(" - ")[0]
        by_category[label] = flt(by_category.get(label, 0.0) + flt(r.amount), 3)

    categories = sorted(
        ({"label": k, "amount": v} for k, v in by_category.items()),
        key=lambda x: -x["amount"],
    )
    return {"accounts": rows[:25], "categories": categories[:12]}


# ── cash flow ─────────────────────────────────────────────────────────────────

def _cashflow(company, from_date, to_date, granularity, mode_of_payment=None):
    """Money In vs Money Out, straight off the cash and bank accounts.

        Money In        = every debit to a Cash or Bank account
        Money Out       = every credit to one
        Net Movement    = In - Out
        Running Balance = opening balance + the net movements so far

    Transfers between two of your own accounts appear on both sides and net to nothing, which
    is correct: moving money from the bank to the till is neither income nor spending.
    """
    accounts = _money_accounts(company)
    empty = {"rows": [], "opening": 0.0, "closing": 0.0, "in": 0.0, "out": 0.0, "net": 0.0}
    if not accounts:
        return empty

    params = {
        "company": company,
        "from_date": from_date,
        "to_date": to_date,
        "accounts": tuple(a.name for a in accounts),
        "fmt": GRANULARITY[granularity],
    }

    mop = ""
    if mode_of_payment:
        # Mode of payment lives on the voucher, not the ledger row, so the filter is applied
        # by naming the vouchers that carry it.
        vouchers = frappe.get_all(
            "Payment Entry",
            filters={"company": company, "docstatus": 1, "mode_of_payment": mode_of_payment},
            pluck="name",
        )
        if not vouchers:
            return dict(empty, note=_("No payment entries use this mode of payment."))
        params["vouchers"] = tuple(vouchers)
        mop = " AND gle.voucher_no IN %(vouchers)s"

    opening = flt(
        frappe.db.sql(
            """SELECT COALESCE(SUM(debit - credit), 0) FROM `tabGL Entry`
               WHERE company = %(company)s AND is_cancelled = 0
                 AND account IN %(accounts)s AND posting_date < %(from_date)s""",
            params,
        )[0][0],
        3,
    )

    rows = frappe.db.sql(
        """
        SELECT DATE_FORMAT(gle.posting_date, %(fmt)s) AS bucket,
               MIN(gle.posting_date) AS starts,
               ROUND(SUM(gle.debit), 3)  AS money_in,
               ROUND(SUM(gle.credit), 3) AS money_out
        FROM `tabGL Entry` gle
        WHERE gle.company = %(company)s AND gle.is_cancelled = 0
          AND gle.account IN %(accounts)s
          AND gle.posting_date BETWEEN %(from_date)s AND %(to_date)s
        """
        + mop
        + " GROUP BY bucket ORDER BY starts",
        params,
        as_dict=True,
    )

    running = opening
    total_in = total_out = 0.0
    for r in rows:
        r["net"] = flt(flt(r.money_in) - flt(r.money_out), 3)
        running = flt(running + r["net"], 3)
        r["running"] = running
        total_in += flt(r.money_in)
        total_out += flt(r.money_out)

    return {
        "rows": rows,
        "opening": opening,
        "closing": running,
        "in": flt(total_in, 3),
        "out": flt(total_out, 3),
        "net": flt(total_in - total_out, 3),
    }


# ── what is owed, both ways ───────────────────────────────────────────────────

def _outstanding(company, as_on):
    """What is owed to the business and by it, as at the period end."""
    p = {"company": company, "as_on": as_on}

    receivable = frappe.db.sql(
        """SELECT COALESCE(SUM(outstanding_amount), 0) total, COUNT(*) cnt
           FROM `tabSales Invoice` WHERE company = %(company)s AND docstatus = 1
             AND posting_date <= %(as_on)s AND outstanding_amount > 0""",
        p, as_dict=True)[0]
    payable = frappe.db.sql(
        """SELECT COALESCE(SUM(outstanding_amount), 0) total, COUNT(*) cnt
           FROM `tabPurchase Invoice` WHERE company = %(company)s AND docstatus = 1
             AND posting_date <= %(as_on)s AND outstanding_amount > 0""",
        p, as_dict=True)[0]
    overdue_r = frappe.db.sql(
        """SELECT COALESCE(SUM(outstanding_amount), 0) total, COUNT(*) cnt
           FROM `tabSales Invoice` WHERE company = %(company)s AND docstatus = 1
             AND outstanding_amount > 0 AND due_date < %(as_on)s""",
        p, as_dict=True)[0]
    overdue_p = frappe.db.sql(
        """SELECT COALESCE(SUM(outstanding_amount), 0) total, COUNT(*) cnt
           FROM `tabPurchase Invoice` WHERE company = %(company)s AND docstatus = 1
             AND outstanding_amount > 0 AND due_date < %(as_on)s""",
        p, as_dict=True)[0]

    top_r = frappe.get_all(
        "Sales Invoice",
        filters={"company": company, "docstatus": 1, "outstanding_amount": [">", 0]},
        fields=["name", "customer", "outstanding_amount", "due_date"],
        order_by="outstanding_amount desc", limit=8,
    )
    top_p = frappe.get_all(
        "Purchase Invoice",
        filters={"company": company, "docstatus": 1, "outstanding_amount": [">", 0]},
        fields=["name", "supplier", "outstanding_amount", "due_date"],
        order_by="outstanding_amount desc", limit=8,
    )

    return {
        "receivable": flt(receivable.total, 3),
        "receivable_count": cint(receivable.cnt),
        "receivable_overdue": flt(overdue_r.total, 3),
        "receivable_overdue_count": cint(overdue_r.cnt),
        "payable": flt(payable.total, 3),
        "payable_count": cint(payable.cnt),
        "payable_overdue": flt(overdue_p.total, 3),
        "payable_overdue_count": cint(overdue_p.cnt),
        "top_receivable": top_r,
        "top_payable": top_p,
    }


# ── things worth noticing ─────────────────────────────────────────────────────

def _insights(company, from_date, to_date, cost_center):
    params = {"company": company, "from_date": from_date, "to_date": to_date}
    cc = _cc_clause(cost_center, params)

    best_month = frappe.db.sql(
        """
        SELECT DATE_FORMAT(gle.posting_date, '%%Y-%%m') AS bucket,
               ROUND(SUM(gle.credit - gle.debit), 3) AS sales
        FROM `tabGL Entry` gle
        INNER JOIN `tabAccount` acc ON acc.name = gle.account
        WHERE gle.company = %(company)s AND gle.is_cancelled = 0
          AND acc.root_type = 'Income'
          AND gle.posting_date BETWEEN %(from_date)s AND %(to_date)s
        GROUP BY bucket ORDER BY sales DESC LIMIT 1
        """,
        {"company": company, "from_date": from_date, "to_date": to_date},
        as_dict=True,
    )

    top_expense = frappe.db.sql(
        """
        SELECT gle.account AS account, ROUND(SUM(gle.debit - gle.credit), 3) AS amount
        FROM `tabGL Entry` gle
        INNER JOIN `tabAccount` acc ON acc.name = gle.account
        WHERE gle.company = %(company)s AND gle.is_cancelled = 0
          AND acc.root_type = 'Expense'
          AND gle.posting_date BETWEEN %(from_date)s AND %(to_date)s
        """
        + cc
        + " GROUP BY gle.account ORDER BY amount DESC LIMIT 5",
        params,
        as_dict=True,
    )

    biggest_sales = frappe.get_all(
        "Sales Invoice",
        filters={"company": company, "docstatus": 1,
                 "posting_date": ["between", [from_date, to_date]]},
        fields=["name", "customer", "posting_date", "base_grand_total"],
        order_by="base_grand_total desc", limit=5,
    )
    biggest_purchases = frappe.get_all(
        "Purchase Invoice",
        filters={"company": company, "docstatus": 1,
                 "posting_date": ["between", [from_date, to_date]]},
        fields=["name", "supplier", "posting_date", "base_grand_total"],
        order_by="base_grand_total desc", limit=5,
    )

    return {
        "best_month": best_month[0] if best_month else None,
        "top_expenses": top_expense,
        "biggest_sales": biggest_sales,
        "biggest_purchases": biggest_purchases,
    }


# ── data quality: reported, never corrected ───────────────────────────────────

def _data_quality(company, from_date, to_date):
    """Flag what looks wrong. Nothing here changes a single row.

    These are posted accounting entries. Merging what looks like a duplicate, or filling in a
    blank, would put the dashboard out of step with the ledger and with the Trial Balance the
    accountant signs. Each finding names the documents so a person can judge, and correct them
    at source where the correction is recorded.
    """
    findings = []
    p = {"company": company, "from_date": from_date, "to_date": to_date}

    dupes = frappe.db.sql(
        """
        SELECT customer, posting_date, ROUND(base_grand_total, 3) amt, COUNT(*) n,
               GROUP_CONCAT(name ORDER BY name SEPARATOR ', ') docs
        FROM `tabSales Invoice`
        WHERE company = %(company)s AND docstatus = 1 AND is_return = 0
          AND posting_date BETWEEN %(from_date)s AND %(to_date)s
        GROUP BY customer, posting_date, amt HAVING n > 1
        ORDER BY n DESC, amt DESC LIMIT 10
        """,
        p, as_dict=True)
    if dupes:
        findings.append({
            "key": "duplicate_sales",
            "severity": "warning",
            "title": _("Possible duplicate sales invoices"),
            "detail": _("Same customer, same day, same amount. Often genuine repeat business, "
                        "so check before assuming otherwise."),
            "count": sum(cint(d.n) for d in dupes),
            "rows": [{"label": "%s - %s - %s" % (d.customer, d.posting_date, d.amt),
                      "value": d.docs} for d in dupes],
        })

    no_mop = frappe.db.sql(
        """SELECT COUNT(*) n, ROUND(COALESCE(SUM(base_paid_amount), 0), 3) amt
           FROM `tabPayment Entry`
           WHERE company = %(company)s AND docstatus = 1
             AND IFNULL(mode_of_payment, '') = ''
             AND posting_date BETWEEN %(from_date)s AND %(to_date)s""",
        p, as_dict=True)[0]
    if cint(no_mop.n):
        findings.append({
            "key": "payment_without_mode",
            "severity": "warning",
            "title": _("Payments with no mode of payment"),
            "detail": _("These move real money but cannot be split by cash, card or transfer, "
                        "so any report grouped by payment mode is short by this much."),
            "count": cint(no_mop.n),
            "amount": flt(no_mop.amt, 3),
        })

    unnamed = frappe.db.sql(
        """SELECT COUNT(*) n FROM `tabGL Entry` gle
           INNER JOIN `tabAccount` acc ON acc.name = gle.account
           WHERE gle.company = %(company)s AND gle.is_cancelled = 0
             AND gle.posting_date BETWEEN %(from_date)s AND %(to_date)s
             AND acc.account_type IN ('Receivable', 'Payable')
             AND IFNULL(gle.party, '') = ''""",
        p, as_dict=True)[0]
    if cint(unnamed.n):
        findings.append({
            "key": "party_less_ledger",
            "severity": "danger",
            "title": _("Receivable or payable postings with no party"),
            "detail": _("A debtor or creditor line with nobody attached never appears on a "
                        "statement and cannot be collected or paid against."),
            "count": cint(unnamed.n),
        })

    future = frappe.db.sql(
        """SELECT COUNT(*) n FROM `tabGL Entry`
           WHERE company = %(company)s AND is_cancelled = 0 AND posting_date > %(today)s""",
        {"company": company, "today": nowdate()}, as_dict=True)[0]
    if cint(future.n):
        findings.append({
            "key": "future_dated",
            "severity": "info",
            "title": _("Entries dated in the future"),
            "detail": _("Legitimate for post-dated cheques and accruals; worth a look if not."),
            "count": cint(future.n),
        })

    zero = frappe.db.sql(
        """SELECT COUNT(*) n FROM `tabSales Invoice`
           WHERE company = %(company)s AND docstatus = 1
             AND posting_date BETWEEN %(from_date)s AND %(to_date)s
             AND base_grand_total = 0 AND is_return = 0""",
        p, as_dict=True)[0]
    if cint(zero.n):
        findings.append({
            "key": "zero_value_sales",
            "severity": "info",
            "title": _("Sales invoices with a zero total"),
            "count": cint(zero.n),
            "detail": _("Samples and write-offs look like this, so not automatically wrong."),
        })

    return {"findings": findings, "checked": 5}


@frappe.whitelist()
def get_filter_options(company=None):
    """Values for the dashboard's own filters."""
    company = _company(company)
    return {
        "companies": frappe.get_all("Company", pluck="name"),
        "cost_centers": frappe.get_all(
            "Cost Center", filters={"company": company, "is_group": 0}, pluck="name"
        ),
        "modes_of_payment": frappe.get_all("Mode of Payment", pluck="name"),
        "granularity": list(GRANULARITY),
    }
