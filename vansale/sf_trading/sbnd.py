"""Stock Billed But Not Delivered (SBND) accounting.

The mirror of `vansale.sf_trading.sdbnb`, and unlike that one it has no upstream at all —
neither ERPNext nor any app in the reference corpus implements it.

SDBNB covers deliver-then-bill. This covers **bill-then-deliver**: a Sales
Invoice raised without "Update Stock" and with no Delivery Note behind it
recognises revenue immediately, while the goods are still in the warehouse, so
the cost only surfaces later when the delivery is made. Two periods, one sale.

Once a company opts in:

* the Sales Invoice debits COGS and credits the SBND liability account, valued
  at the item's valuation rate **frozen onto the invoice row at submit**;
* the Delivery Note raised against that invoice debits SBND and credits
  inventory at the *real* stock ledger value, and the difference between the
  frozen estimate and the real value is posted to COGS, so SBND lands back at
  zero and COGS ends up at actual cost.

The rate is frozen rather than looked up live because a Repost Accounting
Ledger re-runs `get_gl_entries`: a live lookup would rewrite historical COGS
every time moving-average valuation drifted.

Out of scope by design: return invoices, invoices carrying `update_stock`, and
rows already billing a Delivery Note (those are SDBNB's side of the fence).
"""

import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.utils import cint, flt, get_link_to_form, nowtime

import erpnext
from erpnext.accounts.utils import get_account_currency
from erpnext.stock.utils import get_incoming_rate

from vansale.sf_trading.sdbnb import resolve_cogs_account

SBND_ACCOUNT_TYPE = "Stock Billed But Not Delivered"

ENABLE_FIELD = "custom_enable_stock_billed_but_not_delivered"
ACCOUNT_FIELD = "custom_stock_billed_but_not_delivered"
RATE_FIELD = "custom_sbnd_valuation_rate"

COMPANY_FIELDS = (ENABLE_FIELD, ACCOUNT_FIELD, "default_expense_account")


def get_company_config(company: str) -> frappe._dict:
	if not company:
		return frappe._dict()

	return frappe.get_cached_value("Company", company, COMPANY_FIELDS, as_dict=True) or frappe._dict()


def is_sbnd_enabled(company: str) -> bool:
	config = get_company_config(company)
	return bool(cint(config.get(ENABLE_FIELD)) and config.get(ACCOUNT_FIELD))


def is_sbnd_account(account) -> bool:
	return bool(
		account and frappe.get_cached_value("Account", account, "account_type") == SBND_ACCOUNT_TYPE
	)


# ---------------------------------------------------------------------------
# Company — validation
# ---------------------------------------------------------------------------


def validate_company_sbnd(doc, method=None):
	"""Company.validate hook: keep the SBND configuration coherent."""
	if doc.get("__islocal"):
		return

	enabled = cint(doc.get(ENABLE_FIELD))
	account = doc.get(ACCOUNT_FIELD)

	if enabled and not account:
		frappe.throw(_("Please choose a Stock Billed But Not Delivered Account"))

	if enabled and account:
		validate_sbnd_account(doc.name, account)

	doc_before_save = doc.get_doc_before_save()
	if not (doc_before_save and doc_before_save.get(ACCOUNT_FIELD)):
		return

	account_changed = account != doc_before_save.get(ACCOUNT_FIELD)
	feature_disabled = cint(doc_before_save.get(ENABLE_FIELD)) and not enabled

	if account_changed or feature_disabled:
		validate_undelivered_invoices(doc.name, doc_before_save.get(ACCOUNT_FIELD))


