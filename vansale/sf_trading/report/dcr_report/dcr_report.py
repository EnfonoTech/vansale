# Copyright (c) 2025, sf_trading and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import add_days, flt, getdate


def execute(filters=None):
	columns = get_columns()
	filters = filters or {}
	# From/To can transiently cross while the user is still editing the date
	# filters (e.g. From Date bumped forward before To Date catches up) — show
	# an empty report rather than an interrupting error popup on every keystroke.
	if filters.get("from_date") and filters.get("to_date") and getdate(filters["from_date"]) > getdate(filters["to_date"]):
		return columns, []
	data = get_data(filters)
	return columns, data


def _show_margin():
	"""Show Gross Margin column only to System Manager."""
	return "System Manager" in frappe.get_roles()


def enforce_user_cost_center(cost_center):
	"""A user restricted to exactly one Cost Center via User Permission always
	sees only that cost center's data, even with no filter selected."""
	if cost_center:
		return cost_center
	from frappe.core.doctype.user_permission.user_permission import get_user_permissions
	perms = (get_user_permissions() or {}).get("Cost Center") or []
	allowed = list({p.get("doc") for p in perms if p.get("doc")})
	if len(allowed) == 1:
		return allowed[0]
	return cost_center


def get_columns():
	cols = [
		_("Particulars") + ":Data:300",
		_("Income") + ":Currency:120",
		_("Expense") + ":Currency:120",
		_("Total Discount/Adj.") + ":Currency:150",
	]
	if _show_margin():
		cols.append(_("Gross Margin") + ":Currency:120")
	return cols


def get_report_link(label, report_type, from_date_str, to_date_str, company, cost_center):
	"""Create a clickable link to DCR Detail report with the given type and filters."""
	from frappe.utils import get_url
	from urllib.parse import urlencode, quote
	query_params = {
		"report_type": report_type,
		"from_date": from_date_str or "",
		"to_date": to_date_str or "",
		"company": company or "",
		"cost_center": cost_center or "",
	}
	query_string = urlencode({k: v for k, v in query_params.items() if v})
	report_path = quote("DCR Detail", safe="")
	url = get_url(uri=f"/app/query-report/{report_path}?{query_string}")
	return f'<a href="{url}">{label}</a>'


# ═══════════════════════════════════════════════════════════════════════════════
# Settlement-based classification (shared with DCR Detail)
#
# Sales lines follow the money actually received ON/BEFORE the invoice date:
#   Cash-type mode          → CASH SALES
#   Cheque mode (for_pdc)   → CHEQUE SALES (even though MoP type is Bank)
#   any other mode          → BANK SALES
# The unsettled remainder → CREDIT SALES, or Home Credit when a driver is set.
# Split payments land proportionally in each line.
# ═══════════════════════════════════════════════════════════════════════════════

def _mode_is_cheque(alias):
	"""SQL condition: the mode of payment on `alias` is a cheque/PDC mode.
	Cheque modes are flagged for_pdc in Branch Configuration; name match is a
	fallback for unconfigured modes."""
	return (
		"(EXISTS (SELECT 1 FROM `tabBranch Configuration Mode of Payment` {a}_pdc"
		" WHERE {a}_pdc.mode_of_payment = {a}.mode_of_payment AND {a}_pdc.for_pdc = 1)"
		" OR LOWER(COALESCE({a}.mode_of_payment, '')) LIKE '%%cheque%%'"
		" OR LOWER(COALESCE({a}.mode_of_payment, '')) LIKE '%%chq%%')"
	).format(a=alias)


def _settled_alloc_subquery(prefix, kind):
	"""Amount settled against the invoice on/before its posting date via the given
	kind of mode ('cash', 'bank' or 'cheque'), from Payment Entries plus the
	invoice's own POS payment rows."""
	p = prefix
	pe_cheque = _mode_is_cheque(f"{p}_pe")
	sip_cheque = _mode_is_cheque(f"{p}_sip")
	if kind == "cash":
		pe_mode = f"({p}_mop.type = 'Cash' AND NOT {pe_cheque})"
		sip_mode = f"({p}_sipm.type = 'Cash' AND NOT {sip_cheque})"
	elif kind == "bank":
		pe_mode = f"(COALESCE({p}_mop.type, '') != 'Cash' AND NOT {pe_cheque})"
		sip_mode = f"(COALESCE({p}_sipm.type, '') != 'Cash' AND NOT {sip_cheque})"
	else:
		pe_mode = pe_cheque
		sip_mode = sip_cheque
	return f"""((
		SELECT COALESCE(SUM({p}_per.allocated_amount), 0)
		FROM `tabPayment Entry Reference` {p}_per
		INNER JOIN `tabPayment Entry` {p}_pe ON {p}_pe.name = {p}_per.parent AND {p}_pe.docstatus = 1 AND {p}_pe.payment_type = 'Receive'
		LEFT JOIN `tabMode of Payment` {p}_mop ON {p}_mop.name = {p}_pe.mode_of_payment
		WHERE {p}_per.reference_doctype = 'Sales Invoice' AND {p}_per.reference_name = si.name
			AND {p}_pe.posting_date <= si.posting_date
			AND {pe_mode}
	) + (
		SELECT COALESCE(SUM({p}_sip.base_amount), 0)
		FROM `tabSales Invoice Payment` {p}_sip
		LEFT JOIN `tabMode of Payment` {p}_sipm ON {p}_sipm.name = {p}_sip.mode_of_payment
		WHERE {p}_sip.parent = si.name AND {p}_sip.parenttype = 'Sales Invoice'
			AND {sip_mode}
	))"""


SETTLED_CASH_ALLOC_SUBQUERY = _settled_alloc_subquery("sc", "cash")
SETTLED_BANK_ALLOC_SUBQUERY = _settled_alloc_subquery("sb", "bank")
SETTLED_CHEQUE_ALLOC_SUBQUERY = _settled_alloc_subquery("sq", "cheque")


