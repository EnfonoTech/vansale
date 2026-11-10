import inspect

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt

from erpnext.controllers.accounts_controller import AccountsController

from vansale.sf_trading.overrides.purchase_invoice_class import (
	CustomPurchaseInvoice,
	SFPurchaseTaxesAndTotals,
)


def _invoice(advances=(), **kwargs):
	"""A Purchase Invoice carrying the totals of 20020000139, never inserted.

	65,435.00 SAR at 0.10027. Summing the per-line base amounts gives a
	base_grand_total of 6,561.168; core's single multiplication gives 6,561.167.
	"""
	doc = frappe.new_doc("Purchase Invoice")
	doc.update(
		{
			"currency": "SAR",
			"party_account_currency": "BHD",
			"conversion_rate": 0.10027,
			"grand_total": 65435.00,
			"rounded_total": 0,
			"base_grand_total": 6561.168,
			"base_rounded_total": 0,
			"write_off_amount": 0,
			"base_write_off_amount": 0,
			"paid_amount": 0,
			"base_paid_amount": 0,
			"total_advance": 0,
			"outstanding_amount": 0,
			"is_return": 0,
		}
	)
	doc.update(kwargs)

	for amount in advances:
		doc.append(
			"advances",
			{
				"reference_type": "Payment Entry",
				"reference_name": "TEST-PE",
				"advance_amount": amount,
				"allocated_amount": amount,
			},
		)

	return doc


def _calculate_total_advance(doc):
	"""Just the capped step, without running the whole calculator over a stub."""
	calculator = SFPurchaseTaxesAndTotals.__new__(SFPurchaseTaxesAndTotals)
	calculator.doc = doc
	calculator.calculate_total_advance()
	return doc


class TestAdvanceCap(FrappeTestCase):
	def test_advance_equal_to_base_grand_total_is_allowed(self):
		"""The exact case that blocked 20020000139."""
		doc = _calculate_total_advance(_invoice(advances=[6561.168]))

		self.assertEqual(doc.total_advance, 6561.168)
		# and it settles the invoice completely, with no stray fils left behind
		self.assertEqual(doc.outstanding_amount, 0.0)

	def test_core_would_have_rejected_the_same_advance(self):
		"""Guard the premise: core's cap really is a fil lower."""
		doc = _invoice(advances=[6561.168])
		core_cap = flt(flt(doc.grand_total) * flt(doc.conversion_rate), 3)

		self.assertEqual(core_cap, 6561.167)
		self.assertLess(core_cap, doc.base_grand_total)

	def test_over_by_one_fil_still_throws(self):
		"""The cap moved; it did not disappear."""
		self.assertRaises(
			frappe.ValidationError, _calculate_total_advance, _invoice(advances=[6561.169])
		)

	def test_genuine_over_allocation_still_throws(self):
		self.assertRaises(
			frappe.ValidationError, _calculate_total_advance, _invoice(advances=[7000.0])
		)

	def test_partial_advance_leaves_the_balance_outstanding(self):
		doc = _calculate_total_advance(_invoice(advances=[1000.0]))

		self.assertEqual(doc.total_advance, 1000.0)
		self.assertEqual(doc.outstanding_amount, 5561.168)

	def test_write_off_lowers_the_cap(self):
		# 100 SAR written off is 10.027 BHD, so the cap drops to 6,551.141
		self.assertRaises(
			frappe.ValidationError,
			_calculate_total_advance,
			_invoice(write_off_amount=100.0, advances=[6551.148]),
		)

	def test_single_currency_delegates_to_core(self):
		doc = _calculate_total_advance(
			_invoice(
				advances=[6561.168],
				currency="BHD",
				party_account_currency="BHD",
				conversion_rate=1.0,
				grand_total=6561.168,
			)
		)

		self.assertEqual(doc.total_advance, 6561.168)
		self.assertEqual(doc.outstanding_amount, 0.0)

	def test_single_currency_over_allocation_still_throws(self):
		self.assertRaises(
			frappe.ValidationError,
			_calculate_total_advance,
			_invoice(
				advances=[6600.0],
				currency="BHD",
				party_account_currency="BHD",
				conversion_rate=1.0,
				grand_total=6561.168,
			),
		)

	def test_cancelled_invoice_is_left_alone(self):
		doc = _invoice(advances=[99999.0])
		doc.docstatus = 2

		self.assertFalse(flt(_calculate_total_advance(doc).total_advance))

	def test_core_tail_stays_selling_only(self):
		"""CustomPurchaseInvoice.calculate_taxes_and_totals replaces core's method.

		Core's version only does extra work for selling doctypes. If an upgrade
		adds Purchase Invoice work to it, the override has to be revisited.
		"""
		source = inspect.getsource(AccountsController.calculate_taxes_and_totals)

		self.assertNotIn("Purchase Invoice", source)

	def test_override_is_wired_for_purchase_invoice(self):
		from frappe.model.base_document import get_controller

		self.assertTrue(issubclass(get_controller("Purchase Invoice"), CustomPurchaseInvoice))
