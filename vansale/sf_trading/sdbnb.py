"""Stock Delivered But Not Billed (SDBNB) accounting, backported to ERPNext v15.

Port of frappe/erpnext#56070 — "add company setting to enable Stock Delivered
But Not Billed accounting" — together with the base SDBNB behaviour that PR
configures, because v15 ships neither the Company fields nor the Sales Invoice
reversal entries (both landed on `develop` only).

Once a company opts in:

* a Delivery Note books the cost of the goods to the SDBNB account instead of
  the item's expense (COGS) account, so the value sits in an asset account
  while the customer has the stock but no invoice;
* the Sales Invoice that bills that Delivery Note credits SDBNB and debits COGS
  for the same valuation amount, which is where the cost is finally recognised.

Everything hangs off `custom_enable_stock_delivered_but_not_billed` on Company
and is a no-op for every company that leaves it switched off — including all
existing ones, since the field defaults to 0.

Upstream naming: core uses `enable_stock_delivered_but_not_billed`,
`stock_delivered_but_not_billed` and `disable_sdbnb_in_sr`. Here they carry the
`custom_` prefix so that an eventual upgrade to a core version shipping the real
fields cannot collide on fieldname; the values would then need copying across.
"""

import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.utils import cint, flt, get_link_to_form

import erpnext
from erpnext.accounts.utils import get_account_currency

SDBNB_ACCOUNT_TYPE = "Stock Delivered But Not Billed"

ENABLE_FIELD = "custom_enable_stock_delivered_but_not_billed"
ACCOUNT_FIELD = "custom_stock_delivered_but_not_billed"
DISABLE_IN_SR_FIELD = "custom_disable_sdbnb_in_sr"

DEPENDS_ON_ENABLE = "eval:doc." + ENABLE_FIELD

COMPANY_FIELDS = (ENABLE_FIELD, ACCOUNT_FIELD, DISABLE_IN_SR_FIELD, "default_expense_account")


def get_company_config(company: str) -> frappe._dict:
	"""SDBNB settings of a company, as a dict that is safe to read blindly."""
	if not company:
		return frappe._dict()

	return frappe.get_cached_value("Company", company, COMPANY_FIELDS, as_dict=True) or frappe._dict()


def is_sdbnb_enabled(company: str) -> bool:
	config = get_company_config(company)
	return bool(cint(config.get(ENABLE_FIELD)) and config.get(ACCOUNT_FIELD))


# ---------------------------------------------------------------------------
# Company — validation
# ---------------------------------------------------------------------------


def validate_company_sdbnb(doc, method=None):
	"""Company.validate hook: keep the SDBNB configuration coherent."""
	if doc.get("__islocal"):
		return

	enabled = cint(doc.get(ENABLE_FIELD))
	account = doc.get(ACCOUNT_FIELD)

	if enabled and not account:
		frappe.throw(_("Please select Stock Delivered But Not Billed Account"))

	if enabled and account:
		validate_sdbnb_account(doc.name, account)

	doc_before_save = doc.get_doc_before_save()
	if not (doc_before_save and doc_before_save.get(ACCOUNT_FIELD)):
		return

	account_changed = account != doc_before_save.get(ACCOUNT_FIELD)
	feature_disabled = cint(doc_before_save.get(ENABLE_FIELD)) and not enabled

	if account_changed or feature_disabled:
		validate_outstanding_sdbnb_transactions(doc.name, doc_before_save.get(ACCOUNT_FIELD))


def validate_sdbnb_account(company: str, account: str):
	"""The chosen account must belong to this company and carry the SDBNB type."""
	account_company, account_type, is_group = frappe.get_cached_value(
		"Account", account, ["company", "account_type", "is_group"]
	)

	if account_company != company:
		frappe.throw(
			_("Stock Delivered But Not Billed Account {0} does not belong to company {1}").format(
				frappe.bold(account), frappe.bold(company)
			)
		)

	if cint(is_group):
		frappe.throw(
			_("Stock Delivered But Not Billed Account {0} is a group account").format(frappe.bold(account))
		)

	if account_type != SDBNB_ACCOUNT_TYPE:
		frappe.throw(
			_("Account {0} must have Account Type set to {1}").format(
				frappe.bold(account), frappe.bold(_(SDBNB_ACCOUNT_TYPE))
			)
		)