def validate_sbnd_account(company: str, account: str):
	account_company, account_type, is_group = frappe.get_cached_value(
		"Account", account, ["company", "account_type", "is_group"]
	)

	if account_company != company:
		frappe.throw(
			_("Stock Billed But Not Delivered Account {0} does not belong to company {1}").format(
				frappe.bold(account), frappe.bold(company)
			)
		)

	if cint(is_group):
		frappe.throw(
			_("Stock Billed But Not Delivered Account {0} is a group account").format(frappe.bold(account))
		)

	if account_type != SBND_ACCOUNT_TYPE:
		frappe.throw(
			_("Account {0} must have Account Type set to {1}").format(
				frappe.bold(account), frappe.bold(_(SBND_ACCOUNT_TYPE))
			)
		)


def validate_undelivered_invoices(company: str, account: str):
	"""Block a change that would orphan the balance sitting in the SBND account."""
	invoices = frappe.get_all(
		"GL Entry",
		filters={
			"is_cancelled": 0,
			"company": company,
			"account": account,
			"voucher_type": "Sales Invoice",
		},
		pluck="voucher_no",
		distinct=True,
	)

	if not invoices:
		return

	undelivered = frappe.db.sql(
		"""select distinct parent from `tabSales Invoice Item`
		   where parent in %(names)s and docstatus = 1 and qty > ifnull(delivered_qty, 0)""",
		{"names": tuple(invoices)},
		pluck=True,
	)

	if undelivered:
		links = ", ".join(get_link_to_form("Sales Invoice", si) for si in undelivered[:10])
		frappe.throw(
			_(
				"Stock Billed But Not Delivered Account cannot be changed or disabled since account {0} still carries undelivered Sales Invoices: {1}"
			).format(frappe.bold(account), links)
		)


# ---------------------------------------------------------------------------
# Sales Invoice — freeze the estimate, then book COGS against SBND
# ---------------------------------------------------------------------------


def freeze_valuation_rate(doc, method=None):
	"""Sales Invoice.validate hook: stamp the valuation rate on qualifying rows.

	Stamped before the document is saved, so the number the GL is built from
	never moves again — including on a Repost Accounting Ledger.
	"""
	validate_zero_valuation_rows(doc)

	if not invoice_qualifies(doc):
		for item in doc.get("items"):
			if item.get(RATE_FIELD):
				item.set(RATE_FIELD, 0)
		return

	# A draft is still editable — the warehouse, item or qty can all change after a
	# save, so re-estimate every time and only let the number set at submit. Keeping
	# the first estimate would leave a rate belonging to a warehouse the row no
	# longer points at.
	already_submitted = cint((doc.get_doc_before_save() or frappe._dict()).get("docstatus")) == 1

	for item in doc.get("items"):
		if not row_qualifies(doc, item):
			item.set(RATE_FIELD, 0)
			continue

		if already_submitted and flt(item.get(RATE_FIELD)):
			# final — a repost or an update-after-submit must not move it
			continue

		item.set(RATE_FIELD, estimate_valuation_rate(doc, item))


def validate_zero_valuation_rows(doc):
	"""Refuse a sales row whose stock carries no valuation, however the row posts.

	Core only asks about valuation when it can find no rate at all. Stock that was
	received at zero leaves a rate of zero on record, which satisfies that lookup, so
	the sale goes through booking revenue and no cost — silently, whether the invoice
	updates stock itself or waits for a Delivery Note.

	This asks the question core would have asked, and takes the same answer: the
	per-row `Allow Zero Valuation Rate` checkbox.
	"""
	config = get_company_config(doc.company)

	if not (cint(config.get(ENABLE_FIELD)) and config.get(ACCOUNT_FIELD)):
		return

	if doc.get("is_return") or not cint(erpnext.is_perpetual_inventory_enabled(doc.company)):
		return

	if cint((doc.get_doc_before_save() or frappe._dict()).get("docstatus")) == 1:
		# already submitted — an update or a repost must not be blocked by this
		return

	unvalued = []
	for item in doc.get("items"):
		if item.get("dn_detail") or item.get("delivery_note"):
			# the delivery already valued this row
			continue

		if not item.get("item_code") or not item.get("warehouse") or item.get("is_fixed_asset"):
			continue

		if cint(item.get("allow_zero_valuation_rate")):
			continue

		if not frappe.get_cached_value("Item", item.item_code, "is_stock_item"):
			continue

		if not flt(estimate_valuation_rate(doc, item)):
			unvalued.append(item)

	if unvalued:
		throw_missing_valuation(unvalued)


