"""Open item engine — the four unbilled/undelivered flows.

A sales or purchase document row stays "open" until its counterpart document
row closes it. The links that pair rows up are core's own mapper fields:

    Sales Invoice Item.dn_detail        -> Delivery Note Item.name   (bill after delivery)
    Delivery Note Item.si_detail        -> Sales Invoice Item.name   (deliver after billing)
    Purchase Invoice Item.pr_detail     -> Purchase Receipt Item.name (bill after receipt)
    Purchase Receipt Item.purchase_invoice_item -> Purchase Invoice Item.name (receive after billing)

Every report here reconstructs the matched quantity from those links as of a
date, instead of reading the live denormalised fields (`billed_amt`,
`delivered_qty`, `per_received`). The live fields only know today's state, so
"open as of 30 June" comes out wrong through them — the linked rows carry
their own posting dates and do not have that problem. It also means a row
whose counterpart was cancelled re-opens by itself.

Returns net the same way: a return document's rows point at the original row
(`sales_invoice_item` / `dn_detail` / `purchase_receipt_item` /
`purchase_invoice_item`) with negative quantities.

Used by the four Script Reports in vansale/sf_trading/report/:
    Invoiced Items To Be Delivered
    Delivered Items Pending Billing
    Received Items Pending Billing
    Billed Items Pending Receipt
"""

import frappe
from frappe import _
from frappe.query_builder.functions import Sum
from frappe.utils import cint, date_diff, flt, getdate, nowdate

QTY_PRECISION = 3


# ---------------------------------------------------------------------------
# shared plumbing
# ---------------------------------------------------------------------------


def as_on_date(filters):
	return getdate(filters.get("as_on") or nowdate())


def posting_range(filters):
	"""Optional posting-date window for the source documents, as (from, to).

	`as_on` answers "was this still open on that date". This answers a different
	question — *which* documents to ask about — so a single period can be checked
	on its own: the July receipts that are still unbilled, rather than every
	receipt ever raised. Both ends are inclusive, and both are optional; leaving
	them empty reports every document, which is what the workspace number cards
	do, so their totals are unaffected by this filter existing.

	Only the source document is bounded. The matched quantities keep counting
	every counterpart up to `as_on` no matter when the counterpart itself was
	raised — a July receipt invoiced in August is billed, not open, and clipping
	the invoice side to July as well would resurrect it as a false positive.

	`as_on` still caps the window: a To Date after it cannot widen the answer,
	because billing state is only known as far as `as_on`.
	"""
	from_date = filters.get("from_date")
	to_date = filters.get("to_date")
	from_date = getdate(from_date) if from_date else None
	to_date = getdate(to_date) if to_date else None

	if from_date and to_date and from_date > to_date:
		frappe.throw(_("From Date cannot be after To Date."))

	return from_date, to_date


def ageing_ranges(filters):
	"""Parse "30, 60, 90" into [30, 60, 90]; fall back to the default split."""
	raw = str(filters.get("range") or "30, 60, 90")
	ranges = [cint(part) for part in raw.split(",") if cint(part) > 0]
	return sorted(set(ranges)) or [30, 60, 90]


def ageing_bucket(age, ranges):
	lower = 0
	for upper in ranges:
		if age <= upper:
			return f"{lower}-{upper}"
		lower = upper + 1
	return f"{ranges[-1] + 1}-{_('Above')}"


def bucket_index(age, ranges):
	"""0-based bucket position for an age; len(ranges) = the Above bucket."""
	for position, upper in enumerate(ranges):
		if age <= upper:
			return position
	return len(ranges)


def bucket_labels(ranges):
	labels = []
	lower = 0
	for upper in ranges:
		labels.append(f"{lower}-{upper}")
		lower = upper + 1
	labels.append(f"{ranges[-1] + 1}-{_('Above')}")
	return labels


def matched_qty_map(child_doctype, parent_doctype, link_field, as_on, is_return=None):
	"""Sum of row qty per counterpart row name, submitted and posted by as_on.

	Return documents carry negative quantities, so summing every submitted row
	that points at the link nets returns out without a second pass.
	"""
	child = frappe.qb.DocType(child_doctype)
	parent = frappe.qb.DocType(parent_doctype)

	query = (
		frappe.qb.from_(child)
		.join(parent)
		.on(parent.name == child.parent)
		.select(child[link_field].as_("link"), Sum(child.qty).as_("qty"))
		.where(
			(parent.docstatus == 1)
			& (parent.posting_date <= as_on)
			& (child[link_field].isnotnull())
			& (child[link_field] != "")
		)
		.groupby(child[link_field])
	)

	if is_return is not None:
		query = query.where(parent.is_return == cint(is_return))

	return {row.link: flt(row.qty) for row in query.run(as_dict=True)}


