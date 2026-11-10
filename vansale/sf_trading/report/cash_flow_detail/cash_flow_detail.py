# apps/vansale/vansale/sf_trading/report/cash_flow_detail/cash_flow_detail.py
"""Cash Flow Detail - what is behind a figure on the Cash Flow summary.

Reached by clicking a period on Cash Flow Money In vs Money Out, which passes its own dates
through, so the detail opens already showing that period and nothing else. It can also be run
on its own for any range.

Five readings of the same money, chosen with Group By:

    Transactions        one row per ledger movement, with a running balance
    By Party            who it went to and came from
    By Voucher Type     which kind of document moved it
    By Account          which till or bank account it moved through
    By Mode of Payment  cash, card, transfer, cheque

Direction narrows to money in or money out alone, which is what a click on one of those
columns is really asking about.

The account, mode-of-payment and internal-transfer filters are the same code the summary uses,
imported rather than copied, so the detail can never add up to something the summary does not.
"""

import frappe
from frappe import _
from frappe.utils import add_months, cint, flt, getdate, nowdate

from vansale.sf_trading.report.cash_flow_money_in_vs_money_out.cash_flow_money_in_vs_money_out import (
    _message,
    _money_accounts,
    _opening,
)

ROW_CAP = 5000


def execute(filters=None):
    filters = frappe._dict(filters or {})
    company = filters.company or frappe.defaults.get_user_default("Company")
    if not company:
        frappe.throw(_("Please choose a company."))

    to_date = getdate(filters.to_date or nowdate())
    from_date = getdate(filters.from_date or add_months(to_date, -1))
    if from_date > to_date:
        frappe.throw(_("From Date is after To Date."))

    accounts = _money_accounts(company, filters.get("account"))
    if not accounts:
        frappe.msgprint(_("No Cash or Bank accounts found for {0}.").format(company))
        return _txn_columns(company), []

    group_by = filters.get("group_by") or "Transactions"
    if group_by == "Transactions":
        opening = _opening(company, accounts, from_date)
        return _transactions(company, accounts, from_date, to_date, filters, opening)
    return _grouped(company, accounts, from_date, to_date, filters, group_by)


def _transactions(company, accounts, from_date, to_date, filters, opening):
    """Every ledger movement on a money account, with a running balance.

    Capped: a full year on this company is over thirty thousand rows and the browser will not
    thank anybody for that. When the cap bites the report says so and names the figure, rather
    than quietly showing a partial answer that looks complete.
    """
    params = {
        "company": company,
        "accounts": tuple(accounts),
        "from_date": from_date,
        "to_date": to_date,
        "cap": ROW_CAP + 1,
    }
    where, params = _voucher_filters(filters, params)

    rows = frappe.db.sql(
        "SELECT gle.posting_date, gle.voucher_type, gle.voucher_no, gle.account,"
        "       gle.party_type, gle.party, gle.against, gle.remarks, gle.cost_center,"
        "       gle.debit AS money_in, gle.credit AS money_out"
        " FROM `tabGL Entry` gle"
        " WHERE gle.company = %(company)s AND gle.is_cancelled = 0"
        "   AND gle.account IN %(accounts)s"
        "   AND gle.posting_date BETWEEN %(from_date)s AND %(to_date)s"
        + where +
        " ORDER BY gle.posting_date, gle.creation LIMIT %(cap)s",
        params,
        as_dict=True,
    )

    truncated = len(rows) > ROW_CAP
    rows = rows[:ROW_CAP]

    modes = _modes_for(rows)
    running, total_in, total_out = opening, 0.0, 0.0
    data = [{
        "period": _("Opening Balance"), "running": opening, "is_opening": 1,
        "money_in": None, "money_out": None, "net": None,
    }]
    for r in rows:
        running = flt(running + flt(r.money_in) - flt(r.money_out), 3)
        total_in += flt(r.money_in)
        total_out += flt(r.money_out)
        data.append({
            "posting_date": r.posting_date,
            "voucher_type": r.voucher_type,
            "voucher_no": r.voucher_no,
            "account": r.account,
            "party": r.party or "",
            "against": r.against or "",
            "mode_of_payment": modes.get(r.voucher_no, ""),
            "remarks": (r.remarks or "")[:140],
            "money_in": flt(r.money_in, 3),
            "money_out": flt(r.money_out, 3),
            "net": flt(flt(r.money_in) - flt(r.money_out), 3),
            "running": running,
        })

    data.append({
        "period": _("Total"), "voucher_type": _("Total"),
        "money_in": flt(total_in, 3), "money_out": flt(total_out, 3),
        "net": flt(total_in - total_out, 3), "running": running, "is_total": 1,
    })

    msg = _message(accounts, filters)
    if truncated:
        msg += (
            "<div style='margin-top:6px;padding:8px 10px;border-left:3px solid #b71c1c;"
            "background:#fdecea'>"
            + _("Showing the first {0} transactions of this period; there are more. Narrow the "
                "dates, pick a single account, or use one of the By views to see everything "
                "summarised.").format(ROW_CAP)
            + "</div>"
        )

    summary = [
        {"label": _("Opening Balance"), "value": opening, "datatype": "Currency", "indicator": "Blue"},
        {"label": _("Money In"), "value": flt(total_in, 3), "datatype": "Currency", "indicator": "Green"},
        {"label": _("Money Out"), "value": flt(total_out, 3), "datatype": "Currency", "indicator": "Red"},
        {"label": _("Transactions"), "value": len(rows), "datatype": "Int"},
        {"label": _("Closing Balance"), "value": running, "datatype": "Currency",
         "indicator": "Blue" if running >= 0 else "Red"},
    ]
    return _txn_columns(company), data, msg, None, summary


