"""
Sales Invoice overrides: remove empty item rows before validation (barcode scanner scan row).
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import today


def before_validate(doc, _method=None):
	"""Remove item rows that have no item_code (leftover scan row from barcode). Runs before validation."""
	# Frappe v15 field_order Property Setter bug: is_pos can arrive as a list
	# instead of a scalar. Coerce it before ERPNext's validation sees it.
	if isinstance(doc.is_pos, list):
		doc.is_pos = 1 if doc.is_pos else 0

	if not doc.get("items"):
		frappe.throw(_("Please add at least one item before saving."))

	# Remove in reverse so indices stay valid
	to_remove = [row for row in doc.items if not (row.get("item_code") or "").strip()]
	for row in to_remove:
		doc.remove(row)
	for i, row in enumerate(doc.items, start=1):
		row.idx = i

	if not doc.items:
		frappe.throw(_("Please add at least one item before saving."))


def validate(doc, _method=None):
	"""Block new credit invoice if customer has overdue unsettled credit."""
	if doc.is_return:
		return
	if doc.custom_payment_mode != "Credit":
		return
	if not doc.customer:
		return

	inv = _get_overdue_invoice(doc.customer, doc.company, as_of_date=doc.posting_date)
	if inv:
		inv_link = frappe.utils.get_link_to_form("Sales Invoice", inv.name)
		frappe.throw(
			_(
				"Cannot create a new credit invoice for {0}. "
				"Invoice {1} dated {2} has an outstanding amount of {3} "
				"that is overdue. Please settle the outstanding balance first."
			).format(
				frappe.bold(doc.customer),
				inv_link,
				inv.posting_date,
				frappe.utils.fmt_money(inv.outstanding_amount, currency=doc.currency),
			),
			title=_("Overdue Invoice"),
		)


def _get_overdue_invoice(customer, company, as_of_date=None):
	"""Return the oldest overdue credit invoice for the customer, or None.

	Uses the Credit Days configured on the Customer Credit Limit row for the
	given company. Returns None if no credit days are set (validation disabled).

	as_of_date is the date "overdue" is measured against - the posting date of
	the invoice being created, not necessarily the real calendar date. This
	matters when an invoice is deliberately post-dated: the credit-days clock
	should run from the older invoice's posting date to the new invoice's
	posting date, not to whatever today happens to be.
	"""
	credit_days = frappe.db.get_value(
		"Customer Credit Limit",
		{"parent": customer, "company": company},
		"custom_credit_days",
	)
	if not credit_days:
		return None

	rows = frappe.db.sql(
		"""
		SELECT name, posting_date, outstanding_amount
		FROM `tabSales Invoice`
		WHERE customer = %s
		  AND company = %s
		  AND custom_payment_mode = 'Credit'
		  AND docstatus = 1
		  AND outstanding_amount > 0
		  AND DATEDIFF(%s, posting_date) > %s
		ORDER BY posting_date ASC
		LIMIT 1
		""",
		(customer, company, as_of_date or today(), frappe.utils.cint(credit_days)),
		as_dict=True,
	)
	return rows[0] if rows else None


def validate_driver_payment(doc, _method=None):
	"""Block new Cash+Driver invoice if the same driver has an overdue unsettled invoice."""
	if doc.is_return:
		return
	if doc.custom_payment_mode == "Credit":
		return
	if not doc.get("custom_driver"):
		return

	inv = _get_driver_overdue_invoice(doc.custom_driver, doc.name, as_of_date=doc.posting_date)
	if inv:
		inv_link = frappe.utils.get_link_to_form("Sales Invoice", inv.name)
		payment_days = frappe.db.get_value("Driver", doc.custom_driver, "custom_payment_days") or 1
		driver_name = frappe.db.get_value("Driver", doc.custom_driver, "full_name") or doc.custom_driver
		frappe.throw(
			_(
				"Delivery Person {0} has an unsettled invoice {1} dated {2} with outstanding amount {3}. "
				"Payment was due within {4} day(s). Please collect and record the payment first."
			).format(
				frappe.bold(driver_name),
				inv_link,
				inv.posting_date,
				frappe.utils.fmt_money(inv.outstanding_amount, currency=doc.currency),
				payment_days,
			),
			title=_("Delivery Person Payment Overdue"),
		)


def _get_driver_overdue_invoice(driver, exclude_name=None, as_of_date=None):
	"""Return the oldest overdue uncleared Cash invoice for the driver, or None."""
	payment_days = frappe.utils.cint(
		frappe.db.get_value("Driver", driver, "custom_payment_days") or 1
	)

	conditions = """
		SELECT name, posting_date, outstanding_amount
		FROM `tabSales Invoice`
		WHERE custom_driver = %s
		  AND docstatus = 1
		  AND outstanding_amount > 0
		  AND DATEDIFF(%s, posting_date) > %s
	"""
	params = [driver, as_of_date or today(), payment_days]

	if exclude_name:
		conditions += " AND name != %s"
		params.append(exclude_name)

	conditions += " ORDER BY posting_date ASC LIMIT 1"

	rows = frappe.db.sql(conditions, params, as_dict=True)
	return rows[0] if rows else None


@frappe.whitelist()
def check_driver_payment_overdue(driver):
	"""Client-side check: return the oldest overdue driver invoice dict or None."""
	if not driver:
		return None
	return _get_driver_overdue_invoice(driver)


@frappe.whitelist()
def check_customer_credit_overdue(customer, company):
	"""Client-side check: return the oldest overdue invoice dict or None."""
	return _get_overdue_invoice(customer, company)


@frappe.whitelist()
def get_credit_limit_status(customer, company):
	"""Client-side check: customer's credit limit and current outstanding for a company.
	Used by the real-time credit-limit popup while items are being added on Sales Invoice."""
	if not customer or not company:
		return {"credit_limit": 0, "outstanding": 0, "currency": None}

	from erpnext.selling.doctype.customer.customer import get_credit_limit, get_customer_outstanding
	from frappe.utils import flt

	credit_limit = flt(get_credit_limit(customer, company))
	outstanding = flt(get_customer_outstanding(customer, company)) if credit_limit else 0
	return {
		"credit_limit": credit_limit,
		"outstanding": outstanding,
		"currency": frappe.get_cached_value("Company", company, "default_currency"),
	}