def _settled_writeoff_subquery(prefix, kind):
	"""Write-off/deduction amount (any Payment Entry Deduction account) riding on
	the invoice's on/before-date settlement of the given kind, proportioned by
	this invoice's share of each contributing Payment Entry's total allocation.

	This portion of {kind}_alloc never became physical cash/bank money — the
	invoice is still correctly classified as settled by this kind (that part of
	the accounting is unaffected), but the amount is subtracted from the row's
	reported Income and shown in Total Discount/Adj. instead, so a sales row
	never reports money that was actually waived, not received."""
	p = prefix
	pe_cheque = _mode_is_cheque(f"{p}_pe")
	if kind == "cash":
		pe_mode = f"({p}_mop.type = 'Cash' AND NOT {pe_cheque})"
	elif kind == "bank":
		pe_mode = f"(COALESCE({p}_mop.type, '') != 'Cash' AND NOT {pe_cheque})"
	else:
		pe_mode = pe_cheque
	return f"""(
		SELECT COALESCE(SUM(
			{p}_per.allocated_amount * COALESCE((
				SELECT SUM({p}_ded.amount) FROM `tabPayment Entry Deduction` {p}_ded
				WHERE {p}_ded.parent = {p}_pe.name
			), 0) / NULLIF((
				SELECT SUM({p}_tper.allocated_amount) FROM `tabPayment Entry Reference` {p}_tper
				WHERE {p}_tper.parent = {p}_pe.name AND {p}_tper.reference_doctype = 'Sales Invoice'
			), 0)
		), 0)
		FROM `tabPayment Entry Reference` {p}_per
		INNER JOIN `tabPayment Entry` {p}_pe ON {p}_pe.name = {p}_per.parent AND {p}_pe.docstatus = 1 AND {p}_pe.payment_type = 'Receive'
		LEFT JOIN `tabMode of Payment` {p}_mop ON {p}_mop.name = {p}_pe.mode_of_payment
		WHERE {p}_per.reference_doctype = 'Sales Invoice' AND {p}_per.reference_name = si.name
			AND {p}_pe.posting_date <= si.posting_date
			AND {pe_mode}
	)"""


SETTLED_CASH_WRITEOFF_SUBQUERY = _settled_writeoff_subquery("wc", "cash")
SETTLED_BANK_WRITEOFF_SUBQUERY = _settled_writeoff_subquery("wb", "bank")
SETTLED_CHEQUE_WRITEOFF_SUBQUERY = _settled_writeoff_subquery("wq", "cheque")


def _settled_modes_subquery(prefix, kind):
	"""Comma-separated distinct Mode of Payment names that contributed to the
	invoice's on/before-date settlement of the given kind (cash/bank/cheque) —
	for the DCR Detail drill-down's Mode of Payment column, not used by the
	summary math. A split payment lists every mode that contributed."""
	p = prefix
	pe_cheque = _mode_is_cheque(f"{p}_pe")
	sip_cheque = _mode_is_cheque(f"{p}_sip")
	if kind == "cash":
		pe_mode = f"({p}_mop.type = 'Cash' AND NOT {pe_cheque})"
		sip_mode = f"({p}_sipm.type = 'Cash' AND NOT {sip_cheque})"
	elif kind == "bank":
		pe_mode = f"(COALESCE({p}_mop.type, '') != 'Cash' AND NOT {pe_cheque})"
		sip_mode = f"(COALESCE({p}_sipm.type, '') != 'Cash' AND NOT {sip_cheque})"
	else:
		pe_mode = pe_cheque
		sip_mode = sip_cheque
	# CONCAT_WS (not a UNION-derived table) — a derived table can't be
	# correlated to the outer invoice in MySQL/MariaDB, so each source is its
	# own correlated scalar subquery, combined at the end. Skips NULLs cleanly.
	return f"""CONCAT_WS(', ', (
		SELECT GROUP_CONCAT(DISTINCT {p}_pe.mode_of_payment ORDER BY {p}_pe.mode_of_payment SEPARATOR ', ')
		FROM `tabPayment Entry Reference` {p}_per
		INNER JOIN `tabPayment Entry` {p}_pe ON {p}_pe.name = {p}_per.parent AND {p}_pe.docstatus = 1 AND {p}_pe.payment_type = 'Receive'
		LEFT JOIN `tabMode of Payment` {p}_mop ON {p}_mop.name = {p}_pe.mode_of_payment
		WHERE {p}_per.reference_doctype = 'Sales Invoice' AND {p}_per.reference_name = si.name
			AND {p}_pe.posting_date <= si.posting_date
			AND {pe_mode}
	), (
		SELECT GROUP_CONCAT(DISTINCT {p}_sip.mode_of_payment ORDER BY {p}_sip.mode_of_payment SEPARATOR ', ')
		FROM `tabSales Invoice Payment` {p}_sip
		LEFT JOIN `tabMode of Payment` {p}_sipm ON {p}_sipm.name = {p}_sip.mode_of_payment
		WHERE {p}_sip.parent = si.name AND {p}_sip.parenttype = 'Sales Invoice'
			AND {sip_mode}
	))"""


SETTLED_CASH_MODES_SUBQUERY = _settled_modes_subquery("mc", "cash")
SETTLED_BANK_MODES_SUBQUERY = _settled_modes_subquery("mb", "bank")
SETTLED_CHEQUE_MODES_SUBQUERY = _settled_modes_subquery("mq", "cheque")

# Return that was actually refunded (money out) on/before the return's posting
# date: a Pay-type Payment Entry against the return, or POS refund rows on it.
# Follows the money on the return itself — the original invoice's settlement is
# irrelevant (a refunded return is a cash return even if the sale was on credit).
RETURN_REFUNDED_CONDITION = """(
	EXISTS (
		SELECT 1 FROM `tabPayment Entry Reference` ret_per
		INNER JOIN `tabPayment Entry` ret_pe ON ret_pe.name = ret_per.parent AND ret_pe.docstatus = 1 AND ret_pe.payment_type = 'Pay'
		WHERE ret_per.reference_doctype = 'Sales Invoice' AND ret_per.reference_name = si.name
			AND ret_pe.posting_date <= si.posting_date
	)
	OR EXISTS (
		SELECT 1 FROM `tabSales Invoice Payment` ret_sip
		WHERE ret_sip.parent = si.name AND ret_sip.parenttype = 'Sales Invoice'
			AND ret_sip.base_amount != 0
	)
)"""


