from erpnext.stock.doctype.delivery_note.delivery_note import DeliveryNote

from vansale.sf_trading.sbnd import get_variance_gl_entries, is_sbnd_account
from vansale.sf_trading.sdbnb import is_sdbnb_account


class CustomDeliveryNote(DeliveryNote):
	def check_expense_account(self, item):
		"""Let a Delivery Note book its cost to a balance-sheet holding account.

		v15's stock controller insists a Delivery Note's expense account is a
		Profit or Loss account. Stock Delivered But Not Billed is deliberately an
		asset account and Stock Billed But Not Delivered a liability one, so that
		rule has to stand aside for them — upstream goes further and switches P&L
		enforcement off for every Delivery Note row on develop. Here it stands
		aside only for those two account types, so every other misconfiguration is
		still caught.
		"""
		account = item.get("expense_account")
		if account and (is_sdbnb_account(account) or is_sbnd_account(account)):
			return

		super().check_expense_account(item)

	def get_gl_entries(self, warehouse_account=None, default_expense_account=None, default_cost_center=None):
		"""Core entries, plus the estimate correction for pre-billed rows.

		A row billed before delivery had its cost frozen on the invoice; core has
		just posted the real stock value against the same account, so the leftover
		is the estimate error and it belongs in COGS.
		"""
		gl_entries = super().get_gl_entries(
			warehouse_account=warehouse_account,
			default_expense_account=default_expense_account,
			default_cost_center=default_cost_center,
		)

		variance_entries = get_variance_gl_entries(self)
		if variance_entries:
			self.set_transaction_currency_and_rate_in_gl_map(variance_entries)
			gl_entries.extend(variance_entries)

		return gl_entries
