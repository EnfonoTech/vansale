import json

import frappe
from frappe import _
from frappe.utils import flt


@frappe.whitelist()
def get_available_credit(customer: str, company: str) -> float:
	"""
	Return the available credit for a customer:
	  credit_limit (from Customer Credit Limit child table)
	  minus sum of outstanding_amount on submitted Sales Invoices
	  where custom_payment_mode = 'Credit'.
	"""
	if not customer or not company:
		return 0.0

	# Credit limit defined on Customer for this company
	row = frappe.db.get_value(
		"Customer Credit Limit",
		{"parent": customer, "company": company},
		"credit_limit",
	)
	if row is None:
		# Fallback: first credit limit regardless of company
		row = frappe.db.get_value(
			"Customer Credit Limit",
			{"parent": customer},
			"credit_limit",
		)
	credit_limit = flt(row)
	if not credit_limit:
		return 0.0

	used = frappe.db.sql(
		"""
		SELECT IFNULL(SUM(grand_total), 0)
		FROM `tabSales Invoice`
		WHERE customer = %s
		  AND company = %s
		  AND custom_payment_mode = 'Credit'
		  AND docstatus = 1
		""",
		(customer, company),
	)[0][0]

	return max(0.0, flt(credit_limit) - flt(used))


@frappe.whitelist()
def get_payment_modes_with_account(company: str, is_return: int | str = 0, is_pdc: int | str = 0, branch: str = None):
	"""
	Return Mode of Payment names that are enabled and have a default Cash/Bank
	account for the given company. Use this to avoid "Please set default Cash or
	Bank account" or disabled-mode errors when showing the payment popup.

	The list is built from all enabled modes with a default account, then
	restricted to the branch allowlist. POS Profile is not consulted.

	Args:
		company: Company name
		is_return: 1 when the invoice is a return (filters to for_return modes)
		is_pdc: 1 when collecting PDC modes (filters to for_pdc modes)
		branch: Branch to restrict Cash/Bank modes to (from the document)

	Returns:
		List of mode names that are enabled and have default account for company.
	"""
	if not company:
		return []

	# Modes that have a default account for this company
	has_account = frappe.db.sql(
		"""
		SELECT DISTINCT parent
		FROM `tabMode of Payment Account`
		WHERE company = %s AND default_account IS NOT NULL AND default_account != ''
		""",
		(company,),
		as_list=True,
	)
	modes_with_account = {r[0] for r in has_account}

	enabled = frappe.get_all(
		"Mode of Payment",
		filters={"enabled": 1},
		pluck="name",
		ignore_permissions=True,
	)

	# Intersection: enabled and has default account for company
	valid = [m for m in enabled if m in modes_with_account]

	# PDC filter: applied globally regardless of user/branch.
	# for_pdc MoPs only appear in PDC mode; they are excluded from all other popups.
	all_pdc_mops = set(
		frappe.get_all(
			"Branch Configuration Mode of Payment",
			filters={"for_pdc": 1},
			pluck="mode_of_payment",
			ignore_permissions=True,
		)
	)
	if frappe.utils.cint(is_pdc):
		if all_pdc_mops:
			valid = [m for m in valid if m in all_pdc_mops]
	else:
		if all_pdc_mops:
			valid = [m for m in valid if m not in all_pdc_mops]

	valid = _restrict_to_branch_allowlist(valid, company, is_return=frappe.utils.cint(is_return), branch=branch)
	return valid


@frappe.whitelist()
def branch_has_pdc_modes(branch: str) -> bool:
	"""Return True if the branch has at least one 'For PDC' mode of payment configured."""
	if not branch:
		return False
	return bool(
		frappe.db.exists(
			"Branch Configuration Mode of Payment",
			{"parent": branch, "parenttype": "Branch Configuration", "for_pdc": 1},
		)
	)


def _restrict_to_branch_allowlist(modes: list, company: str, is_return: int = 0, branch: str = None) -> list:
	"""
	Return only the MOPs that are configured in the document branch's
	Branch Configuration Mode of Payment table.

	- No branch set → return empty list (show nothing).
	- Branch has no MOPs configured → return empty list (show nothing).
	- No role bypasses — rule applies to everyone.
	"""
	if not modes:
		return []

	if not branch:
		return []

	filters = {"parent": branch, "parenttype": "Branch Configuration"}
	if is_return:
		filters["for_return"] = 1

	configured = frappe.get_all(
		"Branch Configuration Mode of Payment",
		filters=filters,
		pluck="mode_of_payment",
		ignore_permissions=True,
	)

	if not configured:
		return []

	allowed = set(configured)
	return [m for m in modes if m in allowed]