def _return_refunded_condition(kind):
	"""SQL condition: the return was refunded via a Pay-type Payment Entry (or a
	POS refund row) of the given kind (cash/bank/cheque) on/before its own
	posting date. Mirrors the sales-side mode split (CASH/BANK/CHEQUE SALES) so
	a return's expense lands in the same kind of row as the account the refund
	actually left — a bank/cheque refund must not be counted as a cash return."""
	pe_cheque = _mode_is_cheque("rf_pe")
	sip_cheque = _mode_is_cheque("rf_sip")
	if kind == "cash":
		pe_mode = f"(rf_mop.type = 'Cash' AND NOT {pe_cheque})"
		sip_mode = f"(rf_sipm.type = 'Cash' AND NOT {sip_cheque})"
	elif kind == "bank":
		pe_mode = f"(COALESCE(rf_mop.type, '') != 'Cash' AND NOT {pe_cheque})"
		sip_mode = f"(COALESCE(rf_sipm.type, '') != 'Cash' AND NOT {sip_cheque})"
	else:
		pe_mode = pe_cheque
		sip_mode = sip_cheque
	return f"""(
		EXISTS (
			SELECT 1 FROM `tabPayment Entry Reference` rf_per
			INNER JOIN `tabPayment Entry` rf_pe ON rf_pe.name = rf_per.parent AND rf_pe.docstatus = 1 AND rf_pe.payment_type = 'Pay'
			LEFT JOIN `tabMode of Payment` rf_mop ON rf_mop.name = rf_pe.mode_of_payment
			WHERE rf_per.reference_doctype = 'Sales Invoice' AND rf_per.reference_name = si.name
				AND rf_pe.posting_date <= si.posting_date
				AND {pe_mode}
		)
		OR EXISTS (
			SELECT 1 FROM `tabSales Invoice Payment` rf_sip
			LEFT JOIN `tabMode of Payment` rf_sipm ON rf_sipm.name = rf_sip.mode_of_payment
			WHERE rf_sip.parent = si.name AND rf_sip.parenttype = 'Sales Invoice'
				AND rf_sip.base_amount != 0
				AND {sip_mode}
		)
	)"""


def get_invoices_with_settlement(from_date, to_date, company, cost_center):
	"""All sales invoices in range with the amounts settled on/before the invoice
	date per mode kind (cash/bank/cheque). Shared by the summary and DCR Detail."""
	conditions = "si.docstatus = 1 AND si.is_return = 0"
	if from_date:
		conditions += " AND si.posting_date >= %(from_date)s"
	if to_date:
		conditions += " AND si.posting_date <= %(to_date)s"
	if company:
		conditions += " AND si.company = %(company)s"
	cost_center_condition = " AND sii.cost_center = %(cost_center)s" if cost_center else ""
	return frappe.db.sql("""
		SELECT
			si.name,
			si.posting_date,
			si.customer,
			si.customer_name,
			si.custom_driver,
			si.base_net_total,
			si.total_taxes_and_charges as vat_amount,
			si.base_grand_total,
			si.grand_total,
			si.discount_amount as discount,
			SUM(COALESCE(sii.incoming_rate, 0) * sii.stock_qty) as cost,
			{cash_alloc} as cash_alloc,
			{bank_alloc} as bank_alloc,
			{cheque_alloc} as cheque_alloc,
			{cash_wo} as cash_write_off,
			{bank_wo} as bank_write_off,
			{cheque_wo} as cheque_write_off,
			{cash_modes} as cash_modes,
			{bank_modes} as bank_modes,
			{cheque_modes} as cheque_modes
		FROM `tabSales Invoice` si
		LEFT JOIN `tabSales Invoice Item` sii ON sii.parent = si.name
		WHERE {conditions}
			{cost_center_condition}
		GROUP BY si.name, si.posting_date, si.customer, si.customer_name, si.custom_driver,
			si.base_net_total, si.total_taxes_and_charges, si.base_grand_total, si.grand_total,
			si.discount_amount
		ORDER BY si.posting_date, si.name
	""".format(cash_alloc=SETTLED_CASH_ALLOC_SUBQUERY, bank_alloc=SETTLED_BANK_ALLOC_SUBQUERY,
		cheque_alloc=SETTLED_CHEQUE_ALLOC_SUBQUERY, cash_wo=SETTLED_CASH_WRITEOFF_SUBQUERY,
		bank_wo=SETTLED_BANK_WRITEOFF_SUBQUERY, cheque_wo=SETTLED_CHEQUE_WRITEOFF_SUBQUERY,
		cash_modes=SETTLED_CASH_MODES_SUBQUERY, bank_modes=SETTLED_BANK_MODES_SUBQUERY,
		cheque_modes=SETTLED_CHEQUE_MODES_SUBQUERY,
		conditions=conditions, cost_center_condition=cost_center_condition), {
		"from_date": from_date,
		"to_date": to_date,
		"company": company,
		"cost_center": cost_center,
	}, as_dict=True)


def split_invoice_settlement(r):
	"""Split one invoice's grand total into settled cash/bank/cheque portions and
	the unsettled remainder. Over-allocation (e.g. write-off riding on the last
	Payment Entry) is scaled back so portions never exceed the invoice total.

	Also returns the write-off portion riding on each settled kind: still part
	of that kind's settled amount (classification is unaffected), but callers
	should subtract it from reported Income — it never became physical money."""
	total = flt(r.base_grand_total)
	if total <= 0:
		return {"cash": 0, "bank": 0, "cheque": 0, "remainder": 0, "total": total,
			"cash_write_off": 0, "bank_write_off": 0, "cheque_write_off": 0}
	cash, bank, cheque = flt(r.cash_alloc), flt(r.bank_alloc), flt(r.cheque_alloc)
	cash_wo, bank_wo, cheque_wo = flt(r.cash_write_off), flt(r.bank_write_off), flt(r.cheque_write_off)
	settled = cash + bank + cheque
	if settled > total:
		factor = total / settled
		cash, bank, cheque = cash * factor, bank * factor, cheque * factor
		cash_wo, bank_wo, cheque_wo = cash_wo * factor, bank_wo * factor, cheque_wo * factor
		settled = total
	remainder = total - settled
	if remainder < 0.005:
		remainder = 0
	# A write-off can never exceed the settled amount it rode on.
	cash_wo = min(cash_wo, cash)
	bank_wo = min(bank_wo, bank)
	cheque_wo = min(cheque_wo, cheque)
	return {"cash": cash, "bank": bank, "cheque": cheque, "remainder": remainder, "total": total,
		"cash_write_off": cash_wo, "bank_write_off": bank_wo, "cheque_write_off": cheque_wo}


