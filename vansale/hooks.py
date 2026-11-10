app_name = "vansale"
app_title = "Van Sale"
app_publisher = "Enfono Technologies"
app_description = "Van Sales PWA — offline-first Vue 3 SPA + Capacitor APK"
app_email = "ramees@enfono.com"
app_license = "mit"

# The sf_trading app (trading features for Steel Force) was merged into this app
# under the vansale.sf_trading package. Its JS lives in public/sf_trading, its docs in
# docs/sf_trading, and its DocTypes / reports / pages under the "Sf Trading" module.
# Do not install both apps on one site: they would register the same hooks twice.
from vansale import __version__ as _v

# Hooks that run on migrate.
# - ensure_capacitor_cors is idempotent and critical for APK login.
# - setup.after_migrate installs the Van User role + its DocPerms and
#   re-applies User Permissions for all Vansale Configuration rows.
# - the sf_trading entries follow.
after_migrate = [
    "vansale.install.ensure_capacitor_cors",
    "vansale.setup.after_migrate",
    "vansale.sf_trading.inter_branch.ensure_branch_accounting_dimension",
    # Company/Sales Invoice Item fields + the two stock-timing Account Types
    "vansale.sf_trading.stock_billing_setup.setup",
    # per-company switch arming the Period Closing open item gate; runs after the
    # stock billing setup because it anchors below the field that one creates
    "vansale.sf_trading.period_closing.ensure_custom_fields",
    # header expense account for a Material Issue
    "vansale.sf_trading.stock_entry_expense.ensure_custom_fields",
]

# /vansale and every /vansale/<path> render www/vansale (the SPA's index.html),
# so the web app has clean URLs and a refresh on a deep link works.
website_route_rules = [
    {"from_route": "/vansale/<path:app_path>", "to_route": "vansale"},
]

# Install files for the web app (manifest, service worker, icons) under /vansale.
page_renderer = ["vansale.pwa.VansalePWARenderer"]

# Property Setters carried over from the Steel Force site database (never exported by sf_trading).
_SITE_PROPERTY_SETTERS = (
	"Customer-main-field_order",
	"Customer-naming_series-hidden",
	"Customer-naming_series-reqd",
	"Delivery Note Item-barcode-hidden",
	"Delivery Note Item-target_warehouse-hidden",
	"Delivery Note-base_rounded_total-hidden",
	"Delivery Note-base_rounded_total-print_hide",
	"Delivery Note-disable_rounded_total-default",
	"Delivery Note-in_words-hidden",
	"Delivery Note-in_words-print_hide",
	"Delivery Note-rounded_total-hidden",
	"Delivery Note-rounded_total-print_hide",
	"Delivery Note-scan_barcode-hidden",
	"Delivery Note-tax_id-hidden",
	"Delivery Note-tax_id-print_hide",
	"Item Barcode-barcode-hidden",
	"Item-barcodes-hidden",
	"Item-item_code-hidden",
	"Item-item_code-reqd",
	"Item-naming_series-hidden",
	"Item-naming_series-reqd",
	"Material Request-scan_barcode-hidden",
	"POS Invoice Item-barcode-hidden",
	"POS Invoice-scan_barcode-hidden",
	"Packed Item-rate-read_only",
	"Pick List-scan_barcode-hidden",
	"Purchase Invoice Item-from_warehouse-hidden",
	"Purchase Invoice-base_rounded_total-print_hide",
	"Purchase Invoice-disable_rounded_total-default",
	"Purchase Invoice-in_words-print_hide",
	"Purchase Invoice-rounded_total-print_hide",
	"Purchase Invoice-scan_barcode-hidden",
	"Purchase Invoice-taxes-hidden",
	"Purchase Invoice-taxes_and_charges-hidden",
	"Purchase Order-base_rounded_total-hidden",
	"Purchase Order-base_rounded_total-print_hide",
	"Purchase Order-disable_rounded_total-default",
	"Purchase Order-in_words-hidden",
	"Purchase Order-in_words-print_hide",
	"Purchase Order-rounded_total-hidden",
	"Purchase Order-rounded_total-print_hide",
	"Purchase Order-scan_barcode-hidden",
	"Purchase Receipt Item-barcode-hidden",
	"Purchase Receipt Item-from_warehouse-hidden",
	"Purchase Receipt-base_rounded_total-print_hide",
	"Purchase Receipt-disable_rounded_total-default",
	"Purchase Receipt-in_words-print_hide",
	"Purchase Receipt-rounded_total-print_hide",
	"Purchase Receipt-scan_barcode-hidden",
	"Sales Invoice Item-barcode-hidden",
	"Sales Invoice Item-discount_account-hidden",
	"Sales Invoice Item-discount_account-mandatory_depends_on",
	"Sales Invoice Item-target_warehouse-hidden",
	"Sales Invoice-additional_discount_account-hidden",
	"Sales Invoice-additional_discount_account-mandatory_depends_on",
	"Sales Invoice-base_rounded_total-hidden",
	"Sales Invoice-base_rounded_total-print_hide",
	"Sales Invoice-disable_rounded_total-default",
	"Sales Invoice-in_words-hidden",
	"Sales Invoice-in_words-print_hide",
	"Sales Invoice-rounded_total-hidden",
	"Sales Invoice-rounded_total-print_hide",
	"Sales Invoice-scan_barcode-hidden",
	"Sales Invoice-tax_id-hidden",
	"Sales Invoice-tax_id-print_hide",
	"Sales Order-base_rounded_total-print_hide",
	"Sales Order-disable_rounded_total-default",
	"Sales Order-in_words-print_hide",
	"Sales Order-rounded_total-print_hide",
	"Sales Order-scan_barcode-hidden",
	"Sales Order-tax_id-hidden",
	"Sales Order-tax_id-print_hide",
	"Stock Entry Detail-barcode-hidden",
	"Stock Entry-scan_barcode-hidden",
	"Stock Reconciliation Item-barcode-hidden",
	"Stock Reconciliation-scan_barcode-hidden",
	"Supplier Quotation-base_rounded_total-hidden",
	"Supplier Quotation-base_rounded_total-print_hide",
	"Supplier Quotation-disable_rounded_total-default",
	"Supplier Quotation-in_words-hidden",
	"Supplier Quotation-in_words-print_hide",
	"Supplier Quotation-rounded_total-hidden",
	"Supplier Quotation-rounded_total-print_hide",
	"Supplier-naming_series-hidden",
	"Supplier-naming_series-reqd",
)