def validate_outstanding_sdbnb_transactions(company: str, account: str):
	"""Block a change that would orphan the balance sitting in the SDBNB account."""
	GLEntry = frappe.qb.DocType("GL Entry")
	DeliveryNote = frappe.qb.DocType("Delivery Note")

	delivery_notes = (
		frappe.qb.from_(GLEntry)
		.join(DeliveryNote)
		.on((GLEntry.voucher_type == "Delivery Note") & (GLEntry.voucher_no == DeliveryNote.name))
		.select(DeliveryNote.name)
		.where(
			(GLEntry.is_cancelled == 0)
			& (GLEntry.company == company)
			& (GLEntry.account == account)
			& (DeliveryNote.per_billed < 100)
			& (DeliveryNote.docstatus == 1)
			& (DeliveryNote.status.isin(["To Bill", "Partially Billed"]))
		)
		.distinct()
		.run(pluck=True)
	)

	if delivery_notes:
		dn_links = ", ".join(get_link_to_form("Delivery Note", dn) for dn in delivery_notes[:10])

		frappe.throw(
			_(
				"Stock Delivered But Not Billed Account cannot be changed or disabled since account {0} contains outstanding Delivery Notes: {1}"
			).format(frappe.bold(account), dn_links)
		)


# ---------------------------------------------------------------------------
# Delivery Note — route the cost to SDBNB
# ---------------------------------------------------------------------------


def set_delivery_note_expense_account(doc, method=None):
	"""Delivery Note.validate hook: point stock rows at the SDBNB account.

	Runs after the controller's own validate, so `expense_account` is already
	filled from the item/company defaults by the time we get here.
	"""
	config = get_company_config(doc.company)

	sdbnb_account = config.get(ACCOUNT_FIELD)
	enabled = cint(config.get(ENABLE_FIELD))
	disable_sdbnb_in_sr = cint(config.get(DISABLE_IN_SR_FIELD))
	default_expense_account = config.get("default_expense_account")

	for item in doc.get("items"):
		if item.get("against_sales_invoice"):
			if sdbnb_account and item.expense_account == sdbnb_account:
				frappe.throw(
					_(
						"Row #{0}: Stock Delivered But Not Billed account cannot be used for items linked to a Sales Invoice"
					).format(item.idx)
				)
		else:
			is_stock_item = frappe.get_cached_value("Item", item.item_code, "is_stock_item")
			# Only stock items
			if is_stock_item and not item.get("is_fixed_asset") and not item.get("is_subcontracted"):
				# Sales Return handling
				if doc.get("is_return") and disable_sdbnb_in_sr and sdbnb_account and enabled:
					if default_expense_account and (
						not item.expense_account or item.expense_account == sdbnb_account
					):
						item.expense_account = default_expense_account

				elif sdbnb_account and enabled:
					item.expense_account = sdbnb_account

				elif sdbnb_account and item.expense_account == sdbnb_account:
					# feature switched off after the row was already pointed at SDBNB
					item.expense_account = default_expense_account

		if not item.expense_account and default_expense_account:
			item.expense_account = default_expense_account


# ---------------------------------------------------------------------------
# Sales Invoice — reverse SDBNB into COGS when the delivery is billed
# ---------------------------------------------------------------------------