def _grouped(company, accounts, from_date, to_date, filters, view):
    """The same money, totalled by whatever the reader is asking about."""
    field = {
        "By Party": "gle.party",
        "By Voucher Type": "gle.voucher_type",
        "By Account": "gle.account",
    }.get(view)
    if not field and view != "By Mode of Payment":
        frappe.throw(_("Unknown grouping: {0}").format(view))

    params = {"company": company, "accounts": tuple(accounts),
              "from_date": from_date, "to_date": to_date}
    where, params = _voucher_filters(filters, params)

    if view == "By Mode of Payment":
        return _by_mode(company, accounts, from_date, to_date, filters, params, where)

    rows = frappe.db.sql(
        "SELECT COALESCE(NULLIF(" + field + ", ''), '" + _("(not set)") + "') AS grp,"
        "       ROUND(SUM(gle.debit), 3) AS money_in,"
        "       ROUND(SUM(gle.credit), 3) AS money_out,"
        "       COUNT(*) AS txns"
        " FROM `tabGL Entry` gle"
        " WHERE gle.company = %(company)s AND gle.is_cancelled = 0"
        "   AND gle.account IN %(accounts)s"
        "   AND gle.posting_date BETWEEN %(from_date)s AND %(to_date)s"
        + where +
        " GROUP BY grp ORDER BY (SUM(gle.debit) + SUM(gle.credit)) DESC",
        params,
        as_dict=True,
    )
    return _finish_grouped(company, rows, view, accounts, filters)


def _by_mode(company, accounts, from_date, to_date, filters, params, where):
    """Mode of payment lives on the Payment Entry, not on the ledger row, so it is joined in.

    Everything that moved money by another route - journals, POS settlements - lands under
    'No payment entry', which on this site is a large number and worth seeing rather than
    hiding.
    """
    rows = frappe.db.sql(
        "SELECT COALESCE(NULLIF(pe.mode_of_payment, ''), '" + _("No payment entry") + "') AS grp,"
        "       ROUND(SUM(gle.debit), 3) AS money_in,"
        "       ROUND(SUM(gle.credit), 3) AS money_out,"
        "       COUNT(*) AS txns"
        " FROM `tabGL Entry` gle"
        " LEFT JOIN `tabPayment Entry` pe"
        "        ON pe.name = gle.voucher_no AND gle.voucher_type = 'Payment Entry'"
        " WHERE gle.company = %(company)s AND gle.is_cancelled = 0"
        "   AND gle.account IN %(accounts)s"
        "   AND gle.posting_date BETWEEN %(from_date)s AND %(to_date)s"
        + where +
        " GROUP BY grp ORDER BY (SUM(gle.debit) + SUM(gle.credit)) DESC",
        params,
        as_dict=True,
    )
    return _finish_grouped(company, rows, "By Mode of Payment", accounts, filters)


def _finish_grouped(company, rows, view, accounts, filters):
    data, total_in, total_out = [], 0.0, 0.0
    for r in rows:
        total_in += flt(r.money_in)
        total_out += flt(r.money_out)
        data.append({
            "group": r.grp,
            "txns": cint(r.txns),
            "money_in": flt(r.money_in, 3),
            "money_out": flt(r.money_out, 3),
            "net": flt(flt(r.money_in) - flt(r.money_out), 3),
        })
    data.append({
        "group": _("Total"), "txns": sum(cint(r.txns) for r in rows),
        "money_in": flt(total_in, 3), "money_out": flt(total_out, 3),
        "net": flt(total_in - total_out, 3), "is_total": 1,
    })

    chart = {
        "data": {
            "labels": [d["group"] for d in data[:-1]][:12],
            "datasets": [
                {"name": _("Money In"), "values": [flt(d["money_in"]) for d in data[:-1]][:12]},
                {"name": _("Money Out"), "values": [flt(d["money_out"]) for d in data[:-1]][:12]},
            ],
        },
        "type": "bar",
        "colors": ["#2e7d32", "#c62828"],
        "fieldtype": "Currency",
    } if len(data) > 1 else None

    summary = [
        {"label": _("Money In"), "value": flt(total_in, 3), "datatype": "Currency", "indicator": "Green"},
        {"label": _("Money Out"), "value": flt(total_out, 3), "datatype": "Currency", "indicator": "Red"},
        {"label": _("Net Movement"), "value": flt(total_in - total_out, 3), "datatype": "Currency",
         "indicator": "Green" if total_in >= total_out else "Red"},
        {"label": _("Groups"), "value": len(rows), "datatype": "Int"},
    ]
    return _grouped_columns(company, view), data, _message(accounts, filters), chart, summary