# Custom Fields carried over from the Steel Force / Steel site databases.
_SITE_CUSTOM_FIELDS = (
	"Company-custom_block_period_closing_on_open_items",
	"Company-custom_disable_sdbnb_in_sr",
	"Company-custom_enable_stock_billed_but_not_delivered",
	"Company-custom_enable_stock_delivered_but_not_billed",
	"Company-custom_stock_billed_but_not_delivered",
	"Company-custom_stock_delivered_but_not_billed",
	"Purchase Invoice-custom_column_break_1qiuv",
	"Purchase Invoice-custom_column_break_ciiei",
	"Purchase Invoice-custom_rejection_reason",
	"Purchase Invoice-custom_section_break_jz0bg",
	"Purchase Invoice-workflow_state",
	"Quotation-custom_column_break_bwult",
	"Quotation-custom_column_break_zkmd4",
	"Quotation-custom_payment_mode",
	"Sales Invoice Item-custom_sbnd_valuation_rate",
	"Sales Invoice-workflow_state",
	"Stock Entry-custom_expense_account",
)

# Fixtures exported on `bench export-fixtures --app vansale`.
fixtures = [
	{
		"dt": "Custom Field",
		# Vansale's own fields (by module) plus the sf_trading custom fields, which
		# are named explicitly because they carry no module of their own
		"or_filters": [
			["module", "=", "Vansale"],
			[
				"name",
				"in",
				_SITE_CUSTOM_FIELDS + (
					"Company-custom_print_formats",
					"Company-custom_delivery_note_print_format",
					"Company-custom_max_payment_write_off",
					# created by vansale.sf_trading.sdbnb.setup_sdbnb on migrate; listed
					# here so an export keeps them in step
					"Company-custom_enable_stock_delivered_but_not_billed",
					"Company-custom_stock_delivered_but_not_billed",
					"Company-custom_disable_sdbnb_in_sr",
					"Company-custom_enable_stock_billed_but_not_delivered",
					"Company-custom_stock_billed_but_not_delivered",
					"Sales Invoice Item-custom_sbnd_valuation_rate",
					"Customer Credit Limit-custom_credit_days",
					"Customer-custom_commercial_registration_number",
					"Sales Invoice-inter_company_branch",
					"Sales Invoice-custom_sale_type",
					"Purchase Receipt-custom_billing_approval_status",
					"Purchase Taxes and Charges Template-custom_for_foreign_currency",
					"Purchase Taxes and Charges Template-custom_for_no_tax_id_supplier",
					"Customer-custom_vat_registration_number",
					"Sales Invoice-custom_credit_limit",
					"Sales Invoice-custom_contact_expairy_date",
					"Sales Invoice-custom_vat__expairy_date",
					"Sales Invoice-custom_payment_mode",
					"Branch-custom_letter_head",
					"Material Request-custom_priority",
					"Customer-custom_company",
					"Customer-custom_branch_access",
					"Sales Invoice-custom_driver",
					"Driver-custom_branch",
					"Driver-custom_payment_days",
					"Sales Invoice-custom_sales_person",
					"Quotation-branch",
					"Quotation-cost_center",
					"Quotation-project",
					"Quotation-set_warehouse",
					"Quotation Item-branch",
					"Quotation Item-cost_center",
					"Quotation Item-project",
					"Sales Invoice Item-custom_quotation",
					"Sales Invoice Item-custom_price_list",
					"Item Group-custom_min_margin_pct",
					"Price List-custom_enforce_min_price",
					"Material Request Item-custom_source_mr",
					"Activity Log-custom_impersonation_reason",
					"Payment Entry-custom_zatca_payment_means_code",
					"Journal Entry-custom_loyalty_sales_invoice",
					"Journal Entry Account-custom_loyalty_sales_invoice",
					"Payment Entry-custom_payment_advice",
					"Supplier-custom_disable_auto_payment",
				),
			],
		],
	},
	{
		"doctype": "Role",
		"filters": [["name", "in", ("B2B Creator",)]],
	},
	{
		"doctype": "Custom DocPerm",
		"filters": [["parent", "in", ("Driver",)]],
	},
	{
		"doctype": "DocType",
		"filters": [["name", "in", ("Company Print Format",)]],
	},
	{
		"doctype": "Report",
		"filters": [
				[
					"name",
					"in",
					(
						"DCR Report",
						"DCR Detailed",
						"DCR Detail",
					)
				]
		]
	},
	{
		"doctype": "Property Setter",
		"filters": [["name", "in", _SITE_PROPERTY_SETTERS + (
			"Sales Invoice Item-barcode-in_list_view",
			"Sales Taxes and Charges-cost_center-ignore_user_permissions",
			"Sales Invoice Item-cost_center-ignore_user_permissions",
			"Purchase Invoice-is_paid-hidden",
			"Purchase Invoice-is_return-hidden",
			"Purchase Invoice-return_against-hidden",
			"Purchase Invoice-update_outstanding_for_self-hidden",
			"Purchase Invoice-update_billed_amount_in_purchase_order-hidden",
			"Purchase Invoice-update_billed_amount_in_purchase_receipt-hidden",
			"Purchase Invoice-apply_tds-hidden",
			"Purchase Invoice-amended_from-hidden",
			# default the two advance switches on, so the PO -> PI mapper fills the
			# advance table at creation; set_advance_allocation turns them back off on an
			# invoice that names no order
			"Purchase Invoice-allocate_advances_automatically-default",
			"Purchase Invoice-only_include_allocated_payments-default",
			"Purchase Invoice-set_posting_time-hidden",
			"Purchase Invoice-sec_warehouse-collapsible",
			"Purchase Invoice-total_net_weight-hidden",
			"Purchase Invoice-base_total-hidden",
			"Purchase Invoice-base_net_total-hidden",
			"Purchase Invoice-net_total-hidden",
			"Purchase Invoice-tax_category-hidden",
			"Purchase Invoice-shipping_rule-hidden",
			"Purchase Invoice-incoterm-hidden",
			"Purchase Invoice-named_place-hidden",
			"Purchase Invoice-base_taxes_and_charges_added-hidden",
			"Purchase Invoice-base_taxes_and_charges_deducted-hidden",
			"Purchase Invoice-taxes_and_charges_added-hidden",
			"Purchase Invoice-taxes_and_charges_deducted-hidden",
			"Purchase Invoice-total_taxes_and_charges-hidden",
			"Purchase Invoice-base_grand_total-hidden",
			"Purchase Invoice-base_rounding_adjustment-hidden",
			"Purchase Invoice-base_rounded_total-hidden",
			"Purchase Invoice-base_in_words-hidden",
			"Purchase Invoice-disable_rounded_total-hidden",
			"Purchase Invoice-apply_discount_on-hidden",
			"Purchase Invoice-base_discount_amount-hidden",
			"Purchase Invoice-additional_discount_percentage-hidden",
			"Purchase Invoice-discount_amount-hidden",
			"Purchase Invoice-tax_withheld_vouchers-hidden",
			"Purchase Invoice-other_charges_calculation-hidden",
			"Purchase Invoice-pricing_rules-hidden",
			"Purchase Invoice-main-field_order",
			"Purchase Invoice-section_break_49-collapsible",
			"Purchase Invoice-in_words-hidden",
			"Purchase Invoice-rounded_total-hidden",
			"Purchase Invoice-rounding_adjustment-hidden",
			"Purchase Invoice-use_company_roundoff_cost_center-hidden",
			"Quotation-pricing_rules-hidden",
			"Quotation-packed_items-hidden",
			"Quotation-other_charges_calculation-hidden",
			"Quotation-referral_sales_partner-hidden",
			"Quotation-discount_amount-hidden",
			"Quotation-additional_discount_percentage-hidden",
			"Quotation-coupon_code-hidden",
			"Quotation-base_discount_amount-hidden",
			"Quotation-apply_discount_on-hidden",
			"Quotation-disable_rounded_total-hidden",
			"Quotation-rounding_adjustment-hidden",
			"Quotation-grand_total-hidden",
			"Quotation-base_in_words-hidden",
			"Quotation-base_rounding_adjustment-hidden",
			"Quotation-total_taxes_and_charges-hidden",
			"Quotation-taxes-hidden",
			"Quotation-named_place-hidden",
			"Quotation-incoterm-hidden",
			"Quotation-shipping_rule-hidden",
			"Quotation-taxes_and_charges-hidden",
			"Quotation-tax_category-hidden",
			"Quotation-net_total-hidden",
			"Quotation-total-hidden",
			"Quotation-base_net_total-hidden",
			"Quotation-total_net_weight-hidden",
			"Quotation-last_scanned_warehouse-hidden",
			"Quotation-order_type-hidden",
			"Quotation-main-hidden",
			"Quotation-main-field_order",
			"Quotation-scan_barcode-hidden",
			"Quotation-in_words-print_hide",
			"Quotation-in_words-hidden",
			"Quotation-disable_rounded_total-default",
			"Quotation-rounded_total-print_hide",
			"Quotation-rounded_total-hidden",
			"Quotation-base_rounded_total-print_hide",
			"Quotation-base_rounded_total-hidden",
			"Purchase Receipt-grand_total-hidden",
			"Purchase Receipt-main-field_order",
			"Purchase Receipt-disable_rounded_total-hidden",
			"Purchase Receipt-in_words-hidden",
			"Purchase Receipt-rounded_total-hidden",
			"Purchase Receipt-rounding_adjustment-hidden",
			"Purchase Receipt-base_in_words-hidden",
			"Purchase Receipt-base_rounded_total-hidden",
			"Purchase Receipt-base_rounding_adjustment-hidden",
			"Purchase Receipt-total_taxes_and_charges-hidden",
			"Purchase Receipt-taxes_and_charges_deducted-hidden",
			"Purchase Receipt-taxes_and_charges_added-hidden",
			"Purchase Receipt-base_taxes_and_charges_deducted-hidden",
			"Purchase Receipt-base_taxes_and_charges_added-hidden",
			"Purchase Receipt-base_grand_total-hidden",
			"Purchase Receipt-taxes-hidden",
			"Purchase Receipt-named_place-hidden",
			"Purchase Receipt-incoterm-hidden",
			"Purchase Receipt-shipping_rule-hidden",
			"Purchase Receipt-taxes_and_charges-hidden",
			"Purchase Receipt-tax_category-hidden",
			"Purchase Receipt-net_total-hidden",
			"Purchase Receipt-total-hidden",
			"Purchase Receipt-total_net_weight-hidden",
			"Purchase Receipt-sec_warehouse-collapsible",
			"Purchase Receipt-return_against-hidden",
			"Purchase Receipt-is_return-hidden",
			"Purchase Receipt-apply_putaway_rule-hidden",
			"Purchase Receipt-set_posting_time-hidden",
			"Purchase Receipt-posting_time-hidden",
			"Sales Order-taxes-hidden",
			"Sales Order-pricing_rules-hidden",
			"Sales Order-packed_items-hidden",
			"Sales Order-other_charges_calculation-hidden",
			"Sales Order-discount_amount-hidden",
			"Sales Order-additional_discount_percentage-hidden",
			"Sales Order-coupon_code-hidden",
			"Sales Order-base_discount_amount-hidden",
			"Sales Order-apply_discount_on-hidden",
			"Sales Order-disable_rounded_total-hidden",
			"Sales Order-advance_paid-hidden",
			"Sales Order-in_words-hidden",
			"Sales Order-rounded_total-hidden",
			"Sales Order-rounding_adjustment-hidden",
			"Sales Order-grand_total-hidden",
			"Sales Order-base_in_words-hidden",
			"Sales Order-base_rounded_total-hidden",
			"Sales Order-total_taxes_and_charges-hidden",
			"Sales Order-named_place-hidden",
			"Sales Order-incoterm-hidden",
			"Sales Order-shipping_rule-hidden",
			"Sales Order-taxes_and_charges-hidden",
			"Sales Order-tax_category-hidden",
			"Sales Order-net_total-hidden",
			"Sales Order-total-hidden",
			"Sales Order-base_net_total-hidden",
			"Sales Order-total_net_weight-hidden",
			"Sales Order-main-field_order",
			"Sales Order-sec_warehouse-collapsible",
			"Sales Order-po_date-hidden",
			"Sales Order-po_no-hidden",
			"Stock Entry-from_warehouse-ignore_user_permissions",
			"Stock Entry-to_warehouse-ignore_user_permissions",
			"Stock Entry Detail-s_warehouse-ignore_user_permissions",
			"Stock Entry Detail-t_warehouse-ignore_user_permissions",
		)]]
	},
	{
		"doctype": "Notification",
		"filters": [["name", "in", ("Supplier Payment Due Reminder",)]],
	},
	{
		"doctype": "Workspace",
		"filters": [["name", "in", ("Supplier Payments", "Open Items")]],
	},
	{
		"doctype": "Number Card",
		"filters": [["name", "in", (
			"Pending Delivery Value",
			"Unbilled Deliveries Value",
			"Unbilled Receipts Value",
			"Pending Receipt Value",
		)]],
	},
	{
		"doctype": "Workflow",
		"filters": [["name", "in", ("Purchase Inv", "Sales Approval",)]],
	},
	{
		"doctype": "Workflow State",
		"filters": [["name", "in", ("Approved", "Draft", "Pending", "Rejected",)]],
	},
	{
		"doctype": "Workflow Action Master",
		"filters": [["name", "in", ("Approve", "ReSubmit", "Reject", "Review", "Send for Approval",)]],
	},
	{
		"doctype": "Client Script",
		"filters": [["name", "in", ("Item order", "comments",)]],
	},
	{
		"doctype": "Server Script",
		"filters": [["name", "in", ("comment",)]],
	},
]