def get_sdbnb_gl_entries(doc) -> list:
	"""GL entries that move a billed delivery's cost from SDBNB to COGS.

	Called from `CustomSalesInvoice.get_gl_entries`, so the entries are rebuilt
	the same way on a Repost Accounting Ledger run.
	"""
	config = get_company_config(doc.company)

	if not (cint(config.get(ENABLE_FIELD)) and config.get(ACCOUNT_FIELD)):
		return []

	if doc.get("is_return") and cint(config.get(DISABLE_IN_SR_FIELD)):
		return []

	# an update_stock invoice books its own COGS; nothing was parked in SDBNB
	if cint(doc.get("update_stock")) or not cint(erpnext.is_perpetual_inventory_enabled(doc.company)):
		return []

	gl_entries = []
	for item in doc.get("items"):
		booking = _get_sdbnb_booking_for_item(doc, item)
		if booking:
			_append_sdbnb_gl_entries(doc, item, booking, gl_entries)

	return gl_entries


def _get_sdbnb_booking_for_item(doc, item):
	"""SDBNB account and valuation to reverse for a billed-from-delivery-note item, if any."""
	if not item.get("delivery_note") and not item.get("dn_detail"):
		return None

	if not item.get("item_code") or not frappe.get_cached_value("Item", item.item_code, "is_stock_item"):
		return None

	dn_expense_account = (
		frappe.get_cached_value("Delivery Note Item", item.dn_detail, "expense_account")
		if item.get("dn_detail")
		else None
	)
	if not is_sdbnb_account(dn_expense_account):
		return None

	cogs_account = resolve_cogs_account(doc, item, dn_expense_account)
	if not cogs_account or cogs_account == dn_expense_account:
		return None

	delivery_note = item.get("delivery_note") or frappe.db.get_value(
		"Delivery Note Item", item.dn_detail, "parent"
	)
	if not delivery_note:
		return None

	sle = frappe.db.get_value(
		"Stock Ledger Entry",
		{
			"voucher_no": delivery_note,
			"voucher_detail_no": item.dn_detail,
			"item_code": item.item_code,
			"is_cancelled": 0,
		},
		["stock_value_difference", "actual_qty"],
		as_dict=True,
	)
	if not sle or not flt(sle.actual_qty):
		return None

	valuation_rate = flt(sle.stock_value_difference) / flt(sle.actual_qty)

	return {
		"dn_expense_account": dn_expense_account,
		"cogs_account": cogs_account,
		"valuation_amount": flt(valuation_rate * flt(item.stock_qty), doc.precision("base_net_total")),
	}


def is_sdbnb_account(account) -> bool:
	return bool(
		account and frappe.get_cached_value("Account", account, "account_type") == SDBNB_ACCOUNT_TYPE
	)


def resolve_cogs_account(doc, item, sdbnb_account):
	"""The account the cost belongs in once the delivery is billed."""
	candidate = item.get("expense_account")
	if candidate and candidate != sdbnb_account and not is_sdbnb_account(candidate):
		return candidate

	item_group = frappe.get_cached_value("Item", item.item_code, "item_group")
	for parenttype, parent in (("Item", item.item_code), ("Item Group", item_group)):
		if not parent:
			continue
		account = frappe.db.get_value(
			"Item Default",
			{"parenttype": parenttype, "parent": parent, "company": doc.company},
			"expense_account",
		)
		if account:
			return account

	return frappe.get_cached_value("Company", doc.company, "default_expense_account")


def _append_sdbnb_gl_entries(doc, item, booking, gl_entries) -> None:
	dn_expense_account = booking["dn_expense_account"]
	cogs_account = booking["cogs_account"]
	valuation_amount = booking["valuation_amount"]

	if not valuation_amount:
		return

	cost_center = item.get("cost_center") or doc.get("cost_center")

	gl_entries.append(
		doc.get_gl_dict(
			{
				"account": dn_expense_account,
				"against": cogs_account,
				"credit": valuation_amount,
				"credit_in_account_currency": valuation_amount,
				"cost_center": cost_center,
				"project": item.get("project") or doc.get("project"),
				"remarks": _("Stock Delivered But Not Billed reversed on billing"),
			},
			get_account_currency(dn_expense_account),
			item=item,
		)
	)

	gl_entries.append(
		doc.get_gl_dict(
			{
				"account": cogs_account,
				"against": dn_expense_account,
				"debit": valuation_amount,
				"debit_in_account_currency": valuation_amount,
				"cost_center": cost_center,
				"project": item.get("project") or doc.get("project"),
				"remarks": _("Cost of goods recognised on billing"),
			},
			get_account_currency(cogs_account),
			item=item,
		)
	)


