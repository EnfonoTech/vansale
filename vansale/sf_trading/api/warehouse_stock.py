import frappe
from frappe import _
from erpnext.stock.utils import get_stock_balance


@frappe.whitelist()
def get_item_warehouse_stock(item_code, company=None, limit=None, target_warehouse=None):
	"""
	Get stock balance for an item across all warehouses in a company.
	Optimized to use Bin table for faster bulk queries.
	
	Args:
		item_code: Item code to get stock for
		company: Company name (optional, will use default if not provided)
		limit: Limit number of results (optional, for pagination)
		target_warehouse: Target warehouse to prioritize (optional)
	
	Returns:
		List of dictionaries with warehouse name and stock balance
	"""
	if not item_code:
		frappe.throw(_("Item Code is required"))
	
	# Get company from context or use default
	if not company:
		company = frappe.defaults.get_user_default("company")
	
	if not company:
		frappe.throw(_("Please set a default company"))
	
	# Get all warehouses for the company (non-group warehouses only)
	warehouses = frappe.get_all(
		"Warehouse",
		filters={
			"company": company,
			"is_group": 0,
			"disabled": 0
		},
		fields=["name", "warehouse_name"],
		order_by="name"
	)
	
	if not warehouses:
		return []
	
	# Optimize: Use Bin table for faster stock queries (bulk query)
	warehouse_names = [w.name for w in warehouses]

	# Fetch stock UOM for the item
	stock_uom = frappe.db.get_value("Item", item_code, "stock_uom") or ""

	# Use Bin table for faster bulk query
	bin_data = frappe.db.sql("""
		SELECT warehouse, actual_qty
		FROM `tabBin`
		WHERE item_code = %s AND warehouse IN %s
	""", (item_code, warehouse_names), as_dict=True)

	# Create a dict for quick lookup
	bin_dict = {d.warehouse: (d.actual_qty or 0.0) for d in bin_data}

	# Build stock data list
	stock_data = []
	for warehouse in warehouses:
		# Get stock from bin_dict (faster than individual get_stock_balance calls)
		stock_qty = bin_dict.get(warehouse.name, 0.0)

		stock_data.append({
			"warehouse": warehouse.name,
			"warehouse_name": warehouse.warehouse_name or warehouse.name,
			"stock_qty": stock_qty,
			"uom": stock_uom,
		})
	
	# Filter: Only show warehouses with stock > 0 (or target warehouse even if 0)
	if target_warehouse:
		filtered_stock_data = [item for item in stock_data if item["stock_qty"] > 0 or item["warehouse"] == target_warehouse]
	else:
		filtered_stock_data = [item for item in stock_data if item["stock_qty"] > 0]
	
	# Sort: target warehouse first, then by stock quantity descending
	if target_warehouse:
		filtered_stock_data.sort(key=lambda x: (-1 if x["warehouse"] == target_warehouse else 0, -x["stock_qty"]))
	else:
		filtered_stock_data.sort(key=lambda x: x["stock_qty"], reverse=True)
	
	# Apply limit if specified
	if limit:
		limit = int(limit)
		return filtered_stock_data[:limit]
	
	return filtered_stock_data


@frappe.whitelist()
def get_available_qty(item_code: str, warehouse: str) -> float:
	"""Return actual_qty from Bin for the given item + warehouse."""
	if not item_code or not warehouse:
		return 0.0
	return frappe.utils.flt(
		frappe.db.get_value("Bin", {"item_code": item_code, "warehouse": warehouse}, "actual_qty") or 0
	)
