# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Purchase Register extended with the receipts nobody has billed yet.

Core's Purchase Register lists Purchase Invoices and nothing else, so the
purchases figure it produces stops at what has been billed. Goods that arrived
and have not been invoiced are real purchases for the trading account, and they
are missing from it.

This report adds them, and adds ONLY the part that is missing. For every
Purchase Receipt in the period it prints the value no Purchase Invoice has
billed, worked out from the same row links the open item reports use
(`vansale.sf_trading.open_items`):

    fully billed receipt   -> does not appear at all
    partly billed receipt  -> appears for its remainder only
    unbilled receipt       -> appears in full

The invoice always carries the billed part on its own line, so no value is
counted twice and no value is dropped. A Purchase Invoice that updates stock
needs no receipt and appears once, as an invoice.

WHY THE UNBILLED PART IS MEASURED AS OF THE PERIOD END, NOT TODAY
-----------------------------------------------------------------
`received_items_pending_billing` reconstructs what has been billed from the
counterpart rows filtered by their own posting date, so passing the period end
as `as_on` answers "what was still unbilled on that date". A January receipt
invoiced in February therefore counts as an unbilled January purchase, and the
February invoice counts in February — the value lands in exactly one period and
re-running January next year gives the same answer. Measuring against today
instead would quietly move that value out of January the moment the invoice was
raised, and January would under-report for good.

SCOPE, AND THE ONE PLACE IT PARTS FROM THE OPERATIONAL REPORT
--------------------------------------------------------------
Receipt rows are submitted, non-return, stock-item rows, excluding rows raised
from an invoice (the bill-first flow, where the invoice already carries the
value).

`Received Items Pending Billing` additionally skips receipts marked Closed or
Completed, which is right for a to-do list. This report does NOT, because that
status describes today: a July receipt invoiced in August reads Completed now,
and judging by it would erase the receipt from July even though July closed
with it unbilled. Billed-ness here is established from the dated row links
instead, which is the accurate test and the only one that stays stable when the
period is re-run later. The two reports therefore agree for the current period
and can differ for a closed one — by exactly the receipts invoiced after it
ended, which is the intended behaviour.

RETURNS
-------
A purchase return reduces purchases and reaches the report one of two ways. A
supplier debit note is a Purchase Invoice with is_return and appears on the
invoice side as a negative. Goods sent back on a return Purchase Receipt with
no debit note behind it yet appear as their own negative line, for the part no
debit note covers. Receipt lines therefore do NOT net returns away, because a
return against an already fully billed receipt would be netted against nothing
and vanish — and on this data some returns name no receipt at all.

Landed Cost Voucher charges follow the goods. A voucher is raised against a
Purchase Receipt, but that receipt leaves this report once it is billed, so the
charge is carried onto the invoice that billed it and split proportionally when
a receipt is only part billed — the invoice takes the share it billed, the
receipt keeps the share it still holds, and the two add back to the voucher.
The charges sit in their own column rather than inside the purchase value,
because a Landed Cost Voucher posts to stock valuation and not to the supplier
bill.

HOW THE INVOICE HALF RELATES TO CORE'S PURCHASE REGISTER
---------------------------------------------------------
Both total an invoice from its item rows rather than its header, so they agree
on most data and did so exactly for July on production. They can still differ,
and the reason is worth knowing before anyone reconciles the two.

Core folds a Purchase Taxes and Charges row into its net_total when the row is
categorised Total and its ACCOUNT HEAD also happens to be used as an item
expense account somewhere in the same filtered set — a Deduct row arriving as a
negative. Whether a given charge lands in net_total or in its own tax column
therefore depends on the mix of invoices on screen, so core's net_total is not
a fixed definition of purchase value. On UAT that pulls three Customs Clearance
charges (55.56 in July) out of core's total while leaving Customs Duty and
Freight in tax columns.

