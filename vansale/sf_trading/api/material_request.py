# Copyright (c) 2025, sf_trading and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import nowdate, add_days, flt


@frappe.whitelist()
def get_mr_purchase_connections(transfer_mr):
	"""
	Return all non-cancelled Purchase MRs linked to a Transfer MR (via item-level
	custom_source_mr) and the item_codes they cover.
	Used to render the connections panel and decide whether to show the button.
	"""
	frappe.has_permission("Material Request", "read", transfer_mr, throw=True)

	linked_items = frappe.get_all(
		"Material Request Item",
		filters={"custom_source_mr": transfer_mr, "docstatus": ["!=", 2]},
		fields=["parent", "item_code"],
		ignore_permissions=True,
	)

	purchase_mr_names = list({row.parent for row in linked_items})
	purchase_mrs = []
	if purchase_mr_names:
		purchase_mrs = frappe.get_all(
			"Material Request",
			filters={"name": ["in", purchase_mr_names]},
			fields=["name", "status", "docstatus", "transaction_date"],
			ignore_permissions=True,
		)

	return {
		"purchase_mrs": purchase_mrs,
		"covered_item_codes": list({row.item_code for row in linked_items}),
	}


@frappe.whitelist()
def make_purchase_request_from_mr(source_name):
	"""
	Map a submitted Material Transfer MR to a new (unsaved) Purchase MR.
	Each item carries custom_source_mr pointing back to the source MR.
	Called via frappe.model.open_mapped_doc — client opens the form without saving.
	"""
	frappe.has_permission("Material Request", "read", source_name, throw=True)
	frappe.has_permission("Material Request", "create", throw=True)

	src = frappe.get_doc("Material Request", source_name)
	if src.material_request_type != "Material Transfer":
		frappe.throw(_("Purchase Request can only be created from a Material Transfer request."))

	# The source warehouse of the transfer (set_from_warehouse) is the warehouse
	# that has no stock — purchases should be received there.
	source_warehouse = src.get("set_from_warehouse") or None

	mr = frappe.new_doc("Material Request")
	mr.material_request_type = "Purchase"
	mr.company = src.company
	mr.transaction_date = nowdate()
	mr.schedule_date = src.schedule_date
	mr.set_warehouse = source_warehouse
	mr.custom_priority = src.get("custom_priority") or None

	for src_item in src.items:
		mr.append("items", {
			"item_code": src_item.item_code,
			"item_name": src_item.item_name,
			"description": src_item.description,
			"qty": src_item.qty,
			"uom": src_item.uom,
			"stock_uom": src_item.stock_uom,
			"conversion_factor": src_item.conversion_factor or 1,
			"schedule_date": src_item.schedule_date or src.schedule_date,
			"warehouse": src_item.from_warehouse or source_warehouse,
			"custom_source_mr": source_name,
		})

	mr.run_method("set_missing_values")
	return mr.as_dict()


@frappe.whitelist()
def create_material_request(item_code, from_warehouse, to_warehouse, qty, schedule_date, material_request_type, company):
	"""
	Create a Material Request for Material Transfer from one warehouse to another.
	
	Args:
		item_code: Item code to request
		from_warehouse: Source warehouse (where items come from)
		to_warehouse: Target warehouse (where items go to)
		qty: Quantity to request
		schedule_date: Required date
		material_request_type: Type of material request (should be "Material Transfer")
		company: Company name
		
	Returns:
		Material Request name
	"""
	if not item_code:
		frappe.throw(_("Item Code is required"))
	
	if not from_warehouse:
		frappe.throw(_("From Warehouse is required"))
	
	if not to_warehouse:
		frappe.throw(_("To Warehouse is required"))
	
	if from_warehouse == to_warehouse:
		frappe.throw(_("From Warehouse and To Warehouse cannot be the same"))
	
	if not qty or flt(qty) <= 0:
		frappe.throw(_("Quantity must be greater than 0"))
	
	if not company:
		frappe.throw(_("Company is required"))
	
	# Validate item exists
	if not frappe.db.exists("Item", item_code):
		frappe.throw(_("Item {0} does not exist").format(item_code))
	
	# Validate warehouses exist
	if not frappe.db.exists("Warehouse", from_warehouse):
		frappe.throw(_("From Warehouse {0} does not exist").format(from_warehouse))
	
	if not frappe.db.exists("Warehouse", to_warehouse):
		frappe.throw(_("To Warehouse {0} does not exist").format(to_warehouse))
	
	# Get item details
	item_doc = frappe.get_cached_doc("Item", item_code)
	
	# Create Material Request - always Material Transfer
	material_request = frappe.new_doc("Material Request")
	material_request.transaction_date = nowdate()
	material_request.company = company
	material_request.material_request_type = "Material Transfer"
	# Set form-level warehouse fields (same as item table)
	material_request.set_warehouse = to_warehouse  # target warehouse
	material_request.set_from_warehouse = from_warehouse  # source warehouse

	# Add item with from_warehouse and to_warehouse
	material_request.append("items", {
		"item_code": item_code,
		"item_name": item_doc.item_name,
		"description": item_doc.description,
		"qty": flt(qty),
		"uom": item_doc.stock_uom,
		"stock_uom": item_doc.stock_uom,
		"schedule_date": schedule_date or add_days(nowdate(), 7),
		"warehouse": to_warehouse,  # Target warehouse
		"from_warehouse": from_warehouse,  # Source warehouse
		"item_group": item_doc.item_group,
		"brand": item_doc.brand
	})
	
	# Set missing values
	material_request.set_missing_values()
	
	# Insert
	material_request.insert(ignore_permissions=True)
	material_request.submit()  
	
	
	return material_request.name
