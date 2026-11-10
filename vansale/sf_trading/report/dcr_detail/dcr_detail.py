# Copyright (c) 2025, sf_trading and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import add_days, flt, getdate

from vansale.sf_trading.report.dcr_report.dcr_report import (
	RETURN_REFUNDED_CONDITION,
	_return_refunded_condition,
	enforce_user_cost_center,
	get_branch_petty_cash_accounts,
	get_gl_cash_balance,
	get_invoices_with_settlement,
	get_petty_cash_payments,
	split_invoice_settlement,
)


def _doc_link(doctype, name):
	"""Clickable link to a document for Data columns that mix doctypes."""
	from urllib.parse import quote
	route = doctype.lower().replace(" ", "-")
	return f'<a href="/app/{route}/{quote(str(name))}">{name}</a>'


REPORT_TYPES = [
	"Opening Cash Balance",
	"Total Sales",
	"Cash Sales",
	"Bank Sales",
	"Cheque Sales",
	"Credit Sales",
	"Home Credit (Delivery)",
	"Sales Return - Cash",
	"Sales Return - Bank",
	"Sales Return - Cheque",
	"Sales Return - Credit",
	"VAT Collected on Cash Sales",
	"VAT Collected on Bank Sales",
	"VAT Collected on Cheque Sales",
	"VAT Applied on Credit Sales",
	"VAT Applied on Home Credit",
	"VAT Refund on Sales Return",
	"Loyalty / Write Off",
	"Credit Purchase - DIRECT PURCHASE",
	"Cash Received : Credit Sales",
	"Payments-Petty Cash (Approved)",
	"Payments-Petty Cash (UnApproved)",
	"Payments-Petty Cash (Total Payments)",
	"Total Receipt-Petty Cash",
	"Net Cash Movement",
	"Closing Cash Balance",
	"Cash Receipts (Cash Sales)",
	"Bank Sales Receipts",
	"Bank Sales Payments",
	"Internal Transfer (Cash Out)",
	"Internal Transfer (Cash In)",
]


def execute(filters=None):
	if not filters:
		filters = {}
	if not filters.get("report_type"):
		return get_columns("Cash Sales"), []
	if not filters.get("from_date") or not filters.get("to_date"):
		frappe.throw(_("Please select From Date and To Date"))
	if not filters.get("company"):
		frappe.throw(_("Please select a Company"))
	from_date = getdate(filters.get("from_date"))
	to_date = getdate(filters.get("to_date"))
	# From/To can transiently cross while the user is still editing the date
	# filters — show an empty report rather than an interrupting error popup.
	if from_date > to_date:
		return get_columns(filters.get("report_type")), []
	company = filters.get("company")
	cost_center = enforce_user_cost_center(filters.get("cost_center"))
	report_type = filters.get("report_type")
	columns = get_columns(report_type)
	data = get_data_for_type(report_type, from_date, to_date, company, cost_center)
	return columns, data