# Which User Permission narrows which column. Branch lives on the parent; cost
# center and warehouse are read off the row, which is what these reports display.
PERMISSION_COLUMNS = (
	("Branch", "branch", "parent"),
	("Cost Center", "cost_center", "child"),
	("Warehouse", "warehouse", "child"),
)


def apply_user_permissions(query, parent, child, parent_doctype):
	"""Narrow a query to the branches and warehouses the session user may see.

	`frappe.qb` applies no permission filtering whatsoever — unlike
	`frappe.get_list` — so without this a user restricted by User Permission to one
	branch still sees every branch in these reports. The desk list views on the same
	data are restricted, so the reports have to match or they leak.

	A blank value passes, the way frappe treats an empty link field under a User
	Permission, so a row naming no cost center is not silently dropped.

	A user with no User Permissions at all — Administrator, and most head-office
	logins — is unaffected: `get_user_permissions` returns nothing and the query is
	handed back untouched.
	"""
	from frappe.permissions import get_user_permissions

	permissions = get_user_permissions(frappe.session.user)
	if not permissions:
		return query

	metas = {
		"parent": frappe.get_meta(parent_doctype),
		"child": frappe.get_meta(parent_doctype + " Item"),
	}
	tables = {"parent": parent, "child": child}

	for doctype, fieldname, level in PERMISSION_COLUMNS:
		allowed = [row.get("doc") for row in (permissions.get(doctype) or []) if row.get("doc")]
		if not allowed:
			continue
		if not metas[level].get_field(fieldname):
			continue
		column = tables[level][fieldname]
		query = query.where(column.isnull() | (column == "") | column.isin(allowed))

	return query


def base_rows(parent_doctype, party_field, filters, extra_conditions=None):
	"""Submitted stock-item rows of the source document, with row-level filters.

	Positive-qty rows only: return documents enter the calculation through the
	matched-qty maps, never as open items of their own.
	"""
	parent = frappe.qb.DocType(parent_doctype)
	child = frappe.qb.DocType(parent_doctype + " Item")
	item = frappe.qb.DocType("Item")
	as_on = as_on_date(filters)

	query = (
		frappe.qb.from_(parent)
		.join(child)
		.on(parent.name == child.parent)
		.join(item)
		.on(item.name == child.item_code)
		.select(
			parent.name.as_("document"),
			parent.posting_date,
			parent[party_field].as_("party"),
			parent[party_field + "_name"].as_("party_name"),
			parent.company,
			child.name.as_("row_name"),
			child.item_code,
			child.item_name,
			child.item_group,
			child.warehouse,
			child.cost_center,
			child.uom,
			child.qty,
			child.base_net_rate,
			child.base_net_amount,
		)
		.where(
			(parent.docstatus == 1)
			& (parent.is_return == 0)
			& (parent.company == filters.get("company"))
			& (parent.posting_date <= as_on)
			& (child.qty > 0)
		)
		.orderby(parent.posting_date)
		.orderby(parent.name)
	)

	query = apply_user_permissions(query, parent, child, parent_doctype)

	from_date, to_date = posting_range(filters)
	if from_date:
		query = query.where(parent.posting_date >= from_date)
	if to_date:
		query = query.where(parent.posting_date <= to_date)

	if not includes_non_stock(filters):
		query = query.where(item.is_stock_item == 1)

	if extra_conditions:
		for condition in extra_conditions(parent, child):
			query = query.where(condition)

	if filters.get("party"):
		query = query.where(parent[party_field] == filters.get("party"))
	if filters.get("item_code"):
		query = query.where(child.item_code == filters.get("item_code"))
	if filters.get("item_group"):
		query = query.where(child.item_group == filters.get("item_group"))
	if filters.get("warehouse"):
		query = query.where(child.warehouse == filters.get("warehouse"))
	if filters.get("cost_center"):
		query = query.where(child.cost_center == filters.get("cost_center"))

	return query.run(as_dict=True)