def get_sales_buckets(from_date, to_date, company, cost_center):
	"""Aggregate the per-invoice settlement splits into the report's sales rows.
	Each bucket's "write_off" is the portion of its settled value that rode on a
	deduction rather than becoming physical money — bucket_income() subtracts it."""
	buckets = {
		key: {"net_total": 0, "vat_amount": 0, "discount": 0, "cost": 0, "write_off": 0}
		for key in ("cash", "bank", "cheque", "credit", "home_credit")
	}
	for r in get_invoices_with_settlement(from_date, to_date, company, cost_center):
		s = split_invoice_settlement(r)
		if s["total"] <= 0:
			continue
		remainder_bucket = "home_credit" if (r.custom_driver or "").strip() else "credit"
		shares = {
			"cash": s["cash"] / s["total"],
			"bank": s["bank"] / s["total"],
			"cheque": s["cheque"] / s["total"],
			remainder_bucket: s["remainder"] / s["total"],
		}
		for bucket_key, share in shares.items():
			if share <= 0:
				continue
			b = buckets[bucket_key]
			b["net_total"] += flt(r.base_net_total) * share
			b["vat_amount"] += flt(r.vat_amount) * share
			b["discount"] += flt(r.discount) * share
			b["cost"] += flt(r.cost) * share
		buckets["cash"]["write_off"] += s["cash_write_off"]
		buckets["bank"]["write_off"] += s["bank_write_off"]
		buckets["cheque"]["write_off"] += s["cheque_write_off"]
	return buckets


def get_data(filters):
	data = []

	if not filters.get("from_date") or not filters.get("to_date"):
		frappe.throw(_("Please select From Date and To Date"))
	if not filters.get("company"):
		frappe.throw(_("Please select a Company"))

	from_date = getdate(filters.get("from_date"))
	to_date = getdate(filters.get("to_date"))
	company = filters.get("company")
	cost_center = enforce_user_cost_center(filters.get("cost_center"))

	from_date_str = from_date.strftime("%Y-%m-%d")
	to_date_str = to_date.strftime("%Y-%m-%d")

	# Opening/Closing straight from the General Ledger cash accounts so both
	# balances always tie to the branch petty cash ledger (Journal Entries,
	# POS payments and Internal Transfers are included automatically), minus
	# whatever UnApproved (draft) petty cash is still pending as of that date —
	# the client treats that cash as already gone from the till even though it
	# has no GL entry yet. Cumulative ("as of", not just this period) so that
	# yesterday's Closing always equals today's Opening, draft or not.
	unapproved_asof_open = get_petty_cash_payments(None, add_days(from_date, -1), company, cost_center, docstatus=0)
	unapproved_asof_close = get_petty_cash_payments(None, to_date, company, cost_center, docstatus=0)
	opening_balance = get_gl_cash_balance(add_days(from_date, -1), company, cost_center) - unapproved_asof_open
	closing_balance = get_gl_cash_balance(to_date, company, cost_center) - unapproved_asof_close

	buckets = get_sales_buckets(from_date, to_date, company, cost_center)

	def bucket_income(b):
		# Net + VAT is the full invoice value settled by this mode; the write-off
		# portion never became physical money, so it's excluded from Income and
		# shown in Total Discount/Adj. instead (see bucket_discount_adj below).
		return b["net_total"] + b["vat_amount"] - b["write_off"]

	def bucket_margin(b):
		return b["net_total"] - b["cost"]

	def bucket_discount_adj(b):
		return -(b["discount"] + b["write_off"])

	cash_b = buckets["cash"]
	bank_b = buckets["bank"]
	cheque_b = buckets["cheque"]
	credit_b = buckets["credit"]
	home_b = buckets["home_credit"]

	total_sales_income = sum(bucket_income(b) for b in buckets.values())
	total_sales_margin = sum(bucket_margin(b) for b in buckets.values())
	total_sales_discount = sum(b["discount"] + b["write_off"] for b in buckets.values())

	sales_return_cash_data = get_sales_returns(from_date, to_date, company, cost_center, kind="cash")
	sales_return_bank_data = get_sales_returns(from_date, to_date, company, cost_center, kind="bank")
	sales_return_cheque_data = get_sales_returns(from_date, to_date, company, cost_center, kind="cheque")
	credit_return_data = get_sales_returns(from_date, to_date, company, cost_center, kind="credit")

	sales_return_cash = sales_return_cash_data["net_total"] + sales_return_cash_data["vat_amount"]
	sales_return_bank = sales_return_bank_data["net_total"] + sales_return_bank_data["vat_amount"]
	sales_return_cheque = sales_return_cheque_data["net_total"] + sales_return_cheque_data["vat_amount"]
	credit_return_total = credit_return_data["net_total"] + credit_return_data["vat_amount"]

	# VAT Refund on Sales Return stays a single combined figure across every
	# refund mode — VAT recognition doesn't depend on how the refund was paid.
	vat_refund_total = (
		sales_return_cash_data["vat_amount"]
		+ sales_return_bank_data["vat_amount"]
		+ sales_return_cheque_data["vat_amount"]
	)

	credit_purchase = get_credit_purchases(from_date, to_date, company, cost_center).get("total_with_vat", 0)

	cash_received_credit_sales = get_cash_received_credit_sales(from_date, to_date, company, cost_center)
	cash_movement = get_gl_cash_movement(from_date, to_date, company, cost_center)

	petty_cash_approved = get_petty_cash_payments(from_date, to_date, company, cost_center, docstatus=1)
	petty_cash_unapproved = get_petty_cash_payments(from_date, to_date, company, cost_center, docstatus=0)

	write_off_total = get_write_off_total(from_date, to_date, company, cost_center)

	def _row(particulars, income, expense, discount_adj, margin=0):
		row = [particulars, income, expense, discount_adj]
		if _show_margin():
			row.append(margin)
		return row

	def _link(label, report_type):
		return get_report_link(label, report_type, from_date_str, to_date_str, company, cost_center)

	data.append(_row("<b>" + _link(_("Opening Cash Balance"), "Opening Cash Balance") + "</b>", opening_balance, 0, 0, 0))
	data.append(_row("<b>" + _link(_("Total Sales"), "Total Sales") + "</b>", total_sales_income, 0, -total_sales_discount, total_sales_margin))
	data.append(_row(_link("CASH SALES", "Cash Sales"), bucket_income(cash_b), 0, bucket_discount_adj(cash_b), bucket_margin(cash_b)))
	data.append(_row(_link("BANK SALES", "Bank Sales"), bucket_income(bank_b), 0, bucket_discount_adj(bank_b), bucket_margin(bank_b)))
	data.append(_row(_link("CHEQUE SALES", "Cheque Sales"), bucket_income(cheque_b), 0, bucket_discount_adj(cheque_b), bucket_margin(cheque_b)))
	data.append(_row(_link("CREDIT SALES", "Credit Sales"), bucket_income(credit_b), credit_return_total, bucket_discount_adj(credit_b), bucket_margin(credit_b)))
	data.append(_row(_link("Home Credit (Delivery)", "Home Credit (Delivery)"), bucket_income(home_b), 0, bucket_discount_adj(home_b), bucket_margin(home_b)))
	# Sales Return - Cash is the normal case for this business and always shown.
	# Bank/Cheque refunds are rare exceptions — only show those rows when this
	# run actually has a value, to keep the common case uncluttered.
	data.append(_row(_link("Sales Return - Cash", "Sales Return - Cash"), 0, sales_return_cash, 0, 0))
	if abs(sales_return_bank) > 0.0001:
		data.append(_row(_link("Sales Return - Bank", "Sales Return - Bank"), 0, sales_return_bank, 0, 0))
	if abs(sales_return_cheque) > 0.0001:
		data.append(_row(_link("Sales Return - Cheque", "Sales Return - Cheque"), 0, sales_return_cheque, 0, 0))
	data.append(_row(_link("VAT Collected on Cash Sales", "VAT Collected on Cash Sales"), cash_b["vat_amount"], 0, 0, 0))
	data.append(_row(_link("VAT Collected on Bank Sales", "VAT Collected on Bank Sales"), bank_b["vat_amount"], 0, 0, 0))
	data.append(_row(_link("VAT Collected on Cheque Sales", "VAT Collected on Cheque Sales"), cheque_b["vat_amount"], 0, 0, 0))
	data.append(_row(_link("VAT Applied on Credit Sales", "VAT Applied on Credit Sales"), credit_b["vat_amount"], credit_return_data["vat_amount"], 0, 0))
	data.append(_row(_link("VAT Applied on Home Credit", "VAT Applied on Home Credit"), home_b["vat_amount"], 0, 0, 0))
	data.append(_row(_link("VAT Refund on Sales Return", "VAT Refund on Sales Return"), 0, vat_refund_total, 0, 0))
	data.append(_row(_link("Loyalty / Write Off", "Loyalty / Write Off"), 0, write_off_total, 0, 0))
	data.append(_row(_link("Credit Purchase - DIRECT PURCHASE", "Credit Purchase - DIRECT PURCHASE"), 0, credit_purchase, 0, 0))
	data.append(_row(_link("Cash Received : Credit Sales", "Cash Received : Credit Sales"), cash_received_credit_sales, 0, 0, 0))
	data.append(_row(_link("Payments-Petty Cash (Approved)", "Payments-Petty Cash (Approved)"), 0, petty_cash_approved, 0, 0))
	data.append(_row(_link("Payments-Petty Cash (UnApproved)", "Payments-Petty Cash (UnApproved)"), 0, petty_cash_unapproved, 0, 0))
	# Net Cash Movement's expense includes the NET CHANGE in still-pending
	# UnApproved petty cash over this period (new drafts raised, minus any
	# earlier-pending draft that got approved/cancelled) — not just this
	# period's own drafts — so it stays consistent with the cumulative
	# Opening/Closing above and the identity holds exactly no matter the range.
	unapproved_net_change = unapproved_asof_close - unapproved_asof_open
	net_movement = cash_movement["cash_in"] - (cash_movement["cash_out"] + unapproved_net_change)
	net_movement_income = net_movement if net_movement >= 0 else 0
	net_movement_expense = -net_movement if net_movement < 0 else 0
	data.append(_row("<b>" + _link(_("Net Cash Movement"), "Net Cash Movement") + "</b>", net_movement_income, net_movement_expense, 0, 0))
	data.append(_row("<b>" + _link(_("Closing Cash Balance"), "Closing Cash Balance") + "</b>", closing_balance, 0, 0, 0))

	return data