def get_columns(report_type):
	"""Columns vary by report type."""
	if report_type == "Opening Cash Balance":
		return [
			_("Account") + ":Link/Account:250",
			_("As Of Date") + ":Date:110",
			_("Balance") + ":Currency:150",
		]
	if report_type in ("Closing Cash Balance", "Net Cash Movement"):
		return [
			_("Posting Date") + ":Date:95",
			_("Voucher Type") + ":Data:130",
			_("Voucher") + ":Data:170",
			_("Account") + ":Link/Account:180",
			_("Against") + ":Data:160",
			_("Debit") + ":Currency:105",
			_("Credit") + ":Currency:105",
			_("Balance") + ":Currency:115",
		]
	if report_type == "Total Sales":
		return [
			_("Sales Invoice") + ":Link/Sales Invoice:130",
			_("Posting Date") + ":Date:95",
			_("Customer") + ":Link/Customer:130",
			_("Customer Name") + ":Data:150",
			_("Grand Total") + ":Currency:110",
			_("Cash") + ":Currency:100",
			_("Bank") + ":Currency:100",
			_("Cheque") + ":Currency:100",
			_("Credit / Home Credit") + ":Currency:130",
		]
	if report_type == "Total Receipt-Petty Cash":
		return [
			_("Receipt Type") + ":Data:150",
			_("Document") + ":Data:170",
			_("Posting Date") + ":Date:95",
			_("Party") + ":Data:150",
			_("Mode of Payment") + ":Data:110",
			_("Amount") + ":Currency:110",
		]
	if report_type in ("Cash Sales", "Bank Sales", "Cheque Sales", "Credit Sales", "VAT Collected on Cash Sales", "VAT Collected on Bank Sales", "VAT Collected on Cheque Sales", "VAT Applied on Credit Sales"):
		return [
			_("Sales Invoice") + ":Link/Sales Invoice:120",
			_("Posting Date") + ":Date:100",
			_("Customer") + ":Link/Customer:150",
			_("Customer Name") + ":Data:180",
			_("Net Total") + ":Currency:120",
			_("VAT") + ":Currency:100",
			_("Grand Total") + ":Currency:120",
			_("Discount") + ":Currency:90",
			_("Write Off") + ":Currency:100",
			_("Mode of Payment") + ":Link/Mode of Payment:150",
		]
	if report_type in ("Home Credit (Delivery)", "VAT Applied on Home Credit"):
		return [
			_("Sales Invoice") + ":Link/Sales Invoice:120",
			_("Posting Date") + ":Date:100",
			_("Customer") + ":Link/Customer:150",
			_("Customer Name") + ":Data:180",
			_("Delivery Person") + ":Link/Driver:150",
			_("Net Total") + ":Currency:120",
			_("VAT") + ":Currency:100",
			_("Grand Total") + ":Currency:120",
		]
	if report_type in ("Sales Return - Cash", "Sales Return - Bank", "Sales Return - Cheque", "Sales Return - Credit", "VAT Refund on Sales Return"):
		return [
			_("Sales Invoice") + ":Link/Sales Invoice:120",
			_("Posting Date") + ":Date:100",
			_("Return Against") + ":Link/Sales Invoice:120",
			_("Customer") + ":Link/Customer:150",
			_("Net Total") + ":Currency:120",
			_("VAT") + ":Currency:100",
		]
	if report_type == "Credit Purchase - DIRECT PURCHASE":
		return [
			_("Purchase Invoice") + ":Link/Purchase Invoice:120",
			_("Posting Date") + ":Date:100",
			_("Supplier") + ":Link/Supplier:150",
			_("Supplier Name") + ":Data:180",
			_("Net Total") + ":Currency:120",
			_("VAT") + ":Currency:100",
			_("Grand Total") + ":Currency:120",
		]
	if report_type == "Cash Receipts (Cash Sales)":
		return [
			_("Payment Entry") + ":Link/Payment Entry:120",
			_("Posting Date") + ":Date:100",
			_("Party") + ":Data:150",
			_("Received Amount") + ":Currency:120",
			_("Mode of Payment") + ":Data:120",
			_("Reference") + ":Link/Sales Invoice:120",
		]
	if report_type == "Cash Received : Credit Sales":
		return [
			_("Payment Entry") + ":Link/Payment Entry:130",
			_("Posting Date") + ":Date:100",
			_("Party") + ":Data:150",
			_("Mode of Payment") + ":Data:110",
			_("Type") + ":Data:130",
			_("Sales Invoice(s)") + ":Data:180",
			_("Amount") + ":Currency:120",
		]
	if report_type in ("Payments-Petty Cash (Total Payments)", "Payments-Petty Cash (Approved)", "Payments-Petty Cash (UnApproved)"):
		return [
			_("Document Type") + ":Data:120",
			_("Document") + ":Data:120",
			_("Posting Date") + ":Date:100",
			_("Party") + ":Data:150",
			_("Amount") + ":Currency:120",
			_("Mode of Payment") + ":Data:120",
		]
	if report_type == "Loyalty / Write Off":
		return [
			_("Payment Entry") + ":Link/Payment Entry:140",
			_("Posting Date") + ":Date:100",
			_("Party") + ":Data:150",
			_("Sales Invoice") + ":Link/Sales Invoice:140",
			_("Account") + ":Link/Account:180",
			_("Write Off Amount") + ":Currency:120",
		]
	if report_type == "Bank Sales Receipts":
		return [
			_("Payment Entry") + ":Link/Payment Entry:120",
			_("Posting Date") + ":Date:100",
			_("Party") + ":Data:150",
			_("Received Amount") + ":Currency:120",
			_("Mode of Payment") + ":Data:120",
			_("Reference") + ":Data:120",
		]
	if report_type == "Bank Sales Payments":
		return [
			_("Document Type") + ":Data:120",
			_("Document") + ":Data:120",
			_("Posting Date") + ":Date:100",
			_("Party") + ":Data:150",
			_("Amount") + ":Currency:120",
			_("Mode of Payment") + ":Data:120",
		]
	if report_type in ("Internal Transfer (Cash Out)", "Internal Transfer (Cash In)"):
		return [
			_("Payment Entry") + ":Link/Payment Entry:120",
			_("Posting Date") + ":Date:100",
			_("From Account") + ":Link/Account:150",
			_("To Account") + ":Link/Account:150",
			_("Amount") + ":Currency:120",
		]
	return []


def _base_conditions(from_date, to_date, company, cost_center, date_field="si.posting_date", table_alias="si"):
	conditions = []
	if from_date:
		conditions.append(f" {date_field} >= %(from_date)s")
	if to_date:
		conditions.append(f" {date_field} <= %(to_date)s")
	if company:
		conditions.append(f" {table_alias}.company = %(company)s")
	return " AND ".join(conditions) if conditions else " 1=1 "


def get_data_for_type(report_type, from_date, to_date, company, cost_center):
	params = {"from_date": from_date, "to_date": to_date, "company": company, "cost_center": cost_center}
	if report_type == "Opening Cash Balance":
		return _detail_cash_balance(params, cost_center, opening=True)
	if report_type in ("Closing Cash Balance", "Net Cash Movement"):
		return _detail_closing_movement(params, cost_center)
	if report_type == "Total Sales":
		return _detail_total_sales(params, cost_center)
	if report_type == "Total Receipt-Petty Cash":
		return _detail_total_receipts(params, cost_center)
	if report_type in ("Cash Sales", "VAT Collected on Cash Sales"):
		return _detail_settled_share(params, cost_center, "cash")
	if report_type in ("Bank Sales", "VAT Collected on Bank Sales"):
		return _detail_settled_share(params, cost_center, "bank")
	if report_type in ("Cheque Sales", "VAT Collected on Cheque Sales"):
		return _detail_settled_share(params, cost_center, "cheque")
	if report_type in ("Credit Sales", "VAT Applied on Credit Sales"):
		return _detail_remainder_share(params, cost_center, with_driver=False)
	if report_type in ("Home Credit (Delivery)", "VAT Applied on Home Credit"):
		return _detail_remainder_share(params, cost_center, with_driver=True)
	if report_type == "Sales Return - Cash":
		return _detail_sales_return(params, cost_center, kind="cash")
	if report_type == "Sales Return - Bank":
		return _detail_sales_return(params, cost_center, kind="bank")
	if report_type == "Sales Return - Cheque":
		return _detail_sales_return(params, cost_center, kind="cheque")
	if report_type == "Sales Return - Credit":
		return _detail_sales_return(params, cost_center, kind="credit")
	if report_type == "VAT Refund on Sales Return":
		return _detail_sales_return(params, cost_center, kind="refunded_any")
	if report_type == "Loyalty / Write Off":
		return _detail_write_off(params, cost_center)
	if report_type == "Credit Purchase - DIRECT PURCHASE":
		return _detail_credit_purchase(params, cost_center)
	if report_type == "Cash Received : Credit Sales":
		return _detail_cash_received_credit_sales(params, cost_center)
	if report_type in ("Payments-Petty Cash (Total Payments)", "Payments-Petty Cash (Approved)"):
		return _detail_payments_petty_cash(params, cost_center, docstatus=1)
	if report_type == "Payments-Petty Cash (UnApproved)":
		return _detail_payments_petty_cash(params, cost_center, docstatus=0)
	if report_type == "Cash Receipts (Cash Sales)":
		return _detail_cash_receipts_cash_sales(params, cost_center)
	if report_type == "Bank Sales Receipts":
		return _detail_bank_sales_receipts(params, cost_center)
	if report_type == "Bank Sales Payments":
		return _detail_bank_sales_payments(params, cost_center)
	if report_type == "Internal Transfer (Cash Out)":
		return _detail_internal_transfer_out(params, cost_center)
	if report_type == "Internal Transfer (Cash In)":
		return _detail_internal_transfer_in(params, cost_center)
	return []