# Inject Van User defaults + sidebar restrictions into the desk session.
boot_session = "vansale.boot.boot_session"

# Role home page — Van Users land straight on the PWA.
role_home_page = {
    "Van User": "/vansale",
    "Van Manager": "/vansale",
}

# ─── Desk JS (sf_trading) ─────────────────────────────────────────────────────
app_include_js = [
	# ── Multi-doctype: selling (Sales Invoice, Sales Order, Quotation, Delivery Note) ──
	f"/assets/vansale/sf_trading/js/last_selling_rate.js?{_v}",
	f"/assets/vansale/sf_trading/js/quick_entry.js?{_v}",
	f"/assets/vansale/sf_trading/js/create_customer.js?{_v}",
	f"/assets/vansale/sf_trading/js/selling_price_realtime.js?{_v}",
	# ── Multi-doctype: purchasing (Purchase Invoice, Purchase Order, Purchase Receipt, …) ──
	f"/assets/vansale/sf_trading/js/last_purchase_rate.js?{_v}",
	f"/assets/vansale/sf_trading/js/create_supplier.js?{_v}",
	# ── Multi-doctype: cross-selling + purchasing ──
	f"/assets/vansale/sf_trading/js/return_qty_autofix.js?{_v}",
	f"/assets/vansale/sf_trading/js/accounting_dimension_sync.js?{_v}",
	f"/assets/vansale/sf_trading/js/sales_invoice_item_search.js?{_v}",
	f"/assets/vansale/sf_trading/js/purchase_invoice_cost_center.js?{_v}",
	f"/assets/vansale/sf_trading/js/stock_availability.js?{_v}",
	# ── Global (all pages / all item_code fields / print patches) ──
	f"/assets/vansale/sf_trading/js/workflow_approval_shortcut.js?{_v}",
	f"/assets/vansale/sf_trading/js/item_search_cache_buster.js?{_v}",
	f"/assets/vansale/sf_trading/js/company_print_format.js?{_v}",
	# ── Overdue-invoice alert: chime + toast + desktop notification ──
	f"/assets/vansale/sf_trading/js/sf_overdue_alert.js?{_v}",
]