def build_open_rows(rows, matched_maps, matched_fieldnames, filters):
	"""Net each source row against its matched maps; keep what stays open.

	matched_maps and matched_fieldnames run in step: the first map's total is
	reported under the first fieldname, and so on. Pending is qty minus every
	matched quantity (matched maps built from return documents already carry
	negative sums, so their absolute value is what got returned).
	"""
	as_on = as_on_date(filters)
	ranges = ageing_ranges(filters)
	open_rows = []

	for row in rows:
		pending = flt(row.qty, QTY_PRECISION)
		for matched_map, fieldname in zip(matched_maps, matched_fieldnames):
			matched = flt(matched_map.get(row.row_name, 0), QTY_PRECISION)
			row[fieldname] = abs(matched)
			pending -= abs(matched)

		pending = flt(pending, QTY_PRECISION)
		if pending <= 0:
			continue

		row.pending_qty = pending
		row.pending_amount = flt(
			flt(row.base_net_amount) * pending / flt(row.qty), 2
		) if flt(row.qty) else 0
		row.age = max(date_diff(as_on, row.posting_date), 0)
		row.bucket = ageing_bucket(row.age, ranges)
		open_rows.append(row)

	return open_rows


# ---------------------------------------------------------------------------
# the four flows
# ---------------------------------------------------------------------------


def invoiced_items_to_be_delivered(filters):
	"""Sales Invoice rows (no Update Stock) still waiting for a Delivery Note."""
	as_on = as_on_date(filters)

	rows = base_rows(
		"Sales Invoice",
		"customer",
		filters,
		extra_conditions=lambda parent, child: [
			parent.update_stock == 0,
			parent.is_opening != "Yes",
			(child.dn_detail.isnull()) | (child.dn_detail == ""),
			(child.delivery_note.isnull()) | (child.delivery_note == ""),
		],
	)

	delivered = matched_qty_map("Delivery Note Item", "Delivery Note", "si_detail", as_on)
	credited = matched_qty_map(
		"Sales Invoice Item", "Sales Invoice", "sales_invoice_item", as_on, is_return=1
	)

	return build_open_rows(rows, [delivered, credited], ["delivered_qty", "returned_qty"], filters)


def invoices_pending_delivery(filters):
	"""One row per Sales Invoice that still owes a delivery.

	Aggregated from `invoiced_items_to_be_delivered`, deliberately, so it nets
	returns the same way rather than re-deriving it: an invoice whose goods were
	fully credited disappears, and a partly credited one keeps only the quantity
	still genuinely owed. A list view cannot do this — the return links live on the
	credit note (`return_against`), pointing back at the invoice, so nothing on the
	invoice itself says a credit note exists, and `Sales Invoice.status` only reads
	"Credit Note Issued" when the credit note is what took the outstanding to zero.
	An invoice already paid before being credited still reads "Paid".
	"""
	rows = invoiced_items_to_be_delivered(filters)
	if not rows:
		return []

	per_invoice = {}
	for row in rows:
		entry = per_invoice.get(row.document)
		if entry is None:
			entry = per_invoice[row.document] = frappe._dict(
				{
					"document": row.document,
					"posting_date": row.posting_date,
					"party": row.party,
					"party_name": row.party_name,
					"company": row.company,
					"cost_center": row.cost_center,
					"items_pending": 0,
					"pending_qty": 0.0,
					"delivered_qty": 0.0,
					"returned_qty": 0.0,
					"pending_amount": 0.0,
					"age": row.age,
					"bucket": row.bucket,
				}
			)
		entry.items_pending += 1
		entry.pending_qty += flt(row.pending_qty)
		entry.delivered_qty += flt(row.delivered_qty)
		entry.returned_qty += flt(row.returned_qty)
		entry.pending_amount += flt(row.pending_amount)

	# one read for every invoice on the page rather than one per row
	heads = {
		head.name: head
		for head in frappe.get_all(
			"Sales Invoice",
			filters={"name": ["in", list(per_invoice)]},
			fields=["name", "status", "base_grand_total"],
		)
	}

	for name, entry in per_invoice.items():
		head = heads.get(name) or frappe._dict()
		entry.status = head.get("status")
		entry.invoice_total = flt(head.get("base_grand_total"))
		entry.pending_qty = flt(entry.pending_qty, QTY_PRECISION)
		entry.delivered_qty = flt(entry.delivered_qty, QTY_PRECISION)
		entry.returned_qty = flt(entry.returned_qty, QTY_PRECISION)
		entry.pending_amount = flt(entry.pending_amount, 2)

	return sorted(per_invoice.values(), key=lambda row: (getdate(row.posting_date), row.document))