def _voucher_filters(filters, params):
    """The account / mode-of-payment / internal-transfer / direction filters."""
    where = ""
    direction = filters.get("direction")
    if direction == "Money In":
        where += " AND gle.debit > 0"
    elif direction == "Money Out":
        where += " AND gle.credit > 0"
    if cint(filters.get("exclude_internal_transfers")):
        where += (
            " AND gle.voucher_no NOT IN ("
            "   SELECT x.voucher_no FROM `tabGL Entry` x"
            "   WHERE x.company = %(company)s AND x.is_cancelled = 0"
            "     AND x.account IN %(accounts)s"
            "     AND x.posting_date BETWEEN %(from_date)s AND %(to_date)s"
            "   GROUP BY x.voucher_no HAVING COUNT(DISTINCT x.account) > 1)"
        )
    if filters.get("mode_of_payment"):
        vouchers = frappe.get_all(
            "Payment Entry",
            filters={"company": params["company"], "docstatus": 1,
                     "mode_of_payment": filters.get("mode_of_payment")},
            pluck="name",
        )
        params["vouchers"] = tuple(vouchers) if vouchers else ("__none__",)
        where += " AND gle.voucher_no IN %(vouchers)s"
    return where, params


def _modes_for(rows):
    """Mode of payment for the payment entries among these rows, in one query."""
    names = list({r.voucher_no for r in rows if r.voucher_type == "Payment Entry"})
    if not names:
        return {}
    return {
        r.name: r.mode_of_payment
        for r in frappe.get_all("Payment Entry", filters={"name": ["in", names]},
                                fields=["name", "mode_of_payment"])
    }


def _txn_columns(company):
    currency = frappe.db.get_value("Company", company, "default_currency")
    return [
        {"label": _("Date"), "fieldname": "posting_date", "fieldtype": "Date", "width": 95},
        {"label": _("Type"), "fieldname": "voucher_type", "fieldtype": "Data", "width": 120},
        {"label": _("Voucher"), "fieldname": "voucher_no", "fieldtype": "Dynamic Link",
         "options": "voucher_type", "width": 175},
        {"label": _("Money Account"), "fieldname": "account", "fieldtype": "Link",
         "options": "Account", "width": 180},
        {"label": _("Party"), "fieldname": "party", "fieldtype": "Data", "width": 150},
        {"label": _("Against"), "fieldname": "against", "fieldtype": "Data", "width": 180},
        {"label": _("Mode"), "fieldname": "mode_of_payment", "fieldtype": "Data", "width": 110},
        {"label": _("Money In"), "fieldname": "money_in", "fieldtype": "Currency",
         "options": "currency", "width": 120},
        {"label": _("Money Out"), "fieldname": "money_out", "fieldtype": "Currency",
         "options": "currency", "width": 120},
        {"label": _("Running Balance"), "fieldname": "running", "fieldtype": "Currency",
         "options": "currency", "width": 140},
        {"label": _("Remarks"), "fieldname": "remarks", "fieldtype": "Data", "width": 240},
        {"label": _("Currency"), "fieldname": "currency", "fieldtype": "Data", "width": 1,
         "hidden": 1, "default": currency},
    ]


def _grouped_columns(company, view):
    currency = frappe.db.get_value("Company", company, "default_currency")
    label = {"By Party": _("Party"), "By Voucher Type": _("Voucher Type"),
             "By Account": _("Money Account"), "By Mode of Payment": _("Mode of Payment")}.get(
        view, _("Group"))
    return [
        {"label": label, "fieldname": "group", "fieldtype": "Data", "width": 280},
        {"label": _("Transactions"), "fieldname": "txns", "fieldtype": "Int", "width": 110},
        {"label": _("Money In"), "fieldname": "money_in", "fieldtype": "Currency",
         "options": "currency", "width": 150},
        {"label": _("Money Out"), "fieldname": "money_out", "fieldtype": "Currency",
         "options": "currency", "width": 150},
        {"label": _("Net"), "fieldname": "net", "fieldtype": "Currency",
         "options": "currency", "width": 150},
        {"label": _("Currency"), "fieldname": "currency", "fieldtype": "Data", "width": 1,
         "hidden": 1, "default": currency},
    ]