# doctype_js: loaded only when that specific doctype form opens
doctype_js = {
	"Sales Invoice":    "public/sf_trading/js/sales_invoice.js",
	"Sales Order":      "public/sf_trading/js/sales_order.js",
	"Stock Entry":      "public/sf_trading/js/stock_entry.js",
	"Material Request": "public/sf_trading/js/material_request.js",
	"Customer":         "public/sf_trading/js/customer_company.js",
	"Quotation":        "public/sf_trading/js/quotation.js",
	"Supplier Quotation": "public/sf_trading/js/purchase_tax_template.js",
	"Purchase Receipt":   "public/sf_trading/js/purchase_tax_template.js",
	# Payment Advice sits in the Create menu beside Payment Request, under the same conditions
	"Purchase Order":     [
		"public/sf_trading/js/purchase_tax_template.js",
		"public/sf_trading/js/payment_advice_form_action.js",
	],
	"Purchase Invoice":   [
		"public/sf_trading/js/purchase_tax_template.js",
		"public/sf_trading/js/payment_advice_form_action.js",
	],
	# cancelling a payment must not demand the advice behind it be cancelled as well
	"Payment Entry":      "public/sf_trading/js/payment_entry_cancel.js",
	# open item census + submit gate companion view
	"Period Closing Voucher": "public/sf_trading/js/period_closing_voucher.js",
}