def throw_missing_valuation(rows):
	"""Refuse to save an invoice that would carry no cost, until it is acknowledged.

	An invoice raised ahead of delivery writes no stock ledger entry, so core never
	asks about valuation on it — the row simply freezes at zero and the whole cost
	lands on the delivery instead. Asked for the same treatment core gives a stock
	transaction: stop, and require the `Allow Zero Valuation Rate` row checkbox, the
	same field and the same acknowledgement staff already know.

	Raised on every save, not just at submit, so the entry is caught while it is
	being written rather than at the end.
	"""
	lines = "".join(
		"<li>"
		+ _("Row #{0}: {1} in {2}").format(row.idx, frappe.bold(row.item_code), frappe.bold(row.warehouse))
		+ "</li>"
		for row in rows
	)

	message = _("Valuation Rate is required to recognise the cost of goods for these rows:")
	message += "<ul>" + lines + "</ul>"
	message += _("Here are the options to proceed:")
	message += (
		"<ul><li>"
		+ _(
			"If the item is transacting as a Zero Valuation Rate item in this entry, please enable {0} in the Sales Invoice Item table."
		).format(frappe.bold(_("Allow Zero Valuation Rate")))
		+ "</li><li>"
		+ _("If not, create an incoming stock transaction for the Item, or set a Valuation Rate in the Item master.")
		+ "</li></ul>"
	)

	frappe.throw(msg=message, title=_("Valuation Rate Missing"))


def invoice_qualifies(doc) -> bool:
	config = get_company_config(doc.company)

	if not (cint(config.get(ENABLE_FIELD)) and config.get(ACCOUNT_FIELD)):
		return False

	if cint(doc.get("update_stock")) or doc.get("is_return"):
		return False

	return bool(cint(erpnext.is_perpetual_inventory_enabled(doc.company)))


def row_qualifies(doc, item) -> bool:
	if item.get("dn_detail") or item.get("delivery_note"):
		# billing an existing delivery — that is SDBNB's side of the fence
		return False

	if not item.get("item_code") or not item.get("warehouse"):
		return False

	if item.get("is_fixed_asset"):
		return False

	return bool(frappe.get_cached_value("Item", item.item_code, "is_stock_item"))


def estimate_valuation_rate(doc, item) -> float:
	"""Best available cost per stock unit at invoice time — no SLE exists yet."""
	qty = flt(item.get("stock_qty")) or flt(item.get("qty"))

	rate = get_incoming_rate(
		{
			"item_code": item.item_code,
			"warehouse": item.warehouse,
			"posting_date": doc.get("posting_date"),
			"posting_time": doc.get("posting_time") or nowtime(),
			"qty": -1 * qty,
			"serial_and_batch_bundle": item.get("serial_and_batch_bundle"),
			"company": doc.company,
			"voucher_type": doc.doctype,
			"voucher_no": doc.name,
			"voucher_detail_no": item.name,
			"allow_zero_valuation": item.get("allow_zero_valuation_rate"),
			"batch_no": item.get("batch_no"),
			"serial_no": item.get("serial_no"),
		},
		raise_error_if_no_rate=False,
		fallbacks=True,
	)

	if not flt(rate):
		rate = frappe.db.get_value(
			"Bin", {"item_code": item.item_code, "warehouse": item.warehouse}, "valuation_rate"
		)

	if not flt(rate):
		rate = frappe.get_cached_value("Item", item.item_code, "valuation_rate")

	return flt(rate)