def _detail_cash_balance(params, cost_center, opening=True):
	"""Account-wise GL balance of the branch petty cash accounts (or the
	Cash-type fallback) as of the opening/closing date, plus a row for
	still-pending UnApproved petty cash as of that date (no GL entry yet, but
	treated as already gone from the till) — the rows sum to the report's
	Opening/Closing Cash Balance figure exactly."""
	as_of = add_days(getdate(params["from_date"]), -1) if opening else getdate(params["to_date"])
	company = params["company"]
	accounts = get_branch_petty_cash_accounts(company, cost_center)
	p = {"as_of_date": as_of, "company": company, "cost_center": cost_center, "accounts": tuple(accounts) or ("",)}
	conditions = "gle.is_cancelled = 0 AND gle.posting_date <= %(as_of_date)s"
	if company:
		conditions += " AND gle.company = %(company)s"
	if accounts:
		rows = frappe.db.sql("""
			SELECT gle.account, COALESCE(SUM(gle.debit - gle.credit), 0) as balance
			FROM `tabGL Entry` gle
			WHERE {conditions}
				AND gle.account IN %(accounts)s
			GROUP BY gle.account
			ORDER BY gle.account
		""".format(conditions=conditions), p, as_dict=True)
	else:
		cc_condition = " AND gle.cost_center = %(cost_center)s" if cost_center else ""
		rows = frappe.db.sql("""
			SELECT gle.account, COALESCE(SUM(gle.debit - gle.credit), 0) as balance
			FROM `tabGL Entry` gle
			INNER JOIN `tabAccount` acc ON acc.name = gle.account
			WHERE {conditions}
				AND acc.account_type = 'Cash'
				{cc_condition}
			GROUP BY gle.account
			ORDER BY gle.account
		""".format(conditions=conditions, cc_condition=cc_condition), p, as_dict=True)
	out = [[r.account, as_of, flt(r.balance)] for r in rows]
	unapproved = get_petty_cash_payments(None, as_of, company, cost_center, docstatus=0)
	if unapproved:
		out.append([_("Less: UnApproved Petty Cash (pending)"), as_of, -flt(unapproved)])
	return out


def _detail_closing_movement(params, cost_center):
	"""Ledger view of the petty cash account(s): opening balance, every GL entry
	in the period with a running balance, a bridge row for the net change in
	still-pending UnApproved petty cash, and the closing balance — shows
	exactly what moved the cash from (adjusted) opening to (adjusted) closing."""
	from_date = getdate(params["from_date"])
	to_date = getdate(params["to_date"])
	company = params["company"]

	unapproved_open = get_petty_cash_payments(None, add_days(from_date, -1), company, cost_center, docstatus=0)
	unapproved_close = get_petty_cash_payments(None, to_date, company, cost_center, docstatus=0)
	opening = get_gl_cash_balance(add_days(from_date, -1), company, cost_center) - unapproved_open
	closing = get_gl_cash_balance(to_date, company, cost_center) - unapproved_close

	accounts = get_branch_petty_cash_accounts(company, cost_center)
	p = dict(params, accounts=tuple(accounts) or ("",))
	conditions = "gle.is_cancelled = 0 AND gle.posting_date >= %(from_date)s AND gle.posting_date <= %(to_date)s"
	if company:
		conditions += " AND gle.company = %(company)s"
	if accounts:
		account_condition = "gle.account IN %(accounts)s"
		join = ""
	else:
		account_condition = "acc.account_type = 'Cash'"
		if cost_center:
			account_condition += " AND gle.cost_center = %(cost_center)s"
		join = "INNER JOIN `tabAccount` acc ON acc.name = gle.account"
	entries = frappe.db.sql("""
		SELECT gle.posting_date, gle.voucher_type, gle.voucher_no, gle.account, gle.against,
			gle.debit, gle.credit
		FROM `tabGL Entry` gle
		{join}
		WHERE {conditions}
			AND {account_condition}
		ORDER BY gle.posting_date, gle.creation
	""".format(join=join, conditions=conditions, account_condition=account_condition), p, as_dict=True)

	out = [[add_days(from_date, -1), "", "<b>" + _("Opening Balance") + "</b>", "", "", 0, 0, opening]]
	balance = opening
	for e in entries:
		balance += flt(e.debit) - flt(e.credit)
		against = (e.against or "").replace("\n", ", ")
		if len(against) > 60:
			against = against[:57] + "..."
		out.append([
			e.posting_date,
			e.voucher_type,
			_doc_link(e.voucher_type, e.voucher_no),
			e.account,
			against,
			flt(e.debit),
			flt(e.credit),
			balance,
		])
	unapproved_change = unapproved_close - unapproved_open
	if unapproved_change:
		balance -= unapproved_change
		out.append([
			to_date, "", _("Change in UnApproved Petty Cash (pending)"), "", "",
			0, 0, balance,
		])
	out.append([to_date, "", "<b>" + _("Closing Balance") + "</b>", "", "", 0, 0, closing])
	return out