This report always reports the same thing: the goods value on the bill, the sum
of the item rows. It does not move when the filters change.
"""

import frappe
from frappe import _
from frappe.query_builder.custom import ConstantColumn
from frappe.query_builder import Case
from frappe.query_builder.functions import Sum
from frappe.utils import cint, flt, getdate

from vansale.sf_trading.open_items import received_items_pending_billing

INVOICED = "Invoiced"
INVOICED_WITH_STOCK = "Invoiced (Updates Stock)"
DEBIT_NOTE = "Debit Note"
UNBILLED_RECEIPT = "Unbilled Receipt"
UNBILLED_RETURN = "Unbilled Purchase Return"

SCOPE_BOTH = "Invoices and Unbilled Receipts"
SCOPE_INVOICES = "Invoices Only"
SCOPE_RECEIPTS = "Unbilled Receipts Only"

ITEM_TYPE_STOCK = "Stock Items Only"
ITEM_TYPE_ALL = "All Items"


def execute(filters=None):
	filters = frappe._dict(filters or {})
	validate_filters(filters)

	scope = resolve_scope(filters)

	rows = []
	if scope in (SCOPE_BOTH, SCOPE_INVOICES):
		rows += get_invoice_rows(filters)
	if scope in (SCOPE_BOTH, SCOPE_RECEIPTS):
		rows += get_receipt_rows(filters)
		rows += get_return_rows(filters)

	attach_landed_cost(rows, filters)
	rows.sort(key=lambda row: (getdate(row["posting_date"]), row["voucher_no"]))

	return get_columns(), rows


def resolve_scope(filters):
	"""What to list, as a Select rather than a checkbox, and here is why.

	`query_report.js` collects filter values with `.filter((f) => f.get_value())`,
	so a Check the user has just UNTICKED is falsy and never reaches the server
	at all. Server-side it is indistinguishable from "not supplied", so a
	checkbox that defaults to on can never be turned off — unticking Include
	Unbilled Receipts left the receipts on the report. A Select always sends a
	non-empty value, so the choice always arrives.

	`include_unbilled_receipts` is still honoured for anything calling this
	report in code, where a real 0 does come through.
	"""
	scope = filters.get("scope")
	if scope in (SCOPE_BOTH, SCOPE_INVOICES, SCOPE_RECEIPTS):
		return scope

	if "include_unbilled_receipts" in filters and not cint(filters.get("include_unbilled_receipts")):
		return SCOPE_INVOICES

	return SCOPE_BOTH


def stock_items_only(filters) -> bool:
	"""Default to goods, because the register exists to feed the trading account.

	Purchases in Opening + Purchases - Closing = COGS means goods. A freight or
	consultancy bill is an expense, not inventory, so it is left out unless the
	reader asks for All Items — at which point BOTH halves widen together, and
	the invoice half lines up with core's Purchase Register again.
	"""
	return filters.get("item_type", ITEM_TYPE_STOCK) != ITEM_TYPE_ALL


def validate_filters(filters):
	if not filters.get("company"):
		frappe.throw(_("Company is required"))
	if not (filters.get("from_date") and filters.get("to_date")):
		frappe.throw(_("From Date and To Date are required"))
	if getdate(filters.from_date) > getdate(filters.to_date):
		frappe.throw(_("From Date cannot be after To Date"))


# ---------------------------------------------------------------------------
# the billed side — Purchase Invoices, as core lists them
# ---------------------------------------------------------------------------


def get_invoice_rows(filters):
	invoice = frappe.qb.DocType("Purchase Invoice")

	query = (
		frappe.qb.from_(invoice)
		.select(
			ConstantColumn("Purchase Invoice").as_("voucher_type"),
			invoice.name.as_("voucher_no"),
			invoice.posting_date,
			invoice.company,
			invoice.supplier,
			invoice.supplier_name,
			invoice.supplier_group,
			invoice.bill_no,
			invoice.bill_date,
			invoice.is_return,
			invoice.update_stock,
			invoice.base_net_total,
			invoice.base_total_taxes_and_charges,
			invoice.base_grand_total,
		)
		.where(
			(invoice.docstatus == 1)
			& (invoice.company == filters.company)
			& (invoice.posting_date >= getdate(filters.from_date))
			& (invoice.posting_date <= getdate(filters.to_date))
		)
	)

	if filters.get("supplier"):
		query = query.where(invoice.supplier == filters.supplier)
	if filters.get("supplier_group"):
		query = query.where(invoice.supplier_group == filters.supplier_group)
	if filters.get("mode_of_payment"):
		query = query.where(invoice.mode_of_payment == filters.mode_of_payment)
	for fieldname in ("cost_center", "warehouse", "item_group"):
		if filters.get(fieldname):
			query = query.where(
				invoice.name.isin(
					parents_with_item_field("Purchase Invoice Item", fieldname, filters.get(fieldname))
				)
			)

	records = query.run(as_dict=True)
	item_totals = get_invoice_item_totals([record.voucher_no for record in records])
	goods_only = stock_items_only(filters)

	rows = []
	for record in records:
		totals = item_totals.get(record.voucher_no) or {}
		full_net = flt(totals.get("net")) or flt(record.base_net_total)
		stock_net = flt(totals.get("stock_net"))

		net = stock_net if goods_only else full_net
		tax = flt(record.base_total_taxes_and_charges)
		total = flt(record.base_grand_total)

		if goods_only:
			if not net:
				# nothing on this bill is goods — a pure service invoice
				continue
			if abs(stock_net - full_net) > 0.005 and full_net:
				# mixed bill: carry the goods share of the tax with the goods, so
				# the line still adds up on its own
				share = stock_net / full_net
				tax = flt(tax * share, 2)
				total = flt(net + tax, 2)

		if cint(record.is_return):
			status = DEBIT_NOTE
		elif cint(record.update_stock):
			status = INVOICED_WITH_STOCK
		else:
			status = INVOICED

		rows.append(
			{
				"voucher_type": record.voucher_type,
				"voucher_no": record.voucher_no,
				"posting_date": record.posting_date,
				"company": record.company,
				"status": status,
				"supplier": record.supplier,
				"supplier_name": record.supplier_name,
				"supplier_group": record.supplier_group,
				"bill_no": record.bill_no,
				"bill_date": record.bill_date,
				"pending_qty": 0.0,
				# Item level, not the header. The two disagree on this data because
				# invoices imported from ePromise carry landed cost inside the item
				# rate while the header holds only what the supplier is owed, and
				# the goods value is what a trading account needs.
				"net_amount": flt(net),
				"tax_amount": flt(tax),
				"total_amount": flt(total),
			}
		)
	return rows


def get_invoice_item_totals(names):
	"""Net per invoice off the item rows, split into the stock part and the whole.

	Core totals an invoice from its items rather than its header, and on this
	site the two disagree, so both figures come from the same place. The stock
	share is what lets a mixed invoice contribute only its goods.
	"""
	if not names:
		return {}

	item = frappe.qb.DocType("Purchase Invoice Item")
	master = frappe.qb.DocType("Item")
	records = (
		frappe.qb.from_(item)
		.join(master)
		.on(master.name == item.item_code)
		.select(
			item.parent,
			Sum(item.base_net_amount).as_("net"),
			Sum(
				Case().when(master.is_stock_item == 1, item.base_net_amount).else_(0)
			).as_("stock_net"),
		)
		.where(item.parent.isin(names))
		.groupby(item.parent)
	).run(as_dict=True)

	return {
		record.parent: {"net": flt(record.net), "stock_net": flt(record.stock_net)}
		for record in records
	}


def parents_with_item_field(child_doctype, fieldname, value):
	"""Sub-select of parents having an item row that carries this value.

	Branch, warehouse and item group all live on the item rows here, the same
	place core's Purchase Register looks for them. Expressed as a sub-select
	rather than EXISTS because pypika on this bench has no exists criterion.
	"""
	child = frappe.qb.DocType(child_doctype)
	return frappe.qb.from_(child).select(child.parent).where(child[fieldname] == value)


# ---------------------------------------------------------------------------
# the unbilled side — what the receipts are still carrying
# ---------------------------------------------------------------------------


def get_receipt_rows(filters):
	"""One line per receipt, valued at the part no invoice has billed.

	`as_on` is the period end so the answer is what was outstanding then, and
	the receipt has to have been raised inside the period to belong to it.
	"""
	open_filters = frappe._dict(
		{
			"company": filters.company,
			"as_on": getdate(filters.to_date),
			"party": filters.get("supplier"),
			"cost_center": filters.get("cost_center"),
			# Purchase Receipt status reads Completed the moment an invoice lands,
			# including an invoice raised AFTER this period ended, so judging by it
			# would drop that receipt out of a period it genuinely belonged to.
			# Billed-ness comes from the row links, dated, which is the honest test.
			"ignore_document_status": 1,
			# returns are reported on their own lines below; netting them into
			# the receipt as well would subtract the same goods twice
			"ignore_return_netting": 1,
			"warehouse": filters.get("warehouse"),
			"item_group": filters.get("item_group"),
			"include_non_stock": 0 if stock_items_only(filters) else 1,
		}
	)

	if filters.get("mode_of_payment"):
		# a receipt carries no mode of payment, so nothing here can match it
		return []

	from_date = getdate(filters.from_date)
	to_date = getdate(filters.to_date)

	per_receipt = {}
	for row in received_items_pending_billing(open_filters):
		posting_date = getdate(row.posting_date)
		if posting_date < from_date or posting_date > to_date:
			continue

		receipt = per_receipt.get(row.document)
		if receipt is None:
			receipt = {
				"voucher_type": "Purchase Receipt",
				"voucher_no": row.document,
				"posting_date": posting_date,
				"company": row.company,
				"status": UNBILLED_RECEIPT,
				"supplier": row.party,
				"supplier_name": row.party_name,
				"supplier_group": None,
				"bill_no": None,
				"bill_date": None,
				"pending_qty": 0.0,
				"net_amount": 0.0,
				# a receipt carries no supplier tax; the tax arrives with the bill
				"tax_amount": 0.0,
				"total_amount": 0.0,
			}
			per_receipt[row.document] = receipt

		receipt["pending_qty"] += flt(row.pending_qty)
		receipt["net_amount"] += flt(row.pending_amount)
		receipt["total_amount"] += flt(row.pending_amount)

	rows = list(per_receipt.values())
	set_supplier_groups(rows)

	if filters.get("supplier_group"):
		rows = [row for row in rows if row["supplier_group"] == filters.supplier_group]

	for row in rows:
		row["pending_qty"] = flt(row["pending_qty"], 3)
		row["net_amount"] = flt(row["net_amount"], 2)
		row["total_amount"] = flt(row["total_amount"], 2)

	return rows


def get_return_rows(filters):
	"""Goods sent back, as negative lines, net of any debit note already raised.

	A purchase return reduces purchases. It reaches this report one of two ways:
	the supplier issues a debit note, which is a Purchase Invoice with is_return
	and lands on the invoice side as a negative; or the goods go back on a return
	Purchase Receipt and no debit note exists yet, which is what this handles.

	Only the part NOT yet covered by a debit note is printed, so once the debit
	note arrives the return line shrinks to nothing and the debit note carries
	the reduction instead — the same no-double-counting rule the receipt side
	follows. Receipt lines deliberately do not net returns away (see
	`ignore_return_netting`), because a return against a receipt that is already
	fully billed would otherwise be netted against nothing and disappear, and on
	this data some returns name no receipt at all.
	"""
	if filters.get("mode_of_payment"):
		return []

	receipt = frappe.qb.DocType("Purchase Receipt")
	line = frappe.qb.DocType("Purchase Receipt Item")
	item = frappe.qb.DocType("Item")

	query = (
		frappe.qb.from_(receipt)
		.join(line)
		.on(receipt.name == line.parent)
		.join(item)
		.on(item.name == line.item_code)
		.select(
			receipt.name.as_("voucher_no"),
			receipt.posting_date,
			receipt.company,
			receipt.supplier,
			receipt.supplier_name,
			line.name.as_("row_name"),
			line.qty,
			line.base_net_amount,
		)
		.where(
			(receipt.docstatus == 1)
			& (receipt.is_return == 1)
			& (receipt.company == filters.company)
			& (receipt.posting_date >= getdate(filters.from_date))
			& (receipt.posting_date <= getdate(filters.to_date))
			& (line.qty < 0)
		)
	)

	if stock_items_only(filters):
		query = query.where(item.is_stock_item == 1)

	if filters.get("supplier"):
		query = query.where(receipt.supplier == filters.supplier)
	for fieldname in ("cost_center", "warehouse", "item_group"):
		if filters.get(fieldname):
			query = query.where(line[fieldname] == filters.get(fieldname))

	records = query.run(as_dict=True)
	if not records:
		return []

	credited = debit_noted_qty([record.row_name for record in records], getdate(filters.to_date))

	per_return = {}
	for record in records:
		returned = abs(flt(record.qty))
		covered = abs(flt(credited.get(record.row_name, 0)))
		outstanding = flt(returned - covered, 3)
		if outstanding <= 0:
			continue

		row = per_return.get(record.voucher_no)
		if row is None:
			row = {
				"voucher_type": "Purchase Receipt",
				"voucher_no": record.voucher_no,
				"posting_date": getdate(record.posting_date),
				"company": record.company,
				"status": UNBILLED_RETURN,
				"supplier": record.supplier,
				"supplier_name": record.supplier_name,
				"supplier_group": None,
				"bill_no": None,
				"bill_date": None,
				"pending_qty": 0.0,
				"net_amount": 0.0,
				"tax_amount": 0.0,
				"total_amount": 0.0,
			}
			per_return[record.voucher_no] = row

		# base_net_amount is already negative on a return row; take the share of
		# it that no debit note has picked up
		share = flt(record.base_net_amount) * outstanding / returned if returned else 0.0
		row["pending_qty"] -= outstanding
		row["net_amount"] += share
		row["total_amount"] += share

	rows = list(per_return.values())
	set_supplier_groups(rows)

	if filters.get("supplier_group"):
		rows = [row for row in rows if row["supplier_group"] == filters.supplier_group]

	for row in rows:
		row["pending_qty"] = flt(row["pending_qty"], 3)
		row["net_amount"] = flt(row["net_amount"], 2)
		row["total_amount"] = flt(row["total_amount"], 2)

	return rows


def debit_noted_qty(row_names, as_on):
	"""Quantity of each return row a submitted debit note has already covered."""
	if not row_names:
		return {}

	line = frappe.qb.DocType("Purchase Invoice Item")
	invoice = frappe.qb.DocType("Purchase Invoice")
	records = (
		frappe.qb.from_(line)
		.join(invoice)
		.on(invoice.name == line.parent)
		.select(line.pr_detail.as_("link"), Sum(line.qty).as_("qty"))
		.where(
			(invoice.docstatus == 1)
			& (invoice.posting_date <= as_on)
			& (line.pr_detail.isin(row_names))
		)
		.groupby(line.pr_detail)
	).run(as_dict=True)

	return {record.link: flt(record.qty) for record in records}


def set_supplier_groups(rows):
	"""Purchase Receipt has no supplier_group of its own — read it off the party."""
	suppliers = {row["supplier"] for row in rows if row["supplier"]}
	if not suppliers:
		return

	groups = {
		record.name: record.supplier_group
		for record in frappe.get_all(
			"Supplier", filters={"name": ("in", list(suppliers))}, fields=["name", "supplier_group"]
		)
	}
	for row in rows:
		row["supplier_group"] = groups.get(row["supplier"])


# ---------------------------------------------------------------------------
# landed cost
# ---------------------------------------------------------------------------


def attach_landed_cost(rows, filters):
	"""Landed cost against each line, following the charge to whoever carries the goods.

	A Landed Cost Voucher is raised against a Purchase Receipt, but the receipt
	drops off this report the moment it is billed — so matching the charge to
	the document it names would show it only while the goods were unbilled, and
	never afterwards. The charge belongs with the goods, so it follows them onto
	the invoice that billed them.

	Split proportionally, which is what stops a partly billed receipt paying
	twice: the invoice takes the share it billed, the receipt line keeps the
	share still unbilled, and the two add up to the voucher. A claimant outside
	the report period simply takes its share away with it, so each period shows
	the part of the charge that sits on its own rows.
	"""
	for row in rows:
		row["landed_cost_voucher"] = ""
		row["landed_cost_amount"] = 0.0
		row["total_with_landed_cost"] = flt(row["total_amount"])

	if not rows:
		return

	charge = frappe.qb.DocType("Landed Cost Item")
	voucher = frappe.qb.DocType("Landed Cost Voucher")
	records = (
		frappe.qb.from_(charge)
		.join(voucher)
		.on(voucher.name == charge.parent)
		.select(
			charge.parent.as_("voucher"),
			charge.receipt_document_type.as_("voucher_type"),
			charge.receipt_document.as_("voucher_no"),
			charge.applicable_charges,
		)
		.where(voucher.docstatus == 1)
	).run(as_dict=True)
	if not records:
		return

	applied = {}
	for record in records:
		key = (record.voucher_type, record.voucher_no)
		entry = applied.setdefault(key, {"vouchers": [], "charges": 0.0})
		entry["charges"] += flt(record.applicable_charges)
		if record.voucher not in entry["vouchers"]:
			entry["vouchers"].append(record.voucher)

	index = {(row["voucher_type"], row["voucher_no"]): row for row in rows}
	as_on = getdate(filters.to_date)

	for (target_type, target_no), entry in applied.items():
		if target_type == "Purchase Receipt":
			shares = receipt_claim_shares(target_no, as_on)
		else:
			# raised straight against an invoice that updates stock
			shares = {(target_type, target_no): 1.0}

		for key, share in shares.items():
			row = index.get(key)
			if not row or share <= 0:
				continue
			amount = flt(entry["charges"] * share, 2)
			if not amount:
				continue
			row["landed_cost_amount"] = flt(row["landed_cost_amount"] + amount, 2)
			names = [n for n in entry["vouchers"] if n not in (row["landed_cost_voucher"] or "")]
			row["landed_cost_voucher"] = ", ".join(
				sorted(filter(None, [row["landed_cost_voucher"]] + names))
			)

	for row in rows:
		row["total_with_landed_cost"] = flt(row["total_amount"] + row["landed_cost_amount"], 2)


def receipt_claim_shares(receipt, as_on):
	"""How a receipt's landed cost divides between its invoices and its remainder.

	Shares are by value, the same basis a Landed Cost Voucher distributes on,
	and they sum to one across every claimant.
	"""
	lines = frappe.get_all(
		"Purchase Receipt Item",
		filters={"parent": receipt},
		fields=["name", "qty", "base_net_amount"],
	)
	total = sum(flt(line.base_net_amount) for line in lines)
	if not total:
		return {}

	billed_value = {}
	for line in lines:
		if not flt(line.qty):
			continue
		invoice = frappe.qb.DocType("Purchase Invoice")
		item = frappe.qb.DocType("Purchase Invoice Item")
		for record in (
			frappe.qb.from_(item)
			.join(invoice)
			.on(invoice.name == item.parent)
			.select(item.parent.as_("invoice"), item.qty)
			.where(
				(invoice.docstatus == 1)
				& (invoice.posting_date <= as_on)
				& (item.pr_detail == line.name)
			)
		).run(as_dict=True):
			portion = flt(line.base_net_amount) * flt(record.qty) / flt(line.qty)
			billed_value[record.invoice] = billed_value.get(record.invoice, 0.0) + portion

	shares = {
		("Purchase Invoice", invoice): value / total
		for invoice, value in billed_value.items()
		if value
	}

	unbilled = total - sum(billed_value.values())
	if unbilled > 0.005:
		shares[("Purchase Receipt", receipt)] = unbilled / total

	return shares


# ---------------------------------------------------------------------------
# columns
# ---------------------------------------------------------------------------


def currency_column(label, fieldname, width=130):
	return {
		"label": label,
		"fieldname": fieldname,
		"fieldtype": "Currency",
		"options": "Company:company:default_currency",
		"width": width,
	}


def get_columns():
	return [
		{"label": _("Type"), "fieldname": "voucher_type", "fieldtype": "Data", "width": 130},
		{
			"label": _("Document"),
			"fieldname": "voucher_no",
			"fieldtype": "Dynamic Link",
			"options": "voucher_type",
			"width": 175,
		},
		{"label": _("Date"), "fieldname": "posting_date", "fieldtype": "Date", "width": 95},
		{"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 150},
		{
			"label": _("Supplier"),
			"fieldname": "supplier",
			"fieldtype": "Link",
			"options": "Supplier",
			"width": 150,
		},
		{"label": _("Supplier Name"), "fieldname": "supplier_name", "fieldtype": "Data", "width": 170},
		{
			"label": _("Supplier Group"),
			"fieldname": "supplier_group",
			"fieldtype": "Link",
			"options": "Supplier Group",
			"width": 120,
		},
		{"label": _("Bill No"), "fieldname": "bill_no", "fieldtype": "Data", "width": 110},
		{"label": _("Bill Date"), "fieldname": "bill_date", "fieldtype": "Date", "width": 95},
		{"label": _("Unbilled Qty"), "fieldname": "pending_qty", "fieldtype": "Float", "width": 100},
		currency_column(_("Net Amount"), "net_amount"),
		currency_column(_("Tax Amount"), "tax_amount", 110),
		currency_column(_("Total"), "total_amount"),
		{
			# Data, not Link, on purpose — the report .js turns it into a clickable
			# anchor. A Link column would refuse to render for any reader without read
			# permission on Landed Cost Voucher, which on this site is everyone except
			# Stock Manager, and would take the whole report down with it.
			"label": _("Landed Cost Voucher"),
			"fieldname": "landed_cost_voucher",
			"fieldtype": "Data",
			"width": 170,
		},
		currency_column(_("Landed Cost"), "landed_cost_amount", 120),
		currency_column(_("Total with Landed Cost"), "total_with_landed_cost", 160),
		{
			"label": _("Company"),
			"fieldname": "company",
			"fieldtype": "Link",
			"options": "Company",
			"width": 130,
			"hidden": 1,
		},
	]
