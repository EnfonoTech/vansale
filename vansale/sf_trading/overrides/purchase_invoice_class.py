import frappe
from frappe import _
from frappe.utils import flt

from erpnext.accounts.doctype.purchase_invoice.purchase_invoice import PurchaseInvoice
from erpnext.controllers.taxes_and_totals import calculate_taxes_and_totals


class SFPurchaseTaxesAndTotals(calculate_taxes_and_totals):
	"""Core's calculator, with one correction to the multi-currency advance cap."""

	def calculate_total_advance(self):
		"""Cap the advance at the invoice's own base total, not a re-conversion.

		Core (taxes_and_totals.py:846) caps a multi-currency advance at
		``grand_total * conversion_rate`` -- one multiplication, rounded once. But
		``base_grand_total`` is the sum of the per-line base amounts, each already
		rounded to the company currency's precision, so the two disagree by fils.
		On steelforce they differ on 9 of 17 foreign-currency invoices.

		Everything else works off ``base_grand_total``: the GL entries, the Payment
		Entry allocation, and ``calculate_outstanding_amount()`` itself -- core
		reads it at taxes_and_totals.py:926, three lines after the cap it
		contradicts. So an advance that exactly pays the invoice can exceed a cap
		nothing else agrees with, and the invoice can never be submitted
		(20020000139: advance 6,561.168 against a cap of 6,561.167).

		Only the comparison moves. A genuine over-allocation still throws, and the
		single-currency path is core's, untouched.
		"""
		doc = self.doc

		if doc.docstatus.is_cancelled():
			return

		if doc.party_account_currency == doc.currency:
			# no conversion, so core's cap is the grand total itself -- exact
			return super().calculate_total_advance()

		total_allocated_amount = sum(
			flt(adv.allocated_amount, adv.precision("allocated_amount"))
			for adv in doc.get("advances")
		)
		doc.total_advance = flt(total_allocated_amount, doc.precision("total_advance"))

		base_write_off_amount = flt(
			flt(doc.write_off_amount) * doc.conversion_rate,
			doc.precision("base_write_off_amount"),
		)
		# the same expression calculate_outstanding_amount() uses, so the cap and
		# the outstanding are computed off identical inputs
		invoice_total = (
			flt(doc.base_rounded_total or doc.base_grand_total, doc.precision("base_grand_total"))
			- base_write_off_amount
		)

		if invoice_total > 0 and doc.total_advance > invoice_total:
			frappe.throw(
				_("Advance amount cannot be greater than {0} {1}").format(
					doc.party_account_currency, invoice_total
				)
			)

		if doc.get("write_off_outstanding_amount_automatically"):
			doc.write_off_amount = 0

		self.calculate_outstanding_amount()
		self.calculate_write_off_amount()


class CustomPurchaseInvoice(PurchaseInvoice):
	def calculate_taxes_and_totals(self):
		"""Run core's calculation through the subclassed calculator.

		``AccountsController.calculate_taxes_and_totals`` builds the calculator --
		its ``__init__`` does all the work -- and then runs commission and
		contribution for selling doctypes only, which is a no-op here. So this is
		the whole of core's method for a Purchase Invoice.

		``test_advance_cap.test_core_tail_stays_selling_only`` fails if a future
		erpnext adds Purchase Invoice work to that tail.
		"""
		SFPurchaseTaxesAndTotals(self)