def return_qualifies(doc) -> bool:
	"""A credit note can only unwind what an invoice parked in SBND."""
	config = get_company_config(doc.company)

	if not (cint(config.get(ENABLE_FIELD)) and config.get(ACCOUNT_FIELD)):
		return False

	if cint(doc.get("update_stock")) or not doc.get("is_return") or not doc.get("return_against"):
		return False

	return bool(cint(erpnext.is_perpetual_inventory_enabled(doc.company)))


def get_return_reversal_entries(doc) -> list:
	"""Credit note side: give back the cost the invoice recognised early.

	Cancelling an invoice that was raised ahead of delivery leaves COGS carrying
	a cost for goods that never left, and SBND carrying a liability nothing will
	ever clear — no delivery is coming for a returned invoice. So unwind the
	pair, but only for the part that is still undelivered: anything already
	delivered has cleared SBND on its own, and the goods coming back is the
	return Delivery Note's business.
	"""
	config = get_company_config(doc.company)
	sbnd_account = config.get(ACCOUNT_FIELD)

	gl_entries = []
	for item in doc.get("items"):
		source_row = item.get("sales_invoice_item")
		if not source_row:
			continue

		source = frappe.db.get_value(
			"Sales Invoice Item",
			source_row,
			["qty", "stock_qty", "delivered_qty", RATE_FIELD],
			as_dict=True,
		)
		if not source or not flt(source.get(RATE_FIELD)):
			continue

		conversion = flt(source.stock_qty) / flt(source.qty) if flt(source.qty) else 1
		undelivered_stock_qty = flt(source.stock_qty) - flt(source.delivered_qty) * conversion
		reversal_qty = min(abs(flt(item.stock_qty)), max(undelivered_stock_qty, 0))
		if not reversal_qty:
			continue

		amount = flt(flt(source.get(RATE_FIELD)) * reversal_qty, doc.precision("base_net_total"))
		if not amount:
			continue

		cogs_account = resolve_cogs_account(doc, item, sbnd_account)
		if not cogs_account or cogs_account == sbnd_account:
			continue

		cost_center = item.get("cost_center") or doc.get("cost_center")

		gl_entries.append(
			doc.get_gl_dict(
				{
					"account": sbnd_account,
					"against": cogs_account,
					"debit": amount,
					"debit_in_account_currency": amount,
					"cost_center": cost_center,
					"project": item.get("project") or doc.get("project"),
					"remarks": _("Stock billed but not delivered, released on return"),
				},
				get_account_currency(sbnd_account),
				item=item,
			)
		)
		gl_entries.append(
			doc.get_gl_dict(
				{
					"account": cogs_account,
					"against": sbnd_account,
					"credit": amount,
					"credit_in_account_currency": amount,
					"cost_center": cost_center,
					"project": item.get("project") or doc.get("project"),
					"remarks": _("Cost of goods reversed, delivery never made"),
				},
				get_account_currency(cogs_account),
				item=item,
			)
		)

	return gl_entries


def get_sbnd_gl_entries(doc) -> list:
	"""Sales Invoice side: Dr COGS / Cr SBND at the frozen estimate."""
	config = get_company_config(doc.company)
	sbnd_account = config.get(ACCOUNT_FIELD)

	if return_qualifies(doc):
		return get_return_reversal_entries(doc)

	if not invoice_qualifies(doc):
		return []

	gl_entries = []
	for item in doc.get("items"):
		if not row_qualifies(doc, item):
			continue

		amount = flt(
			flt(item.get(RATE_FIELD)) * flt(item.get("stock_qty")), doc.precision("base_net_total")
		)
		if not amount:
			continue

		cogs_account = resolve_cogs_account(doc, item, sbnd_account)
		if not cogs_account or cogs_account == sbnd_account:
			continue

		cost_center = item.get("cost_center") or doc.get("cost_center")

		gl_entries.append(
			doc.get_gl_dict(
				{
					"account": cogs_account,
					"against": sbnd_account,
					"debit": amount,
					"debit_in_account_currency": amount,
					"cost_center": cost_center,
					"project": item.get("project") or doc.get("project"),
					"remarks": _("Cost of goods billed ahead of delivery"),
				},
				get_account_currency(cogs_account),
				item=item,
			)
		)
		gl_entries.append(
			doc.get_gl_dict(
				{
					"account": sbnd_account,
					"against": cogs_account,
					"credit": amount,
					"credit_in_account_currency": amount,
					"cost_center": cost_center,
					"project": item.get("project") or doc.get("project"),
					"remarks": _("Stock billed but not delivered"),
				},
				get_account_currency(sbnd_account),
				item=item,
			)
		)

	return gl_entries