# include js in doctype views
# doctype_js = {"doctype" : "public/sf_trading/js/doctype.js"}
doctype_list_js = {
	"Purchase Invoice": ["public/sf_trading/js/payment_advice_list_action.js", "public/sf_trading/js/purchase_invoice_list.js"],
	"Sales Invoice": ["public/sf_trading/js/payment_advice_list_action.js", "public/sf_trading/js/sales_invoice_list.js"],
	"Purchase Order": ["public/sf_trading/js/payment_advice_list_action.js", "public/sf_trading/js/purchase_order_list.js"],
	"Sales Order": ["public/sf_trading/js/payment_advice_list_action.js", "public/sf_trading/js/sales_order_list.js"],
}

# List-view filters — restrict Van Users to docs touching their warehouse,
# plus sf_trading's Item / Customer branch filters.
permission_query_conditions = {
    "Sales Invoice": "vansale.van_filters.sales_invoice_query",
    "Payment Entry": "vansale.van_filters.payment_entry_query",
    "Stock Entry": "vansale.van_filters.stock_entry_query",
    "Delivery Note": "vansale.van_filters.delivery_note_query",
    "Van Visit Log": "vansale.van_filters.van_visit_log_query",
    "Van Daily Visit": "vansale.van_filters.van_daily_visit_query",
    "Item": "vansale.sf_trading.branch_defaults.item_permission_query",
    "Customer": "vansale.sf_trading.customer_permission.permission_query_conditions_for_customer",
}