def _detail_total_sales(params, cost_center):
	"""Every invoice in range, once, with its settlement split — the union of
	the five sales rows."""
	out = []
	for r in get_invoices_with_settlement(params["from_date"], params["to_date"], params["company"], cost_center):
		s = split_invoice_settlement(r)
		out.append([
			r.name,
			r.posting_date,
			r.get("customer"),
			r.get("customer_name") or "",
			flt(r.get("base_grand_total")),
			s["cash"],
			s["bank"],
			s["cheque"],
			s["remainder"],
		])
	return out


def _detail_total_receipts(params, cost_center):
	"""All cash into the till: cash-mode Payment Entries (same-day sales receipts
	and later credit collections) plus POS cash rows on invoices."""
	cond = _base_conditions(params["from_date"], params["to_date"], params["company"], cost_center, "pe.posting_date", "pe")
	cc = " AND pe.cost_center = %(cost_center)s" if cost_center else ""
	pe_rows = frappe.db.sql("""
		SELECT pe.name, pe.posting_date, pe.party, pe.mode_of_payment, per.allocated_amount as amount,
			CASE WHEN pe.posting_date <= si.posting_date THEN 'Cash Sales Receipt' ELSE 'Credit Collection' END as receipt_type
		FROM `tabPayment Entry` pe
		INNER JOIN `tabPayment Entry Reference` per ON per.parent = pe.name
		INNER JOIN `tabMode of Payment` mop ON mop.name = pe.mode_of_payment
		INNER JOIN `tabSales Invoice` si ON si.name = per.reference_name AND per.reference_doctype = 'Sales Invoice'
		WHERE pe.docstatus = 1 AND pe.payment_type = 'Receive' AND """ + cond + """
		AND per.reference_doctype = 'Sales Invoice' AND mop.type = 'Cash'
		""" + cc + """
		ORDER BY pe.posting_date, pe.name
	""", params, as_dict=True)

	si_cond = _base_conditions(params["from_date"], params["to_date"], params["company"], cost_center, "si.posting_date")
	si_cc = " AND EXISTS (SELECT 1 FROM `tabSales Invoice Item` sii WHERE sii.parent = si.name AND sii.cost_center = %(cost_center)s)" if cost_center else ""
	sip_rows = frappe.db.sql("""
		SELECT si.name, si.posting_date, si.customer_name as party, sip.mode_of_payment, sip.base_amount as amount
		FROM `tabSales Invoice` si
		INNER JOIN `tabSales Invoice Payment` sip ON sip.parent = si.name
		INNER JOIN `tabMode of Payment` mop ON mop.name = sip.mode_of_payment
		WHERE si.docstatus = 1 AND si.is_return = 0 AND """ + si_cond + """
		AND mop.type = 'Cash'
		""" + si_cc + """
		ORDER BY si.posting_date, si.name
	""", params, as_dict=True)

	out = []
	for r in pe_rows:
		out.append([_(r.receipt_type), _doc_link("Payment Entry", r.name), r.posting_date, r.get("party") or "", r.get("mode_of_payment") or "", flt(r.amount)])
	for r in sip_rows:
		out.append([_("POS Payment"), _doc_link("Sales Invoice", r.name), r.posting_date, r.get("party") or "", r.get("mode_of_payment") or "", flt(r.amount)])
	out.sort(key=lambda x: (x[2], x[1]))
	return out


def _scaled_si_row(r, share, write_off=0, mode=None):
	return [
		r.name,
		r.posting_date,
		r.get("customer"),
		r.get("customer_name") or "",
		flt(r.get("base_net_total")) * share,
		flt(r.get("vat_amount")) * share,
		flt(r.get("grand_total")) * share,
		flt(r.get("discount")) * share,
		flt(write_off),
		mode or "",
	]


def _detail_settled_share(params, cost_center, kind):
	"""Invoices with a settled portion of the given kind (cash/bank/cheque),
	scaled to that portion — same math as the summary rows. The Write Off
	column is the part of Grand Total that rode on a deduction rather than
	becoming physical money (Net Total + VAT - Write Off = real Income). Mode
	of Payment lists every mode of that kind that contributed (split payments
	can involve more than one)."""
	out = []
	for r in get_invoices_with_settlement(params["from_date"], params["to_date"], params["company"], cost_center):
		s = split_invoice_settlement(r)
		if s["total"] <= 0:
			continue
		share = s[kind] / s["total"]
		if share > 0:
			out.append(_scaled_si_row(r, share, s.get(kind + "_write_off", 0), r.get(kind + "_modes")))
	return out


def _detail_remainder_share(params, cost_center, with_driver):
	"""Invoices with an unsettled remainder: driver set = Home Credit,
	otherwise Credit Sales. Scaled to the remainder portion."""
	out = []
	for r in get_invoices_with_settlement(params["from_date"], params["to_date"], params["company"], cost_center):
		s = split_invoice_settlement(r)
		if s["total"] <= 0 or s["remainder"] <= 0:
			continue
		has_driver = bool((r.custom_driver or "").strip())
		if has_driver != with_driver:
			continue
		share = s["remainder"] / s["total"]
		if with_driver:
			out.append([
				r.name,
				r.posting_date,
				r.get("customer"),
				r.get("customer_name") or "",
				r.get("custom_driver") or "",
				flt(r.get("base_net_total")) * share,
				flt(r.get("vat_amount")) * share,
				flt(r.get("grand_total")) * share,
			])
		else:
			out.append(_scaled_si_row(r, share))
	return out