def pending_delivery_columns():
	"""Columns for the invoice-wise pending delivery report."""
	return [
		{
			"label": _("Sales Invoice"),
			"fieldname": "document",
			"fieldtype": "Link",
			"options": "Sales Invoice",
			"width": 170,
		},
		{"label": _("Date"), "fieldname": "posting_date", "fieldtype": "Date", "width": 95},
		{
			"label": _("Customer"),
			"fieldname": "party",
			"fieldtype": "Link",
			"options": "Customer",
			"width": 140,
		},
		{"label": _("Customer Name"), "fieldname": "party_name", "fieldtype": "Data", "width": 200},
		{"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 120},
		{
			# a Link, because that is what lets a User Permission on Cost Center
			# narrow this report to a branch
			"label": _("Branch (Cost Center)"),
			"fieldname": "cost_center",
			"fieldtype": "Link",
			"options": "Cost Center",
			"width": 130,
		},
		{"label": _("Items Pending"), "fieldname": "items_pending", "fieldtype": "Int", "width": 105},
		{"label": _("Pending Qty"), "fieldname": "pending_qty", "fieldtype": "Float", "width": 105},
		{"label": _("Delivered Qty"), "fieldname": "delivered_qty", "fieldtype": "Float", "width": 110},
		{"label": _("Returned Qty"), "fieldname": "returned_qty", "fieldtype": "Float", "width": 110},
		{
			"label": _("Pending Amount"),
			"fieldname": "pending_amount",
			"fieldtype": "Currency",
			"options": "Company:company:default_currency",
			"width": 130,
		},
		{
			"label": _("Invoice Total"),
			"fieldname": "invoice_total",
			"fieldtype": "Currency",
			"options": "Company:company:default_currency",
			"width": 120,
		},
		{"label": _("Age (Days)"), "fieldname": "age", "fieldtype": "Int", "width": 85},
		{"label": _("Ageing Bucket"), "fieldname": "bucket", "fieldtype": "Data", "width": 95},
	]


def includes_non_stock(filters) -> bool:
	"""Whether rows for items that are not stock items belong in the answer.

	The open item reports are about goods movement, so they ask only about
	stock items. A purchases register has to be able to widen that, because the
	invoice side of it counts service bills and dropping their receipts would
	leave the two halves disagreeing with each other.
	"""
	return bool(cint(filters.get("include_non_stock")))


def ignores_document_status(filters) -> bool:
	"""Whether the caller wants the parent status left out of the reckoning.

	Status is a snapshot of TODAY — a receipt invoiced this month reads
	Completed now even though it was outstanding at the end of last month — so
	a caller asking an as-of-a-past-date question must be able to switch it
	off, or the answer silently changes as documents get billed. Billed-ness is
	established from the row links either way, which is the accurate test; the
	status filter only ever added operational tidiness on top.
	"""
	return bool(cint(filters.get("ignore_document_status")))


def ignores_return_netting(filters) -> bool:
	"""Whether the caller reports returns as their own lines rather than as a
	deduction from the receipt they came off.

	Netting a return into its receipt is right for a to-do list: what is left to
	bill is what came in less what went back. A register that also prints the
	return as a line of its own would then subtract it twice, and a return whose
	receipt is already fully billed — or that names no receipt at all, which
	happens on this data — would be netted against nothing and vanish. Such a
	caller asks for the raw received quantity here and handles returns itself.
	"""
	return bool(cint(filters.get("ignore_return_netting")))


def delivered_items_pending_billing(filters):
	"""Delivery Note rows still waiting for a Sales Invoice."""
	as_on = as_on_date(filters)

	def conditions(parent, child):
		clauses = [
			(child.si_detail.isnull()) | (child.si_detail == ""),
			(child.against_sales_invoice.isnull()) | (child.against_sales_invoice == ""),
		]
		if not ignores_document_status(filters):
			clauses.append(parent.status.notin(["Closed"]))
		return clauses

	rows = base_rows("Delivery Note", "customer", filters, extra_conditions=conditions)

	billed = matched_qty_map("Sales Invoice Item", "Sales Invoice", "dn_detail", as_on)
	returned = matched_qty_map("Delivery Note Item", "Delivery Note", "dn_detail", as_on, is_return=1)

	return build_open_rows(rows, [billed, returned], ["billed_qty", "returned_qty"], filters)


def received_items_pending_billing(filters):
	"""Purchase Receipt rows still waiting for a Purchase Invoice."""
	as_on = as_on_date(filters)

	def conditions(parent, child):
		clauses = [
			(child.purchase_invoice_item.isnull()) | (child.purchase_invoice_item == ""),
			(child.purchase_invoice.isnull()) | (child.purchase_invoice == ""),
		]
		if not ignores_document_status(filters):
			clauses.append(parent.status.notin(["Closed", "Completed"]))
		return clauses

	rows = base_rows("Purchase Receipt", "supplier", filters, extra_conditions=conditions)

	billed = matched_qty_map("Purchase Invoice Item", "Purchase Invoice", "pr_detail", as_on)

	if ignores_return_netting(filters):
		# the caller accounts for returns on their own lines instead — see
		# ignores_return_netting for why netting them in here would double count
		return build_open_rows(rows, [billed], ["billed_qty"], filters)

	returned = matched_qty_map(
		"Purchase Receipt Item", "Purchase Receipt", "purchase_receipt_item", as_on, is_return=1
	)

	return build_open_rows(rows, [billed, returned], ["billed_qty", "returned_qty"], filters)


def billed_items_pending_receipt(filters):
	"""Purchase Invoice rows (no Update Stock) still waiting for a Purchase Receipt."""
	as_on = as_on_date(filters)

	rows = base_rows(
		"Purchase Invoice",
		"supplier",
		filters,
		extra_conditions=lambda parent, child: [
			parent.update_stock == 0,
			parent.is_opening != "Yes",
			(child.pr_detail.isnull()) | (child.pr_detail == ""),
			(child.purchase_receipt.isnull()) | (child.purchase_receipt == ""),
		],
	)

	received = matched_qty_map(
		"Purchase Receipt Item", "Purchase Receipt", "purchase_invoice_item", as_on
	)
	debited = matched_qty_map(
		"Purchase Invoice Item", "Purchase Invoice", "purchase_invoice_item", as_on, is_return=1
	)

	return build_open_rows(rows, [received, debited], ["received_qty", "returned_qty"], filters)


# ---------------------------------------------------------------------------
# columns shared by the four reports
# ---------------------------------------------------------------------------


def report_columns(document_doctype, party_doctype, matched_fieldname, matched_label):
	return [
		{
			"label": _(party_doctype),
			"fieldname": "party",
			"fieldtype": "Link",
			"options": party_doctype,
			"width": 140,
		},
		{
			"label": _(party_doctype + " Name"),
			"fieldname": "party_name",
			"fieldtype": "Data",
			"width": 160,
		},
		{
			"label": _(document_doctype),
			"fieldname": "document",
			"fieldtype": "Link",
			"options": document_doctype,
			"width": 170,
		},
		{"label": _("Date"), "fieldname": "posting_date", "fieldtype": "Date", "width": 95},
		{"label": _("Age (Days)"), "fieldname": "age", "fieldtype": "Int", "width": 85},
		{"label": _("Ageing Bucket"), "fieldname": "bucket", "fieldtype": "Data", "width": 95},
		{
			"label": _("Item Code"),
			"fieldname": "item_code",
			"fieldtype": "Link",
			"options": "Item",
			"width": 130,
		},
		{"label": _("Item Name"), "fieldname": "item_name", "fieldtype": "Data", "width": 160},
		{
			"label": _("Item Group"),
			"fieldname": "item_group",
			"fieldtype": "Link",
			"options": "Item Group",
			"width": 110,
		},
		{
			"label": _("Warehouse"),
			"fieldname": "warehouse",
			"fieldtype": "Link",
			"options": "Warehouse",
			"width": 120,
		},
		{
			"label": _("Branch"),
			"fieldname": "cost_center",
			"fieldtype": "Link",
			"options": "Cost Center",
			"width": 110,
		},
		# Data, not a Link to UOM: a query report refuses to render a Link column
		# whose doctype the reader cannot read, and plenty of accounts users have
		# no UOM permission — the whole report died with "No permission to read
		# UOM" for them. The other Link columns stay: Cost Center and Warehouse
		# links are what let User Permissions narrow the rows to a user branch,
		# and the party and document links are how people navigate out of here.
		{"label": _("UOM"), "fieldname": "uom", "fieldtype": "Data", "width": 70},
		{"label": _("Qty"), "fieldname": "qty", "fieldtype": "Float", "width": 90},
		{
			"label": matched_label,
			"fieldname": matched_fieldname,
			"fieldtype": "Float",
			"width": 100,
		},
		{"label": _("Returned Qty"), "fieldname": "returned_qty", "fieldtype": "Float", "width": 100},
		{"label": _("Pending Qty"), "fieldname": "pending_qty", "fieldtype": "Float", "width": 100},
		{
			"label": _("Rate"),
			"fieldname": "base_net_rate",
			"fieldtype": "Currency",
			"options": "Company:company:default_currency",
			"width": 100,
		},
		{
			"label": _("Pending Amount"),
			"fieldname": "pending_amount",
			"fieldtype": "Currency",
			"options": "Company:company:default_currency",
			"width": 120,
		},
	]


# ---------------------------------------------------------------------------
# party-wise summaries — one row per customer / supplier
# ---------------------------------------------------------------------------


def party_open_summary(flow_specs, party_doctype, filters):
	"""Aggregate detail flows into one row per party.

	flow_specs: ordered [(flow_function, value_fieldname)]. Every number here
	is a sum over the SAME rows the detail reports print, so summary and
	detail always reconcile — there is no second query path to drift.
	"""
	ranges = ageing_ranges(filters)
	parties = {}
	documents = {}

	for flow, fieldname in flow_specs:
		for row in flow(filters):
			party = parties.get(row.party)
			if party is None:
				party = frappe._dict(
					party=row.party,
					party_name=row.party_name,
					company=row.company,
					open_docs=0,
					open_items=0,
					oldest=0,
					total_value=0.0,
				)
				for _flow, value_field in flow_specs:
					party[value_field] = 0.0
				for position in range(len(ranges) + 1):
					party[f"range{position + 1}"] = 0.0
				parties[row.party] = party
				documents[row.party] = set()

			pending = flt(row.pending_amount)
			party[fieldname] += pending
			party.total_value += pending
			party[f"range{bucket_index(row.age, ranges) + 1}"] += pending
			party.open_items += 1
			party.oldest = max(party.oldest, row.age)
			documents[row.party].add(row.document)

	if filters.get("party_group"):
		group_field = frappe.scrub(party_doctype) + "_group"
		in_group = set(
			frappe.get_all(
				party_doctype,
				filters={
					"name": ["in", list(parties)],
					group_field: filters.get("party_group"),
				},
				pluck="name",
			)
		)
		parties = {name: row for name, row in parties.items() if name in in_group}

	rows = []
	for name, party in parties.items():
		party.open_docs = len(documents[name])
		for key, value in list(party.items()):
			if isinstance(value, float):
				party[key] = flt(value, 2)
		rows.append(party)

	return sorted(rows, key=lambda row: row.total_value, reverse=True)


def summary_columns(party_doctype, flow_columns, filters):
	"""flow_columns: ordered [(value_fieldname, label, drill_report_name)]."""
	columns = [
		{
			"label": _(party_doctype),
			"fieldname": "party",
			"fieldtype": "Link",
			"options": party_doctype,
			"width": 150,
		},
		{
			"label": _(party_doctype + " Name"),
			"fieldname": "party_name",
			"fieldtype": "Data",
			"width": 180,
		},
	]
	for fieldname, label, drill_report in flow_columns:
		columns.append(
			{
				"label": label,
				"fieldname": fieldname,
				"fieldtype": "Currency",
				"options": "Company:company:default_currency",
				"width": 140,
				"drill_report": drill_report,
			}
		)
	columns += [
		{
			"label": _("Total Open Value"),
			"fieldname": "total_value",
			"fieldtype": "Currency",
			"options": "Company:company:default_currency",
			"width": 140,
		},
		{"label": _("Open Docs"), "fieldname": "open_docs", "fieldtype": "Int", "width": 90},
		{"label": _("Open Items"), "fieldname": "open_items", "fieldtype": "Int", "width": 90},
		{"label": _("Oldest (Days)"), "fieldname": "oldest", "fieldtype": "Int", "width": 100},
	]
	for position, label in enumerate(bucket_labels(ageing_ranges(filters))):
		columns.append(
			{
				"label": label,
				"fieldname": f"range{position + 1}",
				"fieldtype": "Currency",
				"options": "Company:company:default_currency",
				"width": 110,
			}
		)
	return columns


def customer_open_items_summary(filters):
	return party_open_summary(
		[
			(invoiced_items_to_be_delivered, "to_deliver_value"),
			(delivered_items_pending_billing, "unbilled_delivery_value"),
		],
		"Customer",
		filters,
	)


def supplier_open_items_summary(filters):
	return party_open_summary(
		[
			(received_items_pending_billing, "unbilled_receipt_value"),
			(billed_items_pending_receipt, "pending_receipt_value"),
		],
		"Supplier",
		filters,
	)