override_doctype_class = {
	"Sales Invoice": "vansale.sf_trading.overrides.sales_invoice_class.CustomSalesInvoice",
	"Delivery Note": "vansale.sf_trading.overrides.delivery_note_class.CustomDeliveryNote",
	"Purchase Invoice": "vansale.sf_trading.overrides.purchase_invoice_class.CustomPurchaseInvoice",
}

# Document hooks. Van hooks come first on each event: they force cost_center +
# warehouse to the van's defaults, which sf_trading's hooks then build on.
# Pushes header accounting dimensions (branch, cost_center, project) down to
# item rows (and cost_center to taxes) on every transaction doctype.
_CC_HOOK = "vansale.sf_trading.branch_defaults.propagate_dimensions_to_items"
_BRANCH_HOOK = "vansale.sf_trading.inter_branch.auto_set_branch_from_warehouse"
# Applies the branch's letter head to the document. Runs on validate, after
# _BRANCH_HOOK so an auto-resolved branch is honoured.
_LH_HOOK = "vansale.sf_trading.branch_defaults.set_letter_head_from_branch"
_SP_HOOK = "vansale.sf_trading.api.selling_price_validation.validate_selling_price"
# Picks the purchase tax template matching the document currency (default
# template for company-currency docs, "Import VAT 0%" otherwise).
_PTT_HOOK = "vansale.sf_trading.purchase_tax_template.set_template_by_currency"
# Books a Delivery Note's cost to the Stock Delivered But Not Billed account
# instead of COGS, for companies that enable it. See sf_trading/sdbnb.py.
_SDBNB_DN_HOOK = "vansale.sf_trading.sdbnb.set_delivery_note_expense_account"
# The mirror case — invoiced before delivery. Runs after _SDBNB_DN_HOOK so the
# invoice-linked rows it claims are the ones SDBNB deliberately left alone.
_SBND_DN_HOOK = "vansale.sf_trading.sbnd.set_delivery_note_expense_account"
doc_events = {
	"Vansale Configuration User": {
		"after_insert": "vansale.customer_hooks.clear_module_active_cache",
		"on_trash": "vansale.customer_hooks.clear_module_active_cache",
	},
	"Stock Entry": {
		# before_validate, so the header account faces ERPNext's own account checks
		# rather than being written past them
		"before_insert": "vansale.van_series.set_naming_series_from_van",
		"before_validate": [
			"vansale.van_defaults.override_cost_center_from_van",
			"vansale.sf_trading.stock_entry_expense.apply_expense_account",
		],
	},
	"Period Closing Voucher": {
		# a period must not close while it still carries unbilled / undelivered items
		"before_submit": "vansale.sf_trading.period_closing.validate_open_items",
	},
	"Payment Entry": {
		"before_insert": "vansale.van_series.set_naming_series_from_van",
		"before_validate": "vansale.van_defaults.override_cost_center_from_van",
		"validate": "vansale.sf_trading.api.payment_advice_hooks.validate_payment_entry_advice",
		"on_submit": "vansale.sf_trading.api.payment_advice_hooks.on_payment_entry_submit",
		"on_cancel": "vansale.sf_trading.api.payment_advice_hooks.on_payment_entry_cancel",
	},
	"Journal Entry": {
		# validate, not before_validate: the controller fills `debit` from
		# debit_in_account_currency * exchange_rate during its own validate, and a hooked
		# handler runs after it, so the debit rows are already known here
		"validate": "vansale.sf_trading.api.loyalty_reward_rows.validate_loyalty_reward_rows",
	},
	"Customer": {
		"before_insert": "vansale.customer_hooks.auto_assign_sales_person",
		"validate": [
			"vansale.sf_trading.api.customer_override.validate",
			"vansale.sf_trading.customer_permission.validate_credit_branch_access",
			"vansale.sf_trading.party_accounts.apply_title_case",
		],
		"before_save": [
			"vansale.sf_trading.customer_permission.auto_add_branch_on_credit_limit",
			"vansale.sf_trading.party_accounts.create_customer_receivable_account",
		],
	},
	"Supplier": {
		"validate": "vansale.sf_trading.party_accounts.apply_title_case",
		"before_save": "vansale.sf_trading.party_accounts.create_supplier_payable_account",
	},
	"Sales Invoice": {
		# before_insert, not before_validate: naming_series is consumed when the
		# name is generated at insert, so a later hook would be too late.
		"before_insert": "vansale.van_series.set_naming_series_from_van",
		# Van defaults first, so sf_trading's dimension propagation copies the
		# van's cost center onto the item rows rather than the pre-override one.
		"before_validate": [
			"vansale.van_defaults.override_cost_center_from_van",
			"vansale.van_defaults.override_warehouse_from_van",
			"vansale.sf_trading.api.sales_invoice_override.before_validate",
			_CC_HOOK,
			"vansale.sf_trading.branch_defaults.override_payment_accounts_from_branch",
		],
		"validate": [
			"vansale.sf_trading.api.sales_invoice_override.validate",
			"vansale.sf_trading.api.sales_invoice_override.validate_driver_payment",
			_BRANCH_HOOK,
			_LH_HOOK,
			_SP_HOOK,
			# freezes the valuation rate on rows invoiced ahead of delivery
			"vansale.sf_trading.sbnd.freeze_valuation_rate",
		],
		"on_submit": [
			"vansale.sf_trading.inter_company.sales_invoice_on_submit",
			"vansale.sf_trading.api.quotation.update_quotation_status_from_invoice",
		],
		"on_cancel": "vansale.sf_trading.api.quotation.update_quotation_status_from_invoice",
	},
	"Sales Order": {
		"before_validate": _CC_HOOK,
		"validate": [_LH_HOOK, _SP_HOOK],
	},
	"Quotation": {
		"before_validate": _CC_HOOK,
		"validate": [_LH_HOOK, _SP_HOOK],
	},
	"Delivery Note": {
		"before_validate": [
			"vansale.van_defaults.override_cost_center_from_van",
			"vansale.van_defaults.override_warehouse_from_van",
			_CC_HOOK,
		],
		# _SDBNB_DN_HOOK last: it reads the expense_account the controller and the
		# earlier hooks have already settled on, then re-points stock rows at the
		# Stock Delivered But Not Billed account when the company opts in.
		"validate": [_BRANCH_HOOK, _LH_HOOK, _SP_HOOK, _SDBNB_DN_HOOK, _SBND_DN_HOOK],
	},
	"Company": {
		"validate": [
			"vansale.sf_trading.sdbnb.validate_company_sdbnb",
			"vansale.sf_trading.sbnd.validate_company_sbnd",
		],
	},
	"Purchase Invoice": {
		"before_validate": [
			"vansale.sf_trading.inter_company.purchase_invoice_before_validate",
			_CC_HOOK,
			_PTT_HOOK,
			# before_validate, because the controller's own validate is what reads these
			# two switches and calls set_advances()
			"vansale.sf_trading.overrides.purchase_invoice.set_advance_allocation",
		],
		"validate": [
			"vansale.sf_trading.overrides.purchase_invoice.validate",
			_BRANCH_HOOK,
			_LH_HOOK,
		],
		"on_save": "vansale.sf_trading.overrides.purchase_invoice.on_save",
		"on_submit": "vansale.sf_trading.api.purchase_return.auto_create_pr_return",
	},
	"Purchase Order": {
		"before_validate": [_CC_HOOK, _PTT_HOOK],
		"validate": _LH_HOOK,
	},
	"Purchase Receipt": {
		"before_validate": [_CC_HOOK, _PTT_HOOK],
		"validate": [_BRANCH_HOOK, _LH_HOOK],
	},
	"Supplier Quotation": {
		"before_validate": [_CC_HOOK, _PTT_HOOK],
		"validate": _LH_HOOK,
	},
	# core logs the impersonation but drops the reason — put it back on the row
	"Activity Log": {
		"before_insert": "vansale.sf_trading.api.impersonation_log.capture_impersonation_reason",
	},
}

