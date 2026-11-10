import frappe
from frappe import _
from frappe.utils import flt


def auto_create_pr_return(doc, method=None):
	"""
	On submit of a Purchase Invoice Return (Debit Note), auto-create and submit a
	Purchase Receipt Return for each linked PR.

	Handles two workflows:
	  Case 1 (PR-first): PI was created from PR → PI items have purchase_receipt + pr_detail
	  Case 2 (PI-first): PI was created first, PR created separately →
	    PR items carry purchase_invoice_item pointing back to the PI item.
	    PI Return items also carry purchase_invoice_item (the original PI item name),
	    so we reverse-lookup: PR item where purchase_invoice_item = that PI item.

	Runs silently — logs errors but never blocks the PI return submission.
	"""
	if not doc.is_return:
		return

	# Build: pr_name → {pr_item_name: abs_qty_to_return}
	pr_groups = {}

	for item in doc.items:
		abs_qty = flt(abs(item.qty))
		if not abs_qty:
			continue

		# Case 1: direct link on PI item
		if item.purchase_receipt and item.pr_detail:
			pr_groups.setdefault(item.purchase_receipt, {})[item.pr_detail] = abs_qty

		# Case 2: PI-first — find PR items that reference the same original PI item
		elif item.purchase_invoice_item:
			matched = frappe.get_all(
				"Purchase Receipt Item",
				filters={"purchase_invoice_item": item.purchase_invoice_item, "docstatus": 1},
				fields=["name", "parent"],
				ignore_permissions=True,
			)
			for row in matched:
				pr_groups.setdefault(row.parent, {})[row.name] = abs_qty

	if not pr_groups:
		return

	for pr_name, item_qty_map in pr_groups.items():
		try:
			_create_pr_return_for(doc, pr_name, item_qty_map)
		except Exception:
			frappe.log_error(
				frappe.get_traceback(),
				_("Auto PR Return Failed — PI {0}, PR {1}").format(doc.name, pr_name),
			)
			frappe.msgprint(
				_(
					"Could not auto-create Purchase Receipt Return for {0}. "
					"Please create it manually. Error logged."
				).format(frappe.bold(pr_name)),
				indicator="orange",
				alert=True,
			)


def _create_pr_return_for(pi_return_doc, pr_name, item_qty_map):
	"""
	item_qty_map: {pr_item_name: abs_qty_being_returned}

	Creates and submits a PR Return scoped to only the items and quantities
	being reversed by the PI Return. Skips items already fully returned on the PR side.
	"""
	from erpnext.controllers.sales_and_purchase_return import make_return_doc

	# Cap each item's return qty at what's still returnable on the PR side
	pr_item_returnable = {}
	for pr_item_name, pi_return_qty in item_qty_map.items():
		original_qty = flt(frappe.db.get_value("Purchase Receipt Item", pr_item_name, "qty"))
		already_returned = flt(
			frappe.db.sql(
				"""
				SELECT COALESCE(SUM(ABS(pri.qty)), 0)
				FROM `tabPurchase Receipt Item` pri
				JOIN `tabPurchase Receipt` pr ON pr.name = pri.parent
				WHERE pri.purchase_receipt_item = %s
				  AND pr.is_return = 1
				  AND pr.docstatus = 1
				""",
				pr_item_name,
			)[0][0]
		)
		remaining = original_qty - already_returned
		qty_to_return = min(pi_return_qty, remaining)
		if qty_to_return > 0:
			pr_item_returnable[pr_item_name] = qty_to_return

	if not pr_item_returnable:
		frappe.msgprint(
			_(
				"Purchase Receipt {0} is already fully returned. "
				"Skipping auto PR return."
			).format(frappe.bold(pr_name)),
			indicator="blue",
			alert=True,
		)
		return

	pr_return = make_return_doc("Purchase Receipt", pr_name)
	# make_return_doc sets is_return=1 internally; reassert explicitly to guard
	# against any controller hook resetting them before insert.
	pr_return.is_return = 1
	pr_return.return_against = pr_name

	items_to_keep = []
	for item in pr_return.items:
		if item.purchase_receipt_item in pr_item_returnable:
			qty = -1 * pr_item_returnable[item.purchase_receipt_item]
			item.qty = qty
			item.received_qty = qty
			item.stock_qty = qty * flt(item.conversion_factor or 1)
			item.received_stock_qty = item.stock_qty
			items_to_keep.append(item)

	if not items_to_keep:
		return

	pr_return.set("items", items_to_keep)
	pr_return.run_method("calculate_taxes_and_totals")

	pr_return.flags.ignore_permissions = True
	pr_return.insert()

	# Re-fetch from DB so __init__ runs with is_return=1 already saved.
	# This ensures status_updater gets the return-specific entries that update
	# per_returned / "Return Issued" on the original PR when submit fires.
	pr_return = frappe.get_doc("Purchase Receipt", pr_return.name)
	pr_return.flags.ignore_permissions = True
	pr_return.submit()

	frappe.msgprint(
		_("Purchase Receipt Return {0} created and submitted automatically.").format(
			frappe.utils.get_link_to_form("Purchase Receipt", pr_return.name)
		),
		indicator="green",
	)