def get_branch_petty_cash_accounts(company, cost_center):
	"""Petty cash accounts of the branch(es) mapped to this cost center, derived
	from Branch Configuration: the default account (per company) of the branch's
	Cash-type Modes of Payment. Branches always have their own cash MoP, and its
	default account is exactly where the payment popup posts the branch's cash."""
	if not cost_center:
		return []
	conditions = "bcc.cost_center = %(cost_center)s AND COALESCE(mopa.default_account, '') != ''"
	if company:
		conditions += " AND mopa.company = %(company)s AND (bc.company = %(company)s OR COALESCE(bc.company, '') = '')"
	else:
		conditions += " AND (mopa.company = bc.company OR COALESCE(bc.company, '') = '')"
	rows = frappe.db.sql("""
		SELECT DISTINCT mopa.default_account
		FROM `tabBranch Configuration` bc
		INNER JOIN `tabBranch Configuration Cost Center` bcc
			ON bcc.parent = bc.name AND bcc.parenttype = 'Branch Configuration'
		INNER JOIN `tabBranch Configuration Mode of Payment` bcm
			ON bcm.parent = bc.name AND bcm.parenttype = 'Branch Configuration'
		INNER JOIN `tabMode of Payment` mop ON mop.name = bcm.mode_of_payment AND mop.type = 'Cash'
		INNER JOIN `tabMode of Payment Account` mopa ON mopa.parent = mop.name
		WHERE {conditions}
	""".format(conditions=conditions), {"company": company, "cost_center": cost_center})
	return [r[0] for r in rows]


def get_gl_cash_balance(as_of_date, company, cost_center):
	"""Opening/Closing Cash Balance from the General Ledger.

	When the cost center maps to a branch with a Petty Cash Account configured
	(Branch Configuration), the balance is that account's full GL balance with
	NO cost center condition — the account is branch-specific by definition, so
	journal entries with a wrong or missing cost center still count, and other
	cash accounts that merely share the cost center are excluded.

	Fallback (no Petty Cash Account configured, or no cost center filter):
	all Cash-type accounts, filtered by cost center when given."""
	petty_cash_accounts = get_branch_petty_cash_accounts(company, cost_center)

	conditions = "gle.is_cancelled = 0 AND gle.posting_date <= %(as_of_date)s"
	if company:
		conditions += " AND gle.company = %(company)s"

	params = {
		"as_of_date": as_of_date,
		"company": company,
		"cost_center": cost_center,
		"accounts": tuple(petty_cash_accounts) or ("",),
	}

	if petty_cash_accounts:
		result = frappe.db.sql("""
			SELECT COALESCE(SUM(gle.debit - gle.credit), 0) as balance
			FROM `tabGL Entry` gle
			WHERE {conditions}
				AND gle.account IN %(accounts)s
		""".format(conditions=conditions), params, as_dict=True)
	else:
		cost_center_condition = " AND gle.cost_center = %(cost_center)s" if cost_center else ""
		result = frappe.db.sql("""
			SELECT COALESCE(SUM(gle.debit - gle.credit), 0) as balance
			FROM `tabGL Entry` gle
			INNER JOIN `tabAccount` acc ON acc.name = gle.account
			WHERE {conditions}
				AND acc.account_type = 'Cash'
				{cost_center_condition}
		""".format(conditions=conditions, cost_center_condition=cost_center_condition), params, as_dict=True)
	return flt(result[0].balance) if result else 0