# ---------------------------------------------------------------------------
# Delivery Note — clear SBND, and put the estimate error into COGS
# ---------------------------------------------------------------------------


def set_delivery_note_expense_account(doc, method=None):
	"""Delivery Note.validate hook: rows billed in advance clear SBND, not COGS."""
	config = get_company_config(doc.company)
	sbnd_account = config.get(ACCOUNT_FIELD)

	if not (cint(config.get(ENABLE_FIELD)) and sbnd_account):
		return

	for item in doc.get("items"):
		if get_frozen_rate(item):
			item.expense_account = sbnd_account


def get_frozen_rate(dn_item) -> float:
	"""The rate the invoice froze for the row this delivery row is fulfilling."""
	if not dn_item.get("si_detail"):
		return 0.0

	return flt(frappe.db.get_value("Sales Invoice Item", dn_item.si_detail, RATE_FIELD))


def get_variance_gl_entries(doc) -> list:
	"""Delivery Note side: post the frozen-vs-actual difference to COGS.

	The core stock GL already debited SBND with the *real* stock value, while
	the invoice credited it with the frozen estimate. Whatever is left in SBND
	for this row is the estimate error, and it belongs in COGS.
	"""
	config = get_company_config(doc.company)
	sbnd_account = config.get(ACCOUNT_FIELD)

	if not (cint(config.get(ENABLE_FIELD)) and sbnd_account):
		return []

	if not cint(erpnext.is_perpetual_inventory_enabled(doc.company)):
		return []

	gl_entries = []
	for item in doc.get("items"):
		rate = get_frozen_rate(item)
		if not rate or item.expense_account != sbnd_account:
			continue

		frozen_amount = flt(rate * flt(item.get("stock_qty")), doc.precision("base_net_total"))

		stock_value_difference = frappe.db.get_value(
			"Stock Ledger Entry",
			{
				"voucher_no": doc.name,
				"voucher_detail_no": item.name,
				"item_code": item.item_code,
				"is_cancelled": 0,
			},
			"stock_value_difference",
		)
		# core debits SBND with -svd (an outgoing delivery carries a negative svd)
		actual_amount = flt(-1 * flt(stock_value_difference), doc.precision("base_net_total"))

		variance = flt(frozen_amount - actual_amount, doc.precision("base_net_total"))
		if not variance:
			continue

		cogs_account = resolve_cogs_account(doc, item, sbnd_account)
		if not cogs_account or cogs_account == sbnd_account:
			continue

		cost_center = item.get("cost_center") or doc.get("cost_center")

		# variance > 0 means the invoice over-estimated the cost: give it back to COGS
		gl_entries.append(
			doc.get_gl_dict(
				{
					"account": sbnd_account,
					"against": cogs_account,
					"debit": variance if variance > 0 else 0,
					"debit_in_account_currency": variance if variance > 0 else 0,
					"credit": -variance if variance < 0 else 0,
					"credit_in_account_currency": -variance if variance < 0 else 0,
					"cost_center": cost_center,
					"project": item.get("project") or doc.get("project"),
					"remarks": _("Stock billed but not delivered, cleared on delivery"),
				},
				get_account_currency(sbnd_account),
				item=item,
			)
		)
		gl_entries.append(
			doc.get_gl_dict(
				{
					"account": cogs_account,
					"against": sbnd_account,
					"credit": variance if variance > 0 else 0,
					"credit_in_account_currency": variance if variance > 0 else 0,
					"debit": -variance if variance < 0 else 0,
					"debit_in_account_currency": -variance if variance < 0 else 0,
					"cost_center": cost_center,
					"project": item.get("project") or doc.get("project"),
					"remarks": _("Cost of goods adjusted to actual on delivery"),
				},
				get_account_currency(cogs_account),
				item=item,
			)
		)

	return gl_entries


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------