def _detail_sales_return(params, cost_center, kind):
	"""kind='cash'/'bank'/'cheque': returns refunded via that mode.
	kind='credit': unrefunded returns. kind='refunded_any': every refunded
	return regardless of mode (used by the combined VAT Refund drill-down)."""
	cond = _base_conditions(params["from_date"], params["to_date"], params["company"], cost_center, "si.posting_date")
	cc = " AND EXISTS (SELECT 1 FROM `tabSales Invoice Item` sii WHERE sii.parent = si.name AND sii.cost_center = %(cost_center)s)" if cost_center else ""
	if kind == "credit":
		return_condition = "NOT " + RETURN_REFUNDED_CONDITION
	elif kind == "refunded_any":
		return_condition = RETURN_REFUNDED_CONDITION
	else:
		return_condition = _return_refunded_condition(kind)
	sql = """
		SELECT si.name, si.posting_date, si.return_against, si.customer,
			ABS(si.base_net_total) as base_net_total, ABS(si.total_taxes_and_charges) as total_taxes_and_charges
		FROM `tabSales Invoice` si
		WHERE si.docstatus = 1 AND si.is_return = 1 AND """ + cond + """
		AND """ + return_condition + """
		""" + cc + """
		ORDER BY si.posting_date, si.name
	"""
	rows = frappe.db.sql(sql, params, as_dict=True)
	return [[r.name, r.posting_date, r.return_against, r.get("customer"), flt(r.base_net_total), flt(r.total_taxes_and_charges)] for r in rows]


def _detail_write_off(params, cost_center):
	"""Every Payment Entry deduction row on a Receive PE, any account."""
	cond = _base_conditions(params["from_date"], params["to_date"], params["company"], cost_center, "pe.posting_date", "pe")
	cc = " AND COALESCE(ded.cost_center, pe.cost_center) = %(cost_center)s" if cost_center else ""
	sql = """
		SELECT pe.name, pe.posting_date, pe.party, ded.account, ded.amount,
			(SELECT wo_per.reference_name FROM `tabPayment Entry Reference` wo_per
			 WHERE wo_per.parent = pe.name AND wo_per.reference_doctype = 'Sales Invoice' LIMIT 1) as reference_name
		FROM `tabPayment Entry Deduction` ded
		INNER JOIN `tabPayment Entry` pe ON pe.name = ded.parent
		WHERE pe.docstatus = 1 AND pe.payment_type = 'Receive' AND """ + cond + """
		""" + cc + """
		ORDER BY pe.posting_date, pe.name
	"""
	rows = frappe.db.sql(sql, params, as_dict=True)
	return [[r.name, r.posting_date, r.get("party") or "", r.get("reference_name") or "", r.account, flt(r.amount)] for r in rows]


def _detail_credit_purchase(params, cost_center):
	cond = _base_conditions(params["from_date"], params["to_date"], params["company"], cost_center, "pi.posting_date", "pi")
	cc = " AND pii.cost_center = %(cost_center)s" if cost_center else ""
	sql = """
		SELECT pi.name, pi.posting_date, pi.supplier, pi.supplier_name,
			pi.net_total, pi.total_taxes_and_charges, pi.grand_total
		FROM `tabPurchase Invoice` pi
		LEFT JOIN `tabPurchase Invoice Item` pii ON pii.parent = pi.name
		WHERE pi.docstatus = 1 AND """ + cond + """
		""" + cc + """
		GROUP BY pi.name, pi.posting_date, pi.supplier, pi.supplier_name, pi.net_total, pi.total_taxes_and_charges, pi.grand_total
		ORDER BY pi.posting_date, pi.name
	"""
	rows = frappe.db.sql(sql, params, as_dict=True)
	return [[r.name, r.posting_date, r.get("supplier"), r.get("supplier_name") or "", flt(r.net_total), flt(r.total_taxes_and_charges), flt(r.grand_total)] for r in rows]