def get_gl_cash_movement(from_date, to_date, company, cost_center):
	"""Gross cash in / cash out of the petty cash account(s) from the General
	Ledger over the range. Same account resolution as the balances, so
	Opening + In - Out = Closing holds exactly."""
	petty_cash_accounts = get_branch_petty_cash_accounts(company, cost_center)

	conditions = "gle.is_cancelled = 0 AND gle.posting_date >= %(from_date)s AND gle.posting_date <= %(to_date)s"
	if company:
		conditions += " AND gle.company = %(company)s"

	params = {
		"from_date": from_date,
		"to_date": to_date,
		"company": company,
		"cost_center": cost_center,
		"accounts": tuple(petty_cash_accounts) or ("",),
	}

	if petty_cash_accounts:
		result = frappe.db.sql("""
			SELECT COALESCE(SUM(gle.debit), 0) as cash_in, COALESCE(SUM(gle.credit), 0) as cash_out
			FROM `tabGL Entry` gle
			WHERE {conditions}
				AND gle.account IN %(accounts)s
		""".format(conditions=conditions), params, as_dict=True)
	else:
		cost_center_condition = " AND gle.cost_center = %(cost_center)s" if cost_center else ""
		result = frappe.db.sql("""
			SELECT COALESCE(SUM(gle.debit), 0) as cash_in, COALESCE(SUM(gle.credit), 0) as cash_out
			FROM `tabGL Entry` gle
			INNER JOIN `tabAccount` acc ON acc.name = gle.account
			WHERE {conditions}
				AND acc.account_type = 'Cash'
				{cost_center_condition}
		""".format(conditions=conditions, cost_center_condition=cost_center_condition), params, as_dict=True)
	row = result[0] if result else {}
	return {"cash_in": flt(row.get("cash_in")), "cash_out": flt(row.get("cash_out"))}


def get_sales_returns(from_date, to_date, company, cost_center, kind):
	"""Sales returns split by how they were refunded: kind='cash'/'bank'/'cheque'
	sums returns refunded via that mode on/before the return's own date (money
	actually left that kind of account); kind='credit' sums UNREFUNDED returns,
	which only offset the customer's receivable (no cash movement, expense on
	the CREDIT SALES row instead). The four kinds are mutually exclusive and
	cover every return exactly once."""
	conditions = "si.docstatus = 1 AND si.is_return = 1"
	if from_date:
		conditions += " AND si.posting_date >= %(from_date)s"
	if to_date:
		conditions += " AND si.posting_date <= %(to_date)s"
	if company:
		conditions += " AND si.company = %(company)s"
	cost_center_condition = " AND EXISTS (SELECT 1 FROM `tabSales Invoice Item` sii WHERE sii.parent = si.name AND sii.cost_center = %(cost_center)s)" if cost_center else ""
	return_condition = "NOT " + RETURN_REFUNDED_CONDITION if kind == "credit" else _return_refunded_condition(kind)
	result = frappe.db.sql("""
		SELECT SUM(ABS(si.base_net_total)) as net_total, SUM(ABS(si.total_taxes_and_charges)) as vat_amount
		FROM `tabSales Invoice` si
		WHERE {conditions}
			AND {return_condition}
			{cost_center_condition}
	""".format(conditions=conditions, return_condition=return_condition,
		cost_center_condition=cost_center_condition), {
		"from_date": from_date,
		"to_date": to_date,
		"company": company,
		"cost_center": cost_center,
	}, as_dict=True)
	if result and (result[0].net_total or result[0].vat_amount):
		return {
			"net_total": flt(result[0].net_total),
			"vat_amount": flt(result[0].vat_amount),
		}
	return {"net_total": 0, "vat_amount": 0}


def get_credit_purchases(from_date, to_date, company, cost_center):
	"""Get credit purchases (Purchase Invoices - all invoices regardless of payment status)
	Returns total including VAT.

	One aggregate row over `tabPurchase Invoice` with NO join to items. Joining to
	items repeats the header net_total once per line item and inflates the totals
	(a 9-line invoice was counted 9x). Cost center is applied via EXISTS so only
	invoices with a line in that cost center are counted, header value taken once."""
	conditions = "pi.docstatus = 1"
	if from_date:
		conditions += " AND pi.posting_date >= %(from_date)s"
	if to_date:
		conditions += " AND pi.posting_date <= %(to_date)s"
	if company:
		conditions += " AND pi.company = %(company)s"
	if cost_center:
		conditions += (
			" AND EXISTS (SELECT 1 FROM `tabPurchase Invoice Item` pii"
			" WHERE pii.parent = pi.name AND pii.cost_center = %(cost_center)s)"
		)

	result = frappe.db.sql(
		"SELECT COALESCE(SUM(pi.net_total), 0) as net_total,"
		" COALESCE(SUM(pi.total_taxes_and_charges), 0) as vat_amount"
		" FROM `tabPurchase Invoice` pi WHERE " + conditions,
		{
			"from_date": from_date,
			"to_date": to_date,
			"company": company,
			"cost_center": cost_center,
		},
		as_dict=True,
	)

	total_net = flt(result[0].net_total) if result else 0
	total_vat = flt(result[0].vat_amount) if result else 0
	return {
		"net_total": total_net,
		"vat_amount": total_vat,
		"total_with_vat": total_net + total_vat,
	}


