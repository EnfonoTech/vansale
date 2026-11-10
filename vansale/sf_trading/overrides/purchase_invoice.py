import frappe
from frappe.utils import cint, flt


def set_advance_allocation(doc, method=None):
	"""Allocate the order's advance on an invoice raised against a Purchase Order.

	Turns on ERPNext's own two switches rather than allocating anything by hand:
	`allocate_advances_automatically` makes `validate` call `set_advances()`, and
	`only_include_allocated_payments` keeps that to advances actually allocated against
	the orders on this invoice.

	Both are needed, and the second is the important one. Without it
	`get_advance_payment_entries` also returns every Payment Entry for the supplier with
	`unallocated_amount > 0` and sweeps that on-account money into the invoice FIFO --
	61,792 BHD of it on this site.

	Both fields also carry a DocField default of 1, shipped as a Property Setter. That is
	what lets the advance table fill the moment the invoice is created from an order:
	`get_mapped_purchase_invoice` calls `set_advances()` in its postprocess, but only
	`if target.get("allocate_advances_automatically")`, and a hook running at
	before_validate is far too late for that -- it fires on save. So the default does the
	creation-time work and this hook decides whether the switches were right.

	Which matters, because on an invoice that names no order they are wrong. Note
	`get_advance_journal_entries` applies its reference filter as
	`if reference_or_condition:`: when nothing is unallocated *and* there is no order to
	match, the list is empty and NO filter is applied at all -- the query then returns
	every submitted advance Journal Entry for that supplier. Turning the switches back
	off means that path is never reached.

	The one exception is an invoice that already carries advance rows. Nothing populates
	them on load -- ERPNext's `fetch_advances` fires on a change event, not on render --
	so rows being present means somebody asked for them, and their choice stands.

	Only on a new invoice, so anyone who unticks either box and saves again keeps that too.
	"""
	if not doc.is_new():
		return

	if not any(item.get("purchase_order") for item in doc.get("items") or []):
		if not doc.get("advances"):
			doc.allocate_advances_automatically = 0
			doc.only_include_allocated_payments = 0
		return

	# a paid invoice settles itself; ERPNext skips set_advances when is_paid is set and
	# the form clears the flag anyway, so do not claim to have set something up
	if cint(doc.get("is_paid")):
		doc.allocate_advances_automatically = 0
		return

	doc.allocate_advances_automatically = 1
	doc.only_include_allocated_payments = 1


def validate(doc, method=None):
	"""Block overbilling at draft/save stage by checking all non-cancelled PIs."""
	_check_overbilling(doc)


def on_save(doc, method=None):
	"""Update Purchase Receipt billing approval status after every save."""
	_update_pr_approval_status(doc)


def _check_overbilling(doc):
	"""Prevent total billed qty (drafts + submitted) from exceeding PO qty."""
	for item in doc.items:
		if not item.get("po_detail"):
			continue

		po_item = frappe.db.get_value(
			"Purchase Order Item",
			item.po_detail,
			["qty", "item_code"],
			as_dict=True,
		)
		if not po_item:
			continue

		# Sum qty across ALL non-cancelled PIs for this PO line (excluding current doc)
		existing_billed_qty = frappe.db.sql(
			"""
			SELECT IFNULL(SUM(pi_item.qty), 0)
			FROM `tabPurchase Invoice Item` pi_item
			INNER JOIN `tabPurchase Invoice` pi ON pi.name = pi_item.parent
			WHERE pi_item.po_detail = %s
			  AND pi.docstatus != 2
			  AND pi.name != %s
		""",
			(item.po_detail, doc.name or ""),
		)[0][0]

		total_qty = flt(existing_billed_qty) + flt(item.qty)

		if total_qty > flt(po_item.qty):
			over_by = total_qty - flt(po_item.qty)
			frappe.throw(
				"Overbilling blocked for item <b>{0}</b>:<br>"
				"PO qty: <b>{1}</b> | Already billed (incl. drafts): <b>{2}</b> "
				"| This PI qty: <b>{3}</b><br>"
				"Over by <b>{4}</b>. Cancel or reduce qty in another draft PI first.".format(
					po_item.item_code,
					flt(po_item.qty),
					flt(existing_billed_qty),
					flt(item.qty),
					over_by,
				)
			)


def _update_pr_approval_status(doc):
	"""Set custom_billing_approval_status on linked Purchase Receipts."""
	linked_prs = list(
		set([item.purchase_receipt for item in doc.items if item.get("purchase_receipt")])
	)

	for pr_name in linked_prs:
		# Check if any OTHER non-cancelled PI for this PR is in Pending Approval
		pending_elsewhere = frappe.db.sql(
			"""
			SELECT COUNT(pi.name)
			FROM `tabPurchase Invoice` pi
			INNER JOIN `tabPurchase Invoice Item` pi_item ON pi_item.parent = pi.name
			WHERE pi_item.purchase_receipt = %s
			  AND pi.docstatus != 2
			  AND pi.workflow_state = 'Pending Approval'
			  AND pi.name != %s
		""",
			(pr_name, doc.name or ""),
		)[0][0]

		current_is_pending = doc.workflow_state == "Pending Approval"

		new_status = "Pending Approval" if (pending_elsewhere or current_is_pending) else ""

		frappe.db.set_value(
			"Purchase Receipt",
			pr_name,
			"custom_billing_approval_status",
			new_status,
			update_modified=False,
		)
