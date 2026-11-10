# Copyright (c) 2025, sf_trading and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt, getdate


def execute(filters=None):
	columns = get_columns()
	data = get_data(filters)
	return columns, data


def get_columns():
	return [
		_("Transaction Type") + ":Data:150",
		_("Document") + ":Link/Dynamic Link:120",
		_("Party") + ":Data:200",
		_("Party Name") + ":Data:200",
		_("Mode of Payment") + ":Data:150",
		_("Amount") + ":Currency:120",
		_("Cash Amount") + ":Currency:120",
		_("Bank/Card Amount") + ":Currency:120",
		_("Posting Date") + ":Date:100",
		_("Remarks") + ":Data:300",
	]


def get_data(filters):
	data = []
	
	if not filters.get("date"):
		frappe.throw(_("Please select a date"))
	
	date = getdate(filters.get("date"))
	company = filters.get("company")
	
	# Get Sales Invoices
	sales_data = get_sales_invoices(date, company)
	data.extend(sales_data)
	
	# Get Purchase Invoices
	purchase_data = get_purchase_invoices(date, company)
	data.extend(purchase_data)
	
	# Get Payment Entries
	payment_data = get_payment_entries(date, company)
	data.extend(payment_data)
	
	# Sort by posting date and transaction type
	data.sort(key=lambda x: (x[8], x[0]))  # Sort by posting_date (index 8) and transaction_type (index 0)
	
	return data


def get_sales_invoices(date, company):
	"""Get Sales Invoices with payment details"""
	data = []
	
	conditions = "si.posting_date = %(date)s AND si.docstatus = 1"
	if company:
		conditions += " AND si.company = %(company)s"
	
	# Get Sales Invoices with payment details
	sales_invoices = frappe.db.sql("""
		SELECT 
			si.name,
			si.posting_date,
			si.customer,
			si.customer_name,
			si.grand_total,
			si.net_total,
			si.outstanding_amount,
			si.remarks,
			si.company
		FROM `tabSales Invoice` si
		WHERE {conditions}
		ORDER BY si.posting_date, si.name
	""".format(conditions=conditions), {
		"date": date,
		"company": company
	}, as_dict=True)
	
	for inv in sales_invoices:
		# Get payment details from Sales Invoice Payment
		payment_details = frappe.db.sql("""
			SELECT 
				mode_of_payment,
				SUM(base_amount) as amount
			FROM `tabSales Invoice Payment`
			WHERE parent = %(invoice)s
			GROUP BY mode_of_payment
		""", {"invoice": inv.name}, as_dict=True)
		
		# Get payment details from Payment Entry
		pe_payments = frappe.db.sql("""
			SELECT 
				pe.mode_of_payment,
				SUM(per.allocated_amount) as amount
			FROM `tabPayment Entry` pe
			INNER JOIN `tabPayment Entry Reference` per ON per.parent = pe.name
			WHERE per.reference_doctype = 'Sales Invoice'
				AND per.reference_name = %(invoice)s
				AND pe.docstatus = 1
				AND pe.posting_date = %(date)s
			GROUP BY pe.mode_of_payment
		""", {"invoice": inv.name, "date": date}, as_dict=True)
		
		# Combine payment details
		all_payments = {}
		for pd in payment_details:
			all_payments[pd.mode_of_payment] = all_payments.get(pd.mode_of_payment, 0) + flt(pd.amount)
		
		for pe in pe_payments:
			all_payments[pe.mode_of_payment] = all_payments.get(pe.mode_of_payment, 0) + flt(pe.amount)
		
		# Calculate cash and bank amounts
		cash_amount = 0
		bank_amount = 0
		mode_of_payment_str = ", ".join(all_payments.keys()) if all_payments else ""
		
		for mode, amount in all_payments.items():
			if mode:
				mode_type = frappe.db.get_value("Mode of Payment", mode, "type")
				if mode_type == "Cash":
					cash_amount += flt(amount)
				else:
					bank_amount += flt(amount)
		
		# If no payment details, use grand_total
		if not all_payments:
			bank_amount = inv.grand_total
		
		data.append([
			"Sales Invoice",
			inv.name,
			inv.customer,
			inv.customer_name or "",
			mode_of_payment_str or "Not Paid",
			inv.grand_total,
			cash_amount,
			bank_amount,
			inv.posting_date,
			inv.remarks or ""
		])
	
	return data


