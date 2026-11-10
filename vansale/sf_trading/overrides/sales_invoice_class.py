from erpnext.accounts.doctype.sales_invoice.sales_invoice import SalesInvoice

from vansale.sf_trading.sbnd import get_sbnd_gl_entries
from vansale.sf_trading.sdbnb import get_sdbnb_gl_entries


class CustomSalesInvoice(SalesInvoice):
	def check_credit_limit(self):
		if self.get("custom_payment_mode") == "Cash":
			return
		super().check_credit_limit()

	def get_gl_entries(self, warehouse_account=None):
		"""Core entries, plus whichever stock-timing account this invoice touches.

		Billing a Delivery Note that parked its cost in SDBNB credits that account
		and debits COGS. Invoicing ahead of delivery does the opposite: debits COGS
		and credits SBND, at the rate frozen on the row. Done here rather than in an
		on_submit hook so a Repost Accounting Ledger rebuilds the same entries.
		"""
		gl_entries = super().get_gl_entries(warehouse_account=warehouse_account)

		extra_entries = get_sdbnb_gl_entries(self) + get_sbnd_gl_entries(self)
		if extra_entries:
			# core runs this over its own map before returning; ours needs it too
			self.set_transaction_currency_and_rate_in_gl_map(extra_entries)
			gl_entries.extend(extra_entries)

		return gl_entries