@frappe.whitelist()
def create_sbnd_account(
	company: str, account_name: str = "Stock Billed But Not Delivered", parent_account=None
) -> str:
	"""Create (or return) the SBND account for a company, under current liabilities.

	The balance is what the company owes its customers in goods, so it sits on
	the liability side — the mirror of SDBNB, which is an asset.
	"""
	frappe.has_permission("Account", "create", throw=True)

	from vansale.sf_trading.stock_billing_setup import ensure_account_type_options

	ensure_account_type_options()

	abbr = frappe.get_cached_value("Company", company, "abbr")
	name = account_name + " - " + abbr

	if frappe.db.exists("Account", name):
		if frappe.db.get_value("Account", name, "account_type") != SBND_ACCOUNT_TYPE:
			frappe.db.set_value("Account", name, "account_type", SBND_ACCOUNT_TYPE)
		return name

	parent_account = parent_account or get_liability_parent(company)
	if not parent_account:
		frappe.throw(_("Could not find a group account under Liabilities for company {0}").format(company))

	account = frappe.get_doc(
		{
			"doctype": "Account",
			"account_name": account_name,
			"parent_account": parent_account,
			"company": company,
			"account_type": SBND_ACCOUNT_TYPE,
			"root_type": "Liability",
			"is_group": 0,
		}
	).insert()

	return account.name


def get_liability_parent(company: str):
	for candidate in ("Current Liabilities", "Accounts Payable", "Liabilities"):
		parent = frappe.db.get_value(
			"Account", {"company": company, "account_name": candidate, "is_group": 1}, "name"
		)
		if parent:
			return parent

	return frappe.db.get_value(
		"Account",
		{"company": company, "root_type": "Liability", "is_group": 1, "parent_account": ["!=", ""]},
		"name",
	)


def ensure_custom_fields():
	depends_on = "eval:doc." + ENABLE_FIELD

	create_custom_fields(
		{
			"Company": [
				{
					"fieldname": ENABLE_FIELD,
					"label": "Enable Stock Billed But Not Delivered",
					"fieldtype": "Check",
					"default": "0",
					"insert_after": "custom_disable_sdbnb_in_sr",
					"description": (
						"If enabled, an invoice raised before delivery recognises the cost against "
						"the Stock Billed But Not Delivered account, which the delivery then clears."
					),
				},
				{
					"fieldname": ACCOUNT_FIELD,
					"label": "Stock Billed But Not Delivered",
					"fieldtype": "Link",
					"options": "Account",
					"insert_after": ENABLE_FIELD,
					"depends_on": depends_on,
					"mandatory_depends_on": depends_on,
					"ignore_user_permissions": 1,
					"no_copy": 1,
				},
			],
			"Sales Invoice Item": [
				{
					"fieldname": RATE_FIELD,
					"label": "SBND Valuation Rate",
					"fieldtype": "Currency",
					"options": "Company:company:default_currency",
					# valuation precision, not currency precision — at BHD's 3 decimals
					# a cheap item's rate rounds enough to manufacture a variance on
					# every single line
					"precision": "9",
					"insert_after": "expense_account",
					"read_only": 1,
					"no_copy": 1,
					"print_hide": 1,
					"description": (
						"Valuation rate frozen when the invoice was submitted ahead of delivery, "
						"kept so a repost reproduces the same cost."
					),
				}
			],
		},
		ignore_validate=True,
	)