def get_cash_received_credit_sales(from_date, to_date, company, cost_center):
	"""Actual cash received (Payment Entry, Cash mode, or a Journal Entry
	debiting a Cash-type account with a Sales Invoice reference) collecting
	credit and home-credit sales — payments made after the invoice date — plus
	any advance/unallocated cash on those same Cash-mode Receive PEs (an
	overpayment, or a PE with no Sales Invoice reference at all).

	Uses the PE's actual received_amount rather than allocated_amount: when a
	write-off rides on the payment, allocated_amount = cash + write-off, which
	overstates real till cash. received_amount is attributed proportionally by
	each PE's share of allocation going to qualifying (credit-collection)
	references, so a PE settling a mix of invoice types splits correctly."""
	conditions = "pe.docstatus = 1 AND pe.payment_type = 'Receive'"
	if from_date:
		conditions += " AND pe.posting_date >= %(from_date)s"
	if to_date:
		conditions += " AND pe.posting_date <= %(to_date)s"
	if company:
		conditions += " AND pe.company = %(company)s"
	cost_center_condition = " AND pe.cost_center = %(cost_center)s" if cost_center else ""
	rows = frappe.db.sql("""
		SELECT pe.name, pe.received_amount,
			SUM(per.allocated_amount) as total_alloc,
			SUM(CASE WHEN si.posting_date < pe.posting_date THEN per.allocated_amount ELSE 0 END) as credit_alloc
		FROM `tabPayment Entry` pe
		INNER JOIN `tabPayment Entry Reference` per ON per.parent = pe.name
		INNER JOIN `tabMode of Payment` mop ON mop.name = pe.mode_of_payment
		INNER JOIN `tabSales Invoice` si ON si.name = per.reference_name AND per.reference_doctype = 'Sales Invoice'
		WHERE {conditions}
			AND per.reference_doctype = 'Sales Invoice'
			AND mop.type = 'Cash'
			{cost_center_condition}
		GROUP BY pe.name, pe.received_amount
	""".format(conditions=conditions, cost_center_condition=cost_center_condition), {
		"from_date": from_date,
		"to_date": to_date,
		"company": company,
		"cost_center": cost_center,
	}, as_dict=True)
	total = 0
	for r in rows:
		total_alloc = flt(r.total_alloc)
		if total_alloc <= 0:
			continue
		share = flt(r.credit_alloc) / total_alloc
		if share > 0:
			total += flt(r.received_amount) * share

	advance_result = frappe.db.sql("""
		SELECT SUM(GREATEST(pe.received_amount - COALESCE((
			SELECT SUM(per.allocated_amount) FROM `tabPayment Entry Reference` per
			WHERE per.parent = pe.name AND per.reference_doctype = 'Sales Invoice'
		), 0), 0)) as amount
		FROM `tabPayment Entry` pe
		INNER JOIN `tabMode of Payment` mop ON mop.name = pe.mode_of_payment
		WHERE {conditions}
			AND mop.type = 'Cash'
			{cost_center_condition}
	""".format(conditions=conditions, cost_center_condition=cost_center_condition), {
		"from_date": from_date,
		"to_date": to_date,
		"company": company,
		"cost_center": cost_center,
	}, as_dict=True)
	if advance_result and advance_result[0].amount:
		total += flt(advance_result[0].amount)

	# Journal Entries collecting a credit sale: a JE Account row debiting a
	# Cash-type account, referencing the Sales Invoice, dated after it — the
	# same collection concept as a Receive PE, just posted via Journal Entry.
	je_conditions = "je.docstatus = 1"
	if from_date:
		je_conditions += " AND je.posting_date >= %(from_date)s"
	if to_date:
		je_conditions += " AND je.posting_date <= %(to_date)s"
	if company:
		je_conditions += " AND je.company = %(company)s"
	je_cost_center_condition = " AND jea.cost_center = %(cost_center)s" if cost_center else ""
	je_result = frappe.db.sql("""
		SELECT SUM(jea.debit) as amount
		FROM `tabJournal Entry Account` jea
		INNER JOIN `tabJournal Entry` je ON je.name = jea.parent
		INNER JOIN `tabAccount` acc ON acc.name = jea.account
		INNER JOIN `tabSales Invoice` si ON si.name = jea.reference_name
		WHERE {je_conditions}
			AND jea.reference_type = 'Sales Invoice'
			AND acc.account_type = 'Cash'
			AND si.posting_date < je.posting_date
			{je_cost_center_condition}
	""".format(je_conditions=je_conditions, je_cost_center_condition=je_cost_center_condition), {
		"from_date": from_date,
		"to_date": to_date,
		"company": company,
		"cost_center": cost_center,
	}, as_dict=True)
	if je_result and je_result[0].amount:
		total += flt(je_result[0].amount)

	return total