def get_purchase_invoices(date, company):
	"""Get Purchase Invoices with payment details"""
	data = []
	
	conditions = "pi.posting_date = %(date)s AND pi.docstatus = 1"
	if company:
		conditions += " AND pi.company = %(company)s"
	
	# Get Purchase Invoices with payment details
	purchase_invoices = frappe.db.sql("""
		SELECT 
			pi.name,
			pi.posting_date,
			pi.supplier,
			pi.supplier_name,
			pi.grand_total,
			pi.net_total,
			pi.outstanding_amount,
			pi.remarks,
			pi.company
		FROM `tabPurchase Invoice` pi
		WHERE {conditions}
		ORDER BY pi.posting_date, pi.name
	""".format(conditions=conditions), {
		"date": date,
		"company": company
	}, as_dict=True)
	
	for inv in purchase_invoices:
		# Get payment details from Payment Entry
		pe_payments = frappe.db.sql("""
			SELECT 
				pe.mode_of_payment,
				SUM(per.allocated_amount) as amount
			FROM `tabPayment Entry` pe
			INNER JOIN `tabPayment Entry Reference` per ON per.parent = pe.name
			WHERE per.reference_doctype = 'Purchase Invoice'
				AND per.reference_name = %(invoice)s
				AND pe.docstatus = 1
				AND pe.posting_date = %(date)s
			GROUP BY pe.mode_of_payment
		""", {"invoice": inv.name, "date": date}, as_dict=True)
		
		# Calculate cash and bank amounts
		cash_amount = 0
		bank_amount = 0
		mode_of_payment_str = ", ".join([p.mode_of_payment for p in pe_payments if p.mode_of_payment]) if pe_payments else ""
		
		for pe in pe_payments:
			if pe.mode_of_payment:
				mode_type = frappe.db.get_value("Mode of Payment", pe.mode_of_payment, "type")
				if mode_type == "Cash":
					cash_amount += flt(pe.amount)
				else:
					bank_amount += flt(pe.amount)
		
		# If no payment details, use grand_total
		if not pe_payments:
			bank_amount = inv.grand_total
		
		data.append([
			"Purchase Invoice",
			inv.name,
			inv.supplier,
			inv.supplier_name or "",
			mode_of_payment_str or "Not Paid",
			inv.grand_total,
			cash_amount,
			bank_amount,
			inv.posting_date,
			inv.remarks or ""
		])
	
	return data


def get_payment_entries(date, company):
	"""Get Payment Entries (both cash and bank/card)"""
	data = []
	
	conditions = "pe.posting_date = %(date)s AND pe.docstatus = 1"
	if company:
		conditions += " AND pe.company = %(company)s"
	
	# Get Payment Entries
	payment_entries = frappe.db.sql("""
		SELECT 
			pe.name,
			pe.posting_date,
			pe.party_type,
			pe.party,
			pe.party_name,
			pe.mode_of_payment,
			pe.paid_amount,
			pe.received_amount,
			pe.payment_type,
			pe.remarks,
			pe.company
		FROM `tabPayment Entry` pe
		WHERE {conditions}
		ORDER BY pe.posting_date, pe.name
	""".format(conditions=conditions), {
		"date": date,
		"company": company
	}, as_dict=True)
	
	for pe in payment_entries:
		amount = pe.paid_amount if pe.payment_type == "Pay" else pe.received_amount
		
		# Determine if cash or bank
		cash_amount = 0
		bank_amount = 0
		
		if pe.mode_of_payment:
			mode_type = frappe.db.get_value("Mode of Payment", pe.mode_of_payment, "type")
			if mode_type == "Cash":
				cash_amount = amount
			else:
				bank_amount = amount
		else:
			# Default to bank if no mode specified
			bank_amount = amount
		
		party_display = pe.party_name or pe.party or ""
		party_type_display = "Customer" if pe.party_type == "Customer" else "Supplier" if pe.party_type == "Supplier" else pe.party_type
		
		data.append([
			"Payment Entry",
			pe.name,
			pe.party or "",
			party_display,
			pe.mode_of_payment or "",
			amount,
			cash_amount,
			bank_amount,
			pe.posting_date,
			pe.remarks or ""
		])
	
	return data
