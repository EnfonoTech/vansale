"""
Party account automation + Title Case for Customer / Supplier.

Hooked via doc_events in hooks.py:
  Customer → validate     → apply_title_case
  Customer → before_save  → create_customer_receivable_account
  Supplier → validate     → apply_title_case
  Supplier → before_save  → create_supplier_payable_account

Customer: for every Credit Limit row with credit_limit > 0, creates a
Receivable ledger named after the customer under the parent of that row's
company's Default Receivable Account, and links it into the customer's
Default Accounts child table (Party Account) so Sales Invoices use it as
the receivable (debit_to) account.

Supplier: on every save (no credit-limit condition), creates a Payable
ledger under the parent of the default company's Default Payable Account
and links it the same way.

No explicit commits — everything stays in the party's save transaction,
so a failed save rolls the new account back too.
"""

import frappe
from frappe import _
from frappe.utils import flt


# ── Title Case ────────────────────────────────────────────────────────────────

def apply_title_case(doc, method=None):
	"""Enforce Title Case on the customer / supplier name on every save."""
	if doc.doctype == "Customer" and doc.customer_name:
		doc.customer_name = doc.customer_name.strip().title()
	elif doc.doctype == "Supplier" and doc.supplier_name:
		doc.supplier_name = doc.supplier_name.strip().title()


# ── Account auto-creation ─────────────────────────────────────────────────────

def create_customer_receivable_account(doc, method=None):
	"""Receivable ledger per Credit Limit row's company (credit_limit > 0 only)."""
	for row in doc.credit_limits or []:
		if flt(row.credit_limit) <= 0 or not row.company:
			continue
		account = _get_or_create_account(
			doc, row.company, "Receivable", "default_receivable_account"
		)
		if account:
			_link_party_account(doc, row.company, account)


def create_supplier_payable_account(doc, method=None):
	"""Payable ledger in the default company, on every Supplier save."""
	company = frappe.defaults.get_global_default("company")
	if not company:
		return
	account = _get_or_create_account(doc, company, "Payable", "default_payable_account")
	if account:
		_link_party_account(doc, company, account)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_or_create_account(doc, company, account_type, default_account_field):
	"""Return the party's ledger for company, creating it if needed."""
	party_name = (doc.get("customer_name") or doc.get("supplier_name") or doc.name).strip()

	existing = frappe.db.get_value(
		"Account", {"account_name": party_name, "company": company}, "name"
	)
	if existing:
		return existing

	default_account = frappe.db.get_value("Company", company, default_account_field)
	parent_account = default_account and frappe.db.get_value(
		"Account", default_account, "parent_account"
	)
	if not parent_account:
		frappe.msgprint(
			_(
				"Company {0} has no Default {1} Account set, so no {1} ledger was "
				"created for {2}. Set it in the Company master."
			).format(frappe.bold(company), _(account_type), frappe.bold(party_name)),
			indicator="orange",
		)
		return None

	currency = doc.get("default_currency") or frappe.db.get_value(
		"Company", company, "default_currency"
	)

	account = frappe.get_doc(
		{
			"doctype": "Account",
			"account_name": party_name,
			"parent_account": parent_account,
			"account_type": account_type,
			"account_currency": currency,
			"company": company,
			"is_group": 0,
		}
	)
	account.flags.ignore_permissions = True
	account.insert(ignore_permissions=True)
	return account.name


def _link_party_account(doc, company, account):
	"""Ensure the party's Default Accounts child table has this company → account row."""
	for row in doc.accounts or []:
		if row.company == company:
			if not row.account:
				row.account = account
			return
	doc.append("accounts", {"company": company, "account": account})