def _detail_cash_received_credit_sales(params, cost_center):
	"""One row per Payment Entry: its actual received_amount attributed to
	credit-collection references (share method, matching
	get_cash_received_credit_sales) labelled "Credit Collection", plus any
	advance/unallocated portion of a Cash-mode Receive PE labelled "Advance" —
	together these sum exactly to the summary row."""
	cond = _base_conditions(params["from_date"], params["to_date"], params["company"], cost_center, "pe.posting_date", "pe")
	cc = " AND pe.cost_center = %(cost_center)s" if cost_center else ""

	collection_rows = frappe.db.sql("""
		SELECT pe.name, pe.posting_date, pe.party, pe.received_amount, pe.mode_of_payment,
			GROUP_CONCAT(DISTINCT per.reference_name ORDER BY per.reference_name SEPARATOR ', ') as refs,
			SUM(per.allocated_amount) as total_alloc,
			SUM(CASE WHEN si.posting_date < pe.posting_date THEN per.allocated_amount ELSE 0 END) as credit_alloc
		FROM `tabPayment Entry` pe
		INNER JOIN `tabPayment Entry Reference` per ON per.parent = pe.name
		INNER JOIN `tabMode of Payment` mop ON mop.name = pe.mode_of_payment
		INNER JOIN `tabSales Invoice` si ON si.name = per.reference_name AND per.reference_doctype = 'Sales Invoice'
		WHERE pe.docstatus = 1 AND pe.payment_type = 'Receive' AND """ + cond + """
		AND per.reference_doctype = 'Sales Invoice' AND mop.type = 'Cash'
		""" + cc + """
		GROUP BY pe.name, pe.posting_date, pe.party, pe.received_amount, pe.mode_of_payment
		ORDER BY pe.posting_date, pe.name
	""", params, as_dict=True)

	advance_rows = frappe.db.sql("""
		SELECT pe.name, pe.posting_date, pe.party, pe.received_amount, pe.mode_of_payment,
			COALESCE((SELECT SUM(per.allocated_amount) FROM `tabPayment Entry Reference` per
				WHERE per.parent = pe.name AND per.reference_doctype = 'Sales Invoice'), 0) as total_alloc
		FROM `tabPayment Entry` pe
		INNER JOIN `tabMode of Payment` mop ON mop.name = pe.mode_of_payment
		WHERE pe.docstatus = 1 AND pe.payment_type = 'Receive' AND """ + cond + """
		AND mop.type = 'Cash'
		""" + cc + """
		ORDER BY pe.posting_date, pe.name
	""", params, as_dict=True)

	je_cond = _base_conditions(params["from_date"], params["to_date"], params["company"], cost_center, "je.posting_date", "je")
	je_cc = " AND jea.cost_center = %(cost_center)s" if cost_center else ""
	je_rows = frappe.db.sql("""
		SELECT jea.parent as name, je.posting_date, jea.party, jea.debit as amount, jea.reference_name as si_name
		FROM `tabJournal Entry Account` jea
		INNER JOIN `tabJournal Entry` je ON je.name = jea.parent
		INNER JOIN `tabAccount` acc ON acc.name = jea.account
		INNER JOIN `tabSales Invoice` si ON si.name = jea.reference_name
		WHERE je.docstatus = 1 AND """ + je_cond + """
		AND jea.reference_type = 'Sales Invoice' AND acc.account_type = 'Cash'
		AND si.posting_date < je.posting_date
		""" + je_cc + """
		ORDER BY je.posting_date, jea.parent
	""", params, as_dict=True)

	out = []
	for r in collection_rows:
		total_alloc = flt(r.total_alloc)
		share = (flt(r.credit_alloc) / total_alloc) if total_alloc else 0
		if share <= 0:
			continue
		out.append([r.name, r.posting_date, r.get("party") or "", r.get("mode_of_payment") or "",
			_("Credit Collection"), r.get("refs") or "", flt(r.received_amount) * share])
	for r in advance_rows:
		advance = flt(r.received_amount) - flt(r.total_alloc)
		if advance > 0.0001:
			out.append([r.name, r.posting_date, r.get("party") or "", r.get("mode_of_payment") or "",
				_("Advance"), "", advance])
	for r in je_rows:
		out.append([r.name, r.posting_date, r.get("party") or "", _("Journal Entry"),
			_("Credit Collection (JE)"), r.get("si_name") or "", flt(r.amount)])
	out.sort(key=lambda x: (x[1], x[0]))
	return out


def _detail_cash_receipts_cash_sales(params, cost_center):
	cond = _base_conditions(params["from_date"], params["to_date"], params["company"], cost_center, "pe.posting_date", "pe")
	cc = " AND pe.cost_center = %(cost_center)s" if cost_center else ""
	sql = """
		SELECT pe.name, pe.posting_date, pe.party, pe.received_amount, pe.mode_of_payment, per.reference_name
		FROM `tabPayment Entry` pe
		INNER JOIN `tabPayment Entry Reference` per ON per.parent = pe.name
		INNER JOIN `tabMode of Payment` mop ON mop.name = pe.mode_of_payment
		INNER JOIN `tabSales Invoice` si ON si.name = per.reference_name AND per.reference_doctype = 'Sales Invoice'
		WHERE pe.docstatus = 1 AND pe.payment_type = 'Receive' AND """ + cond + """
		AND per.reference_doctype = 'Sales Invoice' AND pe.posting_date <= si.posting_date AND mop.type = 'Cash'
		""" + cc + """
		ORDER BY pe.posting_date, pe.name
	"""
	rows = frappe.db.sql(sql, params, as_dict=True)
	return [[r.name, r.posting_date, r.get("party") or "", flt(r.received_amount), r.get("mode_of_payment") or "", r.get("reference_name") or ""] for r in rows]