@frappe.whitelist()
def get_accounts_for_modes(company: str, modes: str | list):
	"""Return {mode_of_payment: account} for each mode in the list.

	Uses the same logic as Sales Invoice.set_account_for_mode_of_payment but
	doesn't require write permission on the document.
	"""
	if not company:
		return {}
	if isinstance(modes, str):
		try:
			modes = json.loads(modes) if modes else []
		except Exception:
			modes = []
	if not modes:
		return {}

	from erpnext.accounts.doctype.sales_invoice.sales_invoice import get_bank_cash_account

	result = {}
	for mode in modes:
		if mode:
			result[mode] = (get_bank_cash_account(mode, company) or {}).get("account") or ""
	return result


@frappe.whitelist()
def create_pos_payments_for_invoice(
	sales_invoice: str,
	payments: str | list,
	cheque_date: str = None,
	cheque_no: str = None,
	posting_date: str = None,
	write_off_amount: float | str = 0,
):
	"""
	Create Payment Entry records for a submitted POS Sales Invoice, one per mode of payment.

	Args:
		sales_invoice: Sales Invoice name
		payments: JSON list or Python list of dicts:
			[{ "mode_of_payment": "Cash", "amount": 100.0 }, ...]
		posting_date: Payment Entry posting and reference date; defaults to the
			invoice's posting date (submit-time collection). The Receive Payment
			flow passes the actual payment date.
		write_off_amount: Small unpaid balance to book as a deduction on the
			last Payment Entry (same mechanism as the PE form's "Write Off
			Difference Amount" button). Uses the Company's Write Off Account,
			capped by the Company's Max Payment Write Off, cost center from the
			invoice (fallback: company default).

	Returns:
		List of created Payment Entry names.
	"""

	if not sales_invoice:
		frappe.throw(_("Sales Invoice is required"))

	si = frappe.get_doc("Sales Invoice", sales_invoice)

	if si.docstatus != 1:
		frappe.throw(
			_("Sales Invoice {0} must be submitted before creating payments.").format(
				si.name
			)
		)

	# Parse payments argument
	if isinstance(payments, str):
		try:
			payments = json.loads(payments)
		except Exception:
			frappe.throw(_("Invalid payments payload"))

	if not isinstance(payments, (list, tuple)) or not payments:
		frappe.throw(_("No payment rows were provided."))

	# Filter and validate rows (Cash and non-Cash; for Bank we set reference_no/reference_date)
	valid_rows = []
	for row in payments:
		mode_of_payment = (row or {}).get("mode_of_payment")
		amount = frappe.utils.flt((row or {}).get("amount"))
		if not mode_of_payment or amount <= 0:
			continue
		valid_rows.append({"mode_of_payment": mode_of_payment, "amount": amount})

	if not valid_rows:
		frappe.throw(_("No valid payment rows found (non-zero amounts with mode of payment)."))

	# Write-off: validate limit and resolve account/cost center up front,
	# before any Payment Entry is created.
	write_off_amount = flt(write_off_amount)
	if write_off_amount < 0:
		frappe.throw(_("Write off amount cannot be negative."))
	write_off_account = None
	write_off_cost_center = None
	if write_off_amount > 0:
		if si.is_return:
			frappe.throw(_("Write off is not allowed on return invoices."))
		company_defaults = frappe.db.get_value(
			"Company",
			si.company,
			["write_off_account", "custom_max_payment_write_off", "cost_center"],
			as_dict=True,
		)
		max_write_off = flt(company_defaults.custom_max_payment_write_off)
		if not max_write_off:
			frappe.throw(
				_("Set 'Max Payment Write Off' on company {0} to allow write off in payments.").format(si.company)
			)
		if write_off_amount - max_write_off > 0.0001:
			frappe.throw(
				_("Write off amount {0} exceeds the company limit of {1}.").format(
					write_off_amount, max_write_off
				)
			)
		write_off_account = company_defaults.write_off_account
		if not write_off_account:
			frappe.throw(_("Set 'Write Off Account' on company {0}.").format(si.company))
		write_off_cost_center = si.get("cost_center") or company_defaults.cost_center
		if not write_off_cost_center:
			frappe.throw(
				_("Set a Cost Center on the invoice or a default Cost Center on company {0}.").format(si.company)
			)

	created = []

	from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry
	from erpnext.accounts.doctype.sales_invoice.sales_invoice import get_bank_cash_account

	number_format = frappe.db.get_value("Currency", si.currency, "number_format") or "#,###.##"
	currency_precision = len(number_format.split(".")[-1]) if "." in number_format else 0

	for idx, row in enumerate(valid_rows):
		# Reload invoice each time so outstanding is up to date after previous payments
		si.reload()
		outstanding = frappe.utils.flt(si.outstanding_amount, currency_precision)
		amount = frappe.utils.flt(row["amount"], currency_precision)

		if amount <= 0:
			continue

		# The write-off rides on the last Payment Entry: it allocates
		# payment + write-off against the invoice, balanced by a deduction row.
		row_write_off = write_off_amount if idx == len(valid_rows) - 1 else 0

		if amount + row_write_off - abs(outstanding) > 0.0001:
			frappe.throw(
				_(
					"Payment amount {0} plus write off is greater than outstanding amount {1} for invoice {2}."
				).format(amount + row_write_off, outstanding, si.name)
			)

		pe = get_payment_entry("Sales Invoice", si.name)

		# Set the specific mode of payment and amount
		pe.mode_of_payment = row["mode_of_payment"]

		bank_cash = get_bank_cash_account(row["mode_of_payment"], si.company)
		bank_account = bank_cash.get("account")

		# For return SIs, payment_type is "Pay": cash/bank goes on paid_from.
		# For normal SIs, payment_type is "Receive": cash/bank goes on paid_to.
		if pe.payment_type == "Pay":
			pe.paid_from = bank_account
			if bank_account:
				acc = frappe.get_cached_value(
					"Account", bank_account, ["account_currency", "account_type"], as_dict=True
				)
				if acc:
					pe.paid_from_account_currency = acc.account_currency
		else:
			pe.paid_to = bank_account
			if bank_account:
				acc = frappe.get_cached_value(
					"Account", bank_account, ["account_currency", "account_type"], as_dict=True
				)
				if acc:
					pe.paid_to_account_currency = acc.account_currency
					pe.paid_to_account_type = acc.account_type

		# Clamp to the reference row's actual outstanding to avoid sub-cent validation
		# failures (e.g. user pays 1.11 but DB outstanding is 1.109 after rounding).
		if pe.references:
			ref = pe.references[0]
			ref_outstanding = frappe.utils.flt(ref.outstanding_amount)
			effective_amount = min(amount, abs(ref_outstanding))
			pe.paid_amount = effective_amount
			pe.received_amount = effective_amount
			allocated = min(effective_amount + row_write_off, abs(ref_outstanding))
			ref.allocated_amount = -allocated if pe.payment_type == "Pay" else allocated
		else:
			if row_write_off:
				frappe.throw(
					_("Cannot apply write off: no outstanding reference found for invoice {0}.").format(si.name)
				)
			pe.paid_amount = amount
			pe.received_amount = amount

		if row_write_off:
			pe.append(
				"deductions",
				{
					"account": write_off_account,
					"cost_center": write_off_cost_center,
					"amount": row_write_off,
				},
			)

		# PDC: posting date = invoice date; reference date = future cheque date
		if cheque_date:
			pe.posting_date = si.posting_date
			pe.reference_no = cheque_no or si.name
			pe.reference_date = cheque_date
		else:
			pe.posting_date = posting_date or si.posting_date
			pe.reference_no = si.name
			pe.reference_date = posting_date or si.posting_date

		pe.insert()

		# Bypass workflow state transition validation for auto-created PEs.
		# ignore_workflow skips the "Draft -> Pending" transition check.
		# ignore_validate skips before_submit hooks (e.g. attachment requirements).
		pe.flags.ignore_workflow = True
		pe.flags.ignore_validate = True

		pe.submit()
		created.append(pe.name)

	return created