# ---------------------------------------------------------------------------
# Setup — custom fields, Account Type option, account helper
# ---------------------------------------------------------------------------


def setup_sdbnb():
	"""Kept as an entry point; provisioning lives in one place for both features."""
	from vansale.sf_trading.stock_billing_setup import setup

	setup()


def ensure_custom_fields():
	create_custom_fields(
		{
			"Company": [
				{
					"fieldname": ENABLE_FIELD,
					"label": "Enable Stock Delivered But Not Billed",
					"fieldtype": "Check",
					"default": "0",
					"insert_after": "stock_received_but_not_billed",
					"description": (
						"If enabled, the value of goods delivered before invoicing will be recorded "
						"in the Stock Delivered But Not Billed account."
					),
				},
				{
					"fieldname": ACCOUNT_FIELD,
					"label": "Stock Delivered But Not Billed",
					"fieldtype": "Link",
					"options": "Account",
					"insert_after": ENABLE_FIELD,
					"depends_on": DEPENDS_ON_ENABLE,
					"mandatory_depends_on": DEPENDS_ON_ENABLE,
					"ignore_user_permissions": 1,
					"no_copy": 1,
				},
				{
					"fieldname": DISABLE_IN_SR_FIELD,
					"label": "Disable Stock Delivered But Not Billed in Sales Return",
					"fieldtype": "Check",
					"default": "0",
					"insert_after": ACCOUNT_FIELD,
					"depends_on": DEPENDS_ON_ENABLE,
					"no_copy": 1,
				},
			]
		},
		ignore_validate=True,
	)


@frappe.whitelist()
def create_sdbnb_account(company: str, account_name: str = "Stock Delivered But Not Billed", parent_account=None) -> str:
	"""Create (or return) the SDBNB account for a company, under Stock Assets.

	Whitelisted so it can be run from the console or the API during setup;
	writing an Account is permission-checked like any other Account creation.
	"""
	frappe.has_permission("Account", "create", throw=True)

	from vansale.sf_trading.stock_billing_setup import ensure_account_type_options

	ensure_account_type_options()

	abbr = frappe.get_cached_value("Company", company, "abbr")
	name = account_name + " - " + abbr

	if frappe.db.exists("Account", name):
		if frappe.db.get_value("Account", name, "account_type") != SDBNB_ACCOUNT_TYPE:
			frappe.db.set_value("Account", name, "account_type", SDBNB_ACCOUNT_TYPE)
		return name

	parent_account = parent_account or _get_stock_assets_parent(company)
	if not parent_account:
		frappe.throw(
			_("Could not find a group account under Current Assets for company {0}").format(company)
		)

	account = frappe.get_doc(
		{
			"doctype": "Account",
			"account_name": account_name,
			"parent_account": parent_account,
			"company": company,
			"account_type": SDBNB_ACCOUNT_TYPE,
			"root_type": "Asset",
			"is_group": 0,
		}
	).insert()

	return account.name


def _get_stock_assets_parent(company: str):
	for account_name in ("Stock Assets", "Current Assets"):
		parent = frappe.db.get_value(
			"Account",
			{"company": company, "account_name": account_name, "is_group": 1},
			"name",
		)
		if parent:
			return parent

	return frappe.db.get_value(
		"Account",
		{"company": company, "root_type": "Asset", "is_group": 1, "parent_account": ["!=", ""]},
		"name",
	)