def _detail_payments_petty_cash(params, cost_center, docstatus=1):
	params = dict(params, docstatus=docstatus)
	# Branch petty cash accounts — fallback match for PE/PI (same accounts used
	# for the JE/Internal Transfer legs below) so a payment posted straight to
	# the branch's petty cash account still counts even when Mode of Payment is
	# blank or not typed "Cash".
	accounts = get_branch_petty_cash_accounts(params["company"], cost_center)
	params["accounts"] = tuple(accounts) or ("",)
	cond = _base_conditions(params["from_date"], params["to_date"], params["company"], cost_center, "pe.posting_date", "pe")
	# The cost center filter only makes sense for the Mode-of-Payment match: a
	# "Cash" typed Mode of Payment doesn't identify a branch by itself, so we
	# need the row's own cost center to know which branch it belongs to. An
	# account match needs no such filter — the account itself is branch-specific
	# — so it counts even when the row's own cost center field was left blank.
	# When no branch account resolved at all (no cost center, or a cost center
	# with no Branch Configuration), fall back to any account of type "Cash" —
	# same fallback used for the JE/Internal Transfer legs and the Cash Balance
	# rows — so this still surfaces in a company-wide (no cost center) run.
	pe_cc = " AND pe.cost_center = %(cost_center)s" if cost_center else ""
	if accounts:
		pe_acc_join = ""
		pe_account_condition = "pe.paid_from IN %(accounts)s"
	else:
		pe_acc_join = "LEFT JOIN `tabAccount` acc_pe ON acc_pe.name = pe.paid_from"
		pe_account_condition = "acc_pe.account_type = 'Cash'"
		if cost_center:
			pe_account_condition += " AND pe.cost_center = %(cost_center)s"
	# Payment Entry (Pay, Cash OR paid from a petty cash account, party type
	# Supplier — references not required)
	sql_pe = """
		SELECT 'Payment Entry' as doctype, pe.name, pe.posting_date, pe.party, pe.paid_amount, pe.mode_of_payment
		FROM `tabPayment Entry` pe
		LEFT JOIN `tabMode of Payment` mop ON mop.name = pe.mode_of_payment
		""" + pe_acc_join + """
		WHERE pe.docstatus = %(docstatus)s AND """ + cond + """
		AND pe.payment_type = 'Pay' AND pe.party_type = 'Supplier'
		AND ((mop.type = 'Cash' """ + pe_cc + """) OR """ + pe_account_condition + """)
		ORDER BY pe.posting_date, pe.name
	"""
	rows_pe = frappe.db.sql(sql_pe, params, as_dict=True)
	# Purchase Invoice (is_paid, Cash OR paid into a petty cash account)
	pi_cond = _base_conditions(params["from_date"], params["to_date"], params["company"], cost_center, "pi.posting_date", "pi")
	pi_cc = " AND pi.cost_center = %(cost_center)s" if cost_center else ""
	if accounts:
		pi_acc_join = ""
		pi_account_condition = "pi.cash_bank_account IN %(accounts)s"
	else:
		pi_acc_join = "LEFT JOIN `tabAccount` acc_pi ON acc_pi.name = pi.cash_bank_account"
		pi_account_condition = "acc_pi.account_type = 'Cash'"
		if cost_center:
			pi_account_condition += " AND pi.cost_center = %(cost_center)s"
	sql_pi = """
		SELECT 'Purchase Invoice' as doctype, pi.name, pi.posting_date, pi.supplier as party, pi.base_paid_amount as paid_amount, pi.mode_of_payment
		FROM `tabPurchase Invoice` pi
		LEFT JOIN `tabMode of Payment` mop ON mop.name = pi.mode_of_payment
		""" + pi_acc_join + """
		WHERE pi.docstatus = %(docstatus)s AND pi.is_paid = 1 AND """ + pi_cond + """
		AND ((mop.type = 'Cash' """ + pi_cc + """) OR """ + pi_account_condition + """)
		ORDER BY pi.posting_date, pi.name
	"""
	rows_pi = frappe.db.sql(sql_pi, params, as_dict=True)
	# Journal Entries paying out of the branch petty cash account (credit side)
	je_params = dict(params, accounts=tuple(accounts) or ("",))
	je_cond = _base_conditions(params["from_date"], params["to_date"], params["company"], cost_center, "je.posting_date", "je")
	if accounts:
		je_join = ""
		je_account_condition = "jea.account IN %(accounts)s"
	else:
		je_join = "INNER JOIN `tabAccount` acc ON acc.name = jea.account"
		je_account_condition = "acc.account_type = 'Cash'"
		if cost_center:
			je_account_condition += " AND jea.cost_center = %(cost_center)s"
	sql_je = """
		SELECT 'Journal Entry' as doctype, je.name, je.posting_date,
			COALESCE(NULLIF(je.pay_to_recd_from, ''), jea.party, '') as party,
			jea.credit as paid_amount, COALESCE(je.mode_of_payment, '') as mode_of_payment
		FROM `tabJournal Entry Account` jea
		INNER JOIN `tabJournal Entry` je ON je.name = jea.parent
		""" + je_join + """
		WHERE je.docstatus = %(docstatus)s AND """ + je_cond + """
		AND jea.credit > 0
		AND """ + je_account_condition + """
		ORDER BY je.posting_date, je.name
	"""
	rows_je = frappe.db.sql(sql_je, je_params, as_dict=True)
	# Internal Transfer Payment Entries taking cash out of the petty cash account
	if accounts:
		it_join = ""
		it_account_condition = "pe_it.paid_from IN %(accounts)s"
	else:
		it_join = "INNER JOIN `tabAccount` acc_it ON acc_it.name = pe_it.paid_from"
		it_account_condition = "acc_it.account_type = 'Cash'"
		if cost_center:
			it_account_condition += " AND pe_it.cost_center = %(cost_center)s"
	it_cond = _base_conditions(params["from_date"], params["to_date"], params["company"], cost_center, "pe_it.posting_date", "pe_it")
	sql_it = """
		SELECT pe_it.name, pe_it.posting_date, pe_it.paid_to as party,
			pe_it.paid_amount, COALESCE(pe_it.mode_of_payment, '') as mode_of_payment
		FROM `tabPayment Entry` pe_it
		""" + it_join + """
		WHERE pe_it.docstatus = %(docstatus)s AND pe_it.payment_type = 'Internal Transfer' AND """ + it_cond + """
		AND """ + it_account_condition + """
		ORDER BY pe_it.posting_date, pe_it.name
	"""
	rows_it = frappe.db.sql(sql_it, je_params, as_dict=True)
	out = []
	for r in rows_pe:
		out.append([r.doctype, _doc_link(r.doctype, r.name), r.posting_date, r.get("party") or "", flt(r.paid_amount), r.get("mode_of_payment") or ""])
	for r in rows_pi:
		out.append([r.doctype, _doc_link(r.doctype, r.name), r.posting_date, r.get("party") or "", flt(r.paid_amount), r.get("mode_of_payment") or ""])
	for r in rows_je:
		out.append([r.doctype, _doc_link(r.doctype, r.name), r.posting_date, r.get("party") or "", flt(r.paid_amount), r.get("mode_of_payment") or ""])
	for r in rows_it:
		out.append([_("Internal Transfer"), _doc_link("Payment Entry", r.name), r.posting_date, r.get("party") or "", flt(r.paid_amount), r.get("mode_of_payment") or ""])
	out.sort(key=lambda x: (x[2], x[1]))
	return out


