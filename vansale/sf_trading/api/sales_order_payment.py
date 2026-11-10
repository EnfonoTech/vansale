import json

import frappe
from frappe import _
from frappe.utils import flt


@frappe.whitelist()
def create_pos_payments_for_order(
	sales_order: str,
	payments: str | list,
	cheque_date: str = None,
	cheque_no: str = None,
	posting_date: str = None,
	write_off_amount: float | str = 0,
):
	"""
	Create Payment Entry records for a submitted Sales Order, one per mode of
	payment, allocated as an advance against the order.

	Mirrors sales_invoice_payment.create_pos_payments_for_invoice, but against
	Sales Order's advance_paid/grand_total instead of outstanding_amount (Sales
	Order has no outstanding_amount or is_return).

	Args:
		sales_order: Sales Order name
		payments: JSON list or Python list of dicts:
			[{ "mode_of_payment": "Cash", "amount": 100.0 }, ...]
		posting_date: Payment Entry posting and reference date; defaults to the
			order's transaction date.
		write_off_amount: Small unpaid balance to book as a deduction on the
			last Payment Entry, same mechanism as the Sales Invoice flow.

	Returns:
		List of created Payment Entry names.
	"""

	if not sales_order:
		frappe.throw(_("Sales Order is required"))

	so = frappe.get_doc("Sales Order", sales_order)

	if so.docstatus != 1:
		frappe.throw(_("Sales Order {0} must be submitted before creating payments.").format(so.name))

	if isinstance(payments, str):
		try:
			payments = json.loads(payments)
		except Exception:
			frappe.throw(_("Invalid payments payload"))

	if not isinstance(payments, (list, tuple)) or not payments:
		frappe.throw(_("No payment rows were provided."))

	valid_rows = []
	for row in payments:
		mode_of_payment = (row or {}).get("mode_of_payment")
		amount = flt((row or {}).get("amount"))
		if not mode_of_payment or amount <= 0:
			continue
		valid_rows.append({"mode_of_payment": mode_of_payment, "amount": amount})

	if not valid_rows:
		frappe.throw(_("No valid payment rows found (non-zero amounts with mode of payment)."))

	# Write-off: validate limit and resolve account/cost center up front.
	write_off_amount = flt(write_off_amount)
	if write_off_amount < 0:
		frappe.throw(_("Write off amount cannot be negative."))
	write_off_account = None
	write_off_cost_center = None
	if write_off_amount > 0:
		company_defaults = frappe.db.get_value(
			"Company",
			so.company,
			["write_off_account", "custom_max_payment_write_off", "cost_center"],
			as_dict=True,
		)
		max_write_off = flt(company_defaults.custom_max_payment_write_off)
		if not max_write_off:
			frappe.throw(
				_("Set 'Max Payment Write Off' on company {0} to allow write off in payments.").format(so.company)
			)
		if write_off_amount - max_write_off > 0.0001:
			frappe.throw(
				_("Write off amount {0} exceeds the company limit of {1}.").format(write_off_amount, max_write_off)
			)
		write_off_account = company_defaults.write_off_account
		if not write_off_account:
			frappe.throw(_("Set 'Write Off Account' on company {0}.").format(so.company))
		write_off_cost_center = so.get("cost_center") or company_defaults.cost_center
		if not write_off_cost_center:
			frappe.throw(
				_("Set a Cost Center on the order or a default Cost Center on company {0}.").format(so.company)
			)

	created = []

	from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry
	from erpnext.accounts.doctype.sales_invoice.sales_invoice import get_bank_cash_account

	number_format = frappe.db.get_value("Currency", so.currency, "number_format") or "#,###.##"
	currency_precision = len(number_format.split(".")[-1]) if "." in number_format else 0

	for idx, row in enumerate(valid_rows):
		# Reload so advance_paid reflects previously created Payment Entries in this loop
		so.reload()
		outstanding = flt(flt(so.grand_total) - flt(so.advance_paid), currency_precision)
		amount = flt(row["amount"], currency_precision)

		if amount <= 0:
			continue

		row_write_off = write_off_amount if idx == len(valid_rows) - 1 else 0

		if amount + row_write_off - outstanding > 0.0001:
			frappe.throw(
				_(
					"Payment amount {0} plus write off is greater than outstanding amount {1} for order {2}."
				).format(amount + row_write_off, outstanding, so.name)
			)

		pe = get_payment_entry("Sales Order", so.name)

		pe.mode_of_payment = row["mode_of_payment"]

		bank_cash = get_bank_cash_account(row["mode_of_payment"], so.company)
		bank_account = bank_cash.get("account")

		pe.paid_to = bank_account
		if bank_account:
			acc = frappe.get_cached_value(
				"Account", bank_account, ["account_currency", "account_type"], as_dict=True
			)
			if acc:
				pe.paid_to_account_currency = acc.account_currency
				pe.paid_to_account_type = acc.account_type

		# Clamp to the reference row's actual outstanding to avoid sub-cent validation failures.
		if pe.references:
			ref = pe.references[0]
			ref_outstanding = flt(ref.outstanding_amount)
			effective_amount = min(amount, abs(ref_outstanding))
			pe.paid_amount = effective_amount
			pe.received_amount = effective_amount
			allocated = min(effective_amount + row_write_off, abs(ref_outstanding))
			ref.allocated_amount = allocated
		else:
			if row_write_off:
				frappe.throw(
					_("Cannot apply write off: no outstanding reference found for order {0}.").format(so.name)
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

		# PDC: posting date = order date; reference date = future cheque date
		if cheque_date:
			pe.posting_date = so.transaction_date
			pe.reference_no = cheque_no or so.name
			pe.reference_date = cheque_date
		else:
			pe.posting_date = posting_date or so.transaction_date
			pe.reference_no = so.name
			pe.reference_date = posting_date or so.transaction_date

		pe.insert()

		# Bypass workflow state transition validation for auto-created PEs.
		pe.flags.ignore_workflow = True
		pe.flags.ignore_validate = True

		pe.submit()
		created.append(pe.name)

	return created