# Overriding Methods
# ------------------------------
#
override_whitelisted_methods = {
	"erpnext.controllers.queries.item_query": "vansale.sf_trading.api.item_search.search_items_with_stock_and_rate",
}

#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# Every doctype a Payment Advice may be raised against gets the advice in its Connections,
# so "has this been sent for payment?" is answerable from the voucher itself. The list
# mirrors VALID_REFERENCE_DOCTYPES in the Payment Advice controller.
_ADVICE_DASHBOARD = "vansale.sf_trading.api.payment_advice_dashboard.get_dashboard_data"

override_doctype_dashboards = {
	"Quotation": ["vansale.sf_trading.api.quotation.get_dashboard_data"],
	"Sales Order": [_ADVICE_DASHBOARD],
	"Sales Invoice": [_ADVICE_DASHBOARD],
	"Purchase Order": [_ADVICE_DASHBOARD],
	"Purchase Invoice": [_ADVICE_DASHBOARD],
	"Journal Entry": [_ADVICE_DASHBOARD],
	"Dunning": [_ADVICE_DASHBOARD],
}

# Request Events
# ----------------
before_request = ["vansale.sf_trading.api.item_search.redirect_item_query_before_request"]

# ─── Scheduler ────────────────────────────────────────────────────────────────
scheduler_events = {
	"daily": [
		"vansale.sf_trading.api.overdue_notifications.notify_overdue_invoices",
	],
	# every tick: each Payment Automation Settings row names its own weekday + time,
	# and the engine fences itself with last_execution
	"all": [
		"vansale.sf_trading.api.payment_automation.run_due_automations",
	],
}