def _detail_bank_sales_receipts(params, cost_center):
	cond = _base_conditions(params["from_date"], params["to_date"], params["company"], cost_center, "pe.posting_date", "pe")
	cc = " AND pe.cost_center = %(cost_center)s" if cost_center else ""
	sql = """
		SELECT pe.name, pe.posting_date, pe.party, pe.received_amount, pe.mode_of_payment,
			GROUP_CONCAT(DISTINCT per.reference_name ORDER BY per.reference_name SEPARATOR ', ') as refs
		FROM `tabPayment Entry` pe
		INNER JOIN `tabPayment Entry Reference` per ON per.parent = pe.name
		INNER JOIN `tabMode of Payment` mop ON mop.name = pe.mode_of_payment
		WHERE pe.docstatus = 1 AND """ + cond + """
		AND pe.payment_type = 'Receive' AND per.reference_doctype IN ('Sales Invoice', 'Sales Order')
		AND (mop.type IS NULL OR mop.type != 'Cash')
		""" + cc + """
		GROUP BY pe.name, pe.posting_date, pe.party, pe.received_amount, pe.mode_of_payment
		ORDER BY pe.posting_date, pe.name
	"""
	rows = frappe.db.sql(sql, params, as_dict=True)
	return [[r.name, r.posting_date, r.get("party") or "", flt(r.received_amount), r.get("mode_of_payment") or "", r.get("refs") or ""] for r in rows]


def _detail_bank_sales_payments(params, cost_center):
	cond = _base_conditions(params["from_date"], params["to_date"], params["company"], cost_center, "pe.posting_date", "pe")
	cc = " AND pe.cost_center = %(cost_center)s" if cost_center else ""
	sql_pe = """
		SELECT 'Payment Entry' as doctype, pe.name, pe.posting_date, pe.party, pe.paid_amount, pe.mode_of_payment
		FROM `tabPayment Entry` pe
		INNER JOIN `tabMode of Payment` mop ON mop.name = pe.mode_of_payment
		WHERE pe.docstatus = 1 AND """ + cond + """
		AND pe.payment_type = 'Pay' AND (mop.type IS NULL OR mop.type != 'Cash')
		""" + cc + """
		ORDER BY pe.posting_date, pe.name
	"""
	rows_pe = frappe.db.sql(sql_pe, params, as_dict=True)
	pi_cond = _base_conditions(params["from_date"], params["to_date"], params["company"], cost_center, "pi.posting_date", "pi")
	pi_cc = " AND pi.cost_center = %(cost_center)s" if cost_center else ""
	sql_pi = """
		SELECT 'Purchase Invoice' as doctype, pi.name, pi.posting_date, pi.supplier as party, pi.base_paid_amount as paid_amount, pi.mode_of_payment
		FROM `tabPurchase Invoice` pi
		INNER JOIN `tabMode of Payment` mop ON mop.name = pi.mode_of_payment
		WHERE pi.docstatus = 1 AND pi.is_paid = 1 AND """ + pi_cond + """
		AND (mop.type IS NULL OR mop.type != 'Cash')
		""" + pi_cc + """
		ORDER BY pi.posting_date, pi.name
	"""
	rows_pi = frappe.db.sql(sql_pi, params, as_dict=True)
	out = []
	for r in rows_pe:
		out.append([r.doctype, _doc_link(r.doctype, r.name), r.posting_date, r.get("party") or "", flt(r.paid_amount), r.get("mode_of_payment") or ""])
	for r in rows_pi:
		out.append([r.doctype, _doc_link(r.doctype, r.name), r.posting_date, r.get("party") or "", flt(r.paid_amount), r.get("mode_of_payment") or ""])
	out.sort(key=lambda x: (x[2], x[1]))
	return out


def _detail_internal_transfer_out(params, cost_center):
	cond = _base_conditions(params["from_date"], params["to_date"], params["company"], cost_center, "pe.posting_date", "pe")
	cc = " AND pe.cost_center = %(cost_center)s" if cost_center else ""
	sql = """
		SELECT pe.name, pe.posting_date, pe.paid_from, pe.paid_to, pe.paid_amount
		FROM `tabPayment Entry` pe
		INNER JOIN `tabAccount` acc_from ON acc_from.name = pe.paid_from
		WHERE pe.docstatus = 1 AND pe.payment_type = 'Internal Transfer' AND """ + cond + """
		AND acc_from.account_type = 'Cash'
		""" + cc + """
		ORDER BY pe.posting_date, pe.name
	"""
	rows = frappe.db.sql(sql, params, as_dict=True)
	return [[r.name, r.posting_date, r.paid_from, r.paid_to, flt(r.paid_amount)] for r in rows]


def _detail_internal_transfer_in(params, cost_center):
	cond = _base_conditions(params["from_date"], params["to_date"], params["company"], cost_center, "pe.posting_date", "pe")
	cc = " AND pe.cost_center = %(cost_center)s" if cost_center else ""
	sql = """
		SELECT pe.name, pe.posting_date, pe.paid_from, pe.paid_to, pe.received_amount
		FROM `tabPayment Entry` pe
		INNER JOIN `tabAccount` acc_to ON acc_to.name = pe.paid_to
		WHERE pe.docstatus = 1 AND pe.payment_type = 'Internal Transfer' AND """ + cond + """
		AND acc_to.account_type = 'Cash'
		""" + cc + """
		ORDER BY pe.posting_date, pe.name
	"""
	rows = frappe.db.sql(sql, params, as_dict=True)
	return [[r.name, r.posting_date, r.paid_from, r.paid_to, flt(r.received_amount)] for r in rows]