def get_petty_cash_payments(from_date, to_date, company, cost_center, docstatus=1):
	"""Petty cash payments: Payment Entry (Pay, Cash mode OR paid from a petty
	cash account, party type Supplier — with or without invoice references),
	paid Purchase Invoices (is_paid, Cash mode OR paid into a petty cash
	account), and Journal Entries crediting the branch petty cash account.
	docstatus 1 = approved (submitted), 0 = unapproved (draft/pending).

	The account match is a fallback, not a replacement, for the Mode of Payment
	check: it catches payments posted straight to a petty cash account even when
	Mode of Payment was left blank or set to something not typed "Cash". When a
	cost center is given and resolves to specific branch petty cash account(s),
	the match is scoped to exactly those. Without that (no cost center, or a
	cost center with no Branch Configuration), it falls back to any account of
	type "Cash" — same fallback already used for the JE/Internal Transfer legs
	and for the Cash Balance rows — so blank-Mode-of-Payment entries still show
	up in a company-wide (no cost center) run instead of disappearing."""
	conditions = "pe.docstatus = %(docstatus)s"
	if from_date:
		conditions += " AND pe.posting_date >= %(from_date)s"
	if to_date:
		conditions += " AND pe.posting_date <= %(to_date)s"
	if company:
		conditions += " AND pe.company = %(company)s"

	# Branch petty cash accounts — same resolution used for the JE/Internal
	# Transfer legs below, also used here as the PE/PI account-match fallback.
	accounts = get_branch_petty_cash_accounts(company, cost_center)

	params = {
		"from_date": from_date,
		"to_date": to_date,
		"company": company,
		"cost_center": cost_center,
		"docstatus": docstatus,
		"accounts": tuple(accounts) or ("",),
	}

	# The cost center filter only makes sense for the Mode-of-Payment match: a
	# "Cash" typed Mode of Payment doesn't identify a branch by itself, so we
	# need the row's own cost center to know which branch it belongs to. An
	# account match needs no such filter — the account itself is branch-specific
	# (that's exactly how `accounts` was derived) — so it counts even when the
	# row's own cost center field was left blank. Applying the cost center
	# filter across the whole OR (as before) wrongly vetoed real account matches
	# on rows with a blank cost center.
	pe_mop_cost_center_condition = " AND pe.cost_center = %(cost_center)s" if cost_center else ""
	if accounts:
		pe_acc_join = ""
		pe_account_condition = "pe.paid_from IN %(accounts)s"
	else:
		pe_acc_join = "LEFT JOIN `tabAccount` acc_pe ON acc_pe.name = pe.paid_from"
		pe_account_condition = "acc_pe.account_type = 'Cash'"
		if cost_center:
			pe_account_condition += " AND pe.cost_center = %(cost_center)s"
	payments_pe_result = frappe.db.sql("""
		SELECT SUM(pe.paid_amount) as amount
		FROM `tabPayment Entry` pe
		LEFT JOIN `tabMode of Payment` mop ON mop.name = pe.mode_of_payment
		{pe_acc_join}
		WHERE {conditions}
			AND pe.payment_type = 'Pay'
			AND pe.party_type = 'Supplier'
			AND ((mop.type = 'Cash' {pe_mop_cost_center_condition}) OR {pe_account_condition})
	""".format(conditions=conditions, pe_mop_cost_center_condition=pe_mop_cost_center_condition,
		pe_acc_join=pe_acc_join, pe_account_condition=pe_account_condition), params, as_dict=True)

	pi_conditions = "pi.docstatus = %(docstatus)s AND pi.is_paid = 1"
	if from_date:
		pi_conditions += " AND pi.posting_date >= %(from_date)s"
	if to_date:
		pi_conditions += " AND pi.posting_date <= %(to_date)s"
	if company:
		pi_conditions += " AND pi.company = %(company)s"

	pi_mop_cost_center_condition = " AND pi.cost_center = %(cost_center)s" if cost_center else ""
	if accounts:
		pi_acc_join = ""
		pi_account_condition = "pi.cash_bank_account IN %(accounts)s"
	else:
		pi_acc_join = "LEFT JOIN `tabAccount` acc_pi ON acc_pi.name = pi.cash_bank_account"
		pi_account_condition = "acc_pi.account_type = 'Cash'"
		if cost_center:
			pi_account_condition += " AND pi.cost_center = %(cost_center)s"
	payments_pi_result = frappe.db.sql("""
		SELECT SUM(pi.base_paid_amount) as amount
		FROM `tabPurchase Invoice` pi
		LEFT JOIN `tabMode of Payment` mop ON mop.name = pi.mode_of_payment
		{pi_acc_join}
		WHERE {conditions}
			AND ((mop.type = 'Cash' {pi_mop_cost_center_condition}) OR {pi_account_condition})
	""".format(conditions=pi_conditions, pi_mop_cost_center_condition=pi_mop_cost_center_condition,
		pi_acc_join=pi_acc_join, pi_account_condition=pi_account_condition), params, as_dict=True)

	# Journal Entries paying out of the branch petty cash account (credit side).
	# Same account resolution as the balances: the branch's derived petty cash
	# accounts without a cost center condition, else Cash-type accounts.
	je_conditions = "je.docstatus = %(docstatus)s"
	if from_date:
		je_conditions += " AND je.posting_date >= %(from_date)s"
	if to_date:
		je_conditions += " AND je.posting_date <= %(to_date)s"
	if company:
		je_conditions += " AND je.company = %(company)s"
	if accounts:
		je_join = ""
		je_account_condition = "jea.account IN %(accounts)s"
	else:
		je_join = "INNER JOIN `tabAccount` acc ON acc.name = jea.account"
		je_account_condition = "acc.account_type = 'Cash'"
		if cost_center:
			je_account_condition += " AND jea.cost_center = %(cost_center)s"
	payments_je_result = frappe.db.sql("""
		SELECT SUM(jea.credit) as amount
		FROM `tabJournal Entry Account` jea
		INNER JOIN `tabJournal Entry` je ON je.name = jea.parent
		{je_join}
		WHERE {je_conditions}
			AND jea.credit > 0
			AND {je_account_condition}
	""".format(je_join=je_join, je_conditions=je_conditions, je_account_condition=je_account_condition), params, as_dict=True)

	# Internal Transfer Payment Entries taking cash out of the petty cash account
	# (e.g. depositing till cash to the bank)
	if accounts:
		it_join = ""
		it_account_condition = "pe_it.paid_from IN %(accounts)s"
	else:
		it_join = "INNER JOIN `tabAccount` acc_it ON acc_it.name = pe_it.paid_from"
		it_account_condition = "acc_it.account_type = 'Cash'"
		if cost_center:
			it_account_condition += " AND pe_it.cost_center = %(cost_center)s"
	it_conditions = "pe_it.docstatus = %(docstatus)s AND pe_it.payment_type = 'Internal Transfer'"
	if from_date:
		it_conditions += " AND pe_it.posting_date >= %(from_date)s"
	if to_date:
		it_conditions += " AND pe_it.posting_date <= %(to_date)s"
	if company:
		it_conditions += " AND pe_it.company = %(company)s"
	payments_it_result = frappe.db.sql("""
		SELECT SUM(pe_it.paid_amount) as amount
		FROM `tabPayment Entry` pe_it
		{it_join}
		WHERE {it_conditions}
			AND {it_account_condition}
	""".format(it_join=it_join, it_conditions=it_conditions, it_account_condition=it_account_condition), params, as_dict=True)

	payments_pe = flt(payments_pe_result[0].amount) if payments_pe_result and payments_pe_result[0].amount else 0
	payments_pi = flt(payments_pi_result[0].amount) if payments_pi_result and payments_pi_result[0].amount else 0
	payments_je = flt(payments_je_result[0].amount) if payments_je_result and payments_je_result[0].amount else 0
	payments_it = flt(payments_it_result[0].amount) if payments_it_result and payments_it_result[0].amount else 0
	return payments_pe + payments_pi + payments_je + payments_it


def get_write_off_total(from_date, to_date, company, cost_center):
	"""Loyalty / Write Off: every Payment Entry deduction row on a Receive PE,
	regardless of account (the payment popup writes the company's Write Off
	Account; a manually edited PE can carry a deduction on a different account,
	e.g. bank charges — both count here so no deduction is ever invisible)."""
	conditions = "pe.docstatus = 1 AND pe.payment_type = 'Receive'"
	if from_date:
		conditions += " AND pe.posting_date >= %(from_date)s"
	if to_date:
		conditions += " AND pe.posting_date <= %(to_date)s"
	if company:
		conditions += " AND pe.company = %(company)s"
	cost_center_condition = " AND COALESCE(ded.cost_center, pe.cost_center) = %(cost_center)s" if cost_center else ""
	result = frappe.db.sql("""
		SELECT COALESCE(SUM(ded.amount), 0) as amount
		FROM `tabPayment Entry Deduction` ded
		INNER JOIN `tabPayment Entry` pe ON pe.name = ded.parent
		WHERE {conditions}
			{cost_center_condition}
	""".format(conditions=conditions, cost_center_condition=cost_center_condition), {
		"from_date": from_date,
		"to_date": to_date,
		"company": company,
		"cost_center": cost_center,
	}, as_dict=True)
	return flt(result[0].amount) if result else 0
