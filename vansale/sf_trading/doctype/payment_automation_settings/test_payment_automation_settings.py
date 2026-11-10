# apps/vansale/vansale/sf_trading/doctype/payment_automation_settings/test_payment_automation_settings.py
"""Tests for Payment Automation Settings and the scheduling gate.

The engine moves money at step 4, so the guards are tested harder than the happy path:
a configuration that skips a step, lacks an approver, or names no weekday must be refused
before it can ever run.
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, now_datetime, nowdate

from vansale.sf_trading.api.payment_automation import is_due
from vansale.sf_trading.doctype.payment_automation_settings.payment_automation_settings import (
	WEEKDAYS,
)


class TestPaymentAutomationSettings(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = frappe.db.get_single_value("Global Defaults", "default_company") or frappe.db.get_value(
			"Company", {}, "name"
		)

	def _settings(self, **kw):
		doc = frappe.new_doc("Payment Automation Settings")
		doc.update(
			{
				"company": self.company,
				"party_type": "Supplier",
				"enabled": 0,
				"auto_create_advice": 1,
				"processing_time": "07:00:00",
				"minimum_amount": 1,
				"max_parties_per_run": 25,
			}
		)
		for day in WEEKDAYS:
			doc.set("automate_on_" + day, 1)
		doc.update(kw)
		return doc

	# ── level chain ──────────────────────────────────────────────────────────────
	def test_submit_advice_needs_create_advice(self):
		doc = self._settings(auto_create_advice=0, auto_submit_advice=1)
		with self.assertRaises(frappe.ValidationError):
			doc.validate_level_chain()

	def test_create_pe_needs_submitted_advice(self):
		doc = self._settings(auto_submit_advice=0, auto_create_payment_entry=1)
		with self.assertRaises(frappe.ValidationError):
			doc.validate_level_chain()

	def test_submit_pe_needs_create_pe(self):
		doc = self._settings(
			auto_submit_advice=1, auto_create_payment_entry=0, auto_submit_payment_entry=1
		)
		with self.assertRaises(frappe.ValidationError):
			doc.validate_level_chain()

	def test_submit_advice_needs_approver(self):
		"""Without an approver the advice's own before_submit would throw mid-run."""
		doc = self._settings(auto_submit_advice=1, approver=None)
		with self.assertRaises(frappe.ValidationError):
			doc.validate_level_chain()

	def test_full_chain_with_approver_is_valid(self):
		# the approver is a User now, not an Employee with a User ID hanging off it
		doc = self._settings(
			auto_submit_advice=1,
			auto_create_payment_entry=1,
			auto_submit_payment_entry=1,
			approver="Administrator",
			mode_of_payment=frappe.db.get_value("Mode of Payment", {}, "name"),
		)
		doc.validate_level_chain()  # must not raise
		self.assertEqual(doc.highest_enabled_step(), 4)

	def test_disabled_approver_is_rejected(self):
		"""A disabled user could be stamped and then nobody could submit those advices."""
		user = frappe.db.get_value("User", {"enabled": 0, "name": ["!=", "Guest"]}, "name")
		if not user:
			self.skipTest("no disabled user on this site")
		doc = self._settings(auto_submit_advice=1, approver=user)
		with self.assertRaises(frappe.ValidationError):
			doc.validate_level_chain()

	# ── schedule ─────────────────────────────────────────────────────────────────
	def test_enabled_needs_a_weekday(self):
		doc = self._settings(enabled=1)
		for day in WEEKDAYS:
			doc.set("automate_on_" + day, 0)
		with self.assertRaises(frappe.ValidationError):
			doc.validate_schedule()

	def test_enabled_needs_processing_time(self):
		doc = self._settings(enabled=1, processing_time=None)
		with self.assertRaises(frappe.ValidationError):
			doc.validate_schedule()

	def test_disabled_skips_schedule_checks(self):
		doc = self._settings(enabled=0, processing_time=None)
		doc.validate_schedule()  # must not raise

	def test_runs_today_reads_the_weekday_flag(self):
		doc = self._settings()
		doc.automate_on_monday = 0
		self.assertFalse(doc.runs_today("Monday"))
		self.assertTrue(doc.runs_today("Tuesday"))

	# ── thresholds ───────────────────────────────────────────────────────────────
	def test_negative_minimum_rejected(self):
		doc = self._settings(minimum_amount=-1)
		with self.assertRaises(frappe.ValidationError):
			doc.validate_thresholds()

	def test_zero_cap_rejected(self):
		doc = self._settings(max_parties_per_run=0)
		with self.assertRaises(frappe.ValidationError):
			doc.validate_thresholds()

	def test_minimum_above_ceiling_rejected(self):
		"""Otherwise every party is skipped and the run silently does nothing."""
		doc = self._settings(minimum_amount=500, advice_threshold=100)
		with self.assertRaises(frappe.ValidationError):
			doc.validate_thresholds()

	# ── steps ────────────────────────────────────────────────────────────────────
	def test_highest_enabled_step(self):
		self.assertEqual(self._settings(auto_create_advice=0).highest_enabled_step(), 0)
		self.assertEqual(self._settings().highest_enabled_step(), 1)
		self.assertEqual(self._settings(auto_submit_advice=1).highest_enabled_step(), 2)


class TestScheduleGate(FrappeTestCase):
	"""is_due() is the fence that stops an `all` tick running a configuration repeatedly."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = frappe.db.get_single_value("Global Defaults", "default_company") or frappe.db.get_value(
			"Company", {}, "name"
		)

	def _saved(self, **kw):
		doc = frappe.new_doc("Payment Automation Settings")
		doc.update(
			{
				"company": self.company,
				"party_type": "Supplier",
				"enabled": 1,
				"auto_create_advice": 1,
				"processing_time": "00:01:00",
				"minimum_amount": 1,
				"max_parties_per_run": 5,
				"title": "test-gate",
			}
		)
		for day in WEEKDAYS:
			doc.set("automate_on_" + day, 1)
		doc.update(kw)
		doc.insert(ignore_permissions=True)
		self.addCleanup(lambda: frappe.delete_doc("Payment Automation Settings", doc.name, force=True))
		return doc

	def test_due_when_time_passed_and_never_run(self):
		doc = self._saved()
		self.assertTrue(is_due(doc.name))

	def test_not_due_when_already_run_today(self):
		doc = self._saved()
		frappe.db.set_value(
			"Payment Automation Settings", doc.name, "last_execution", now_datetime(),
			update_modified=False,
		)
		self.assertFalse(is_due(doc.name))

	def test_due_again_the_next_day(self):
		doc = self._saved()
		frappe.db.set_value(
			"Payment Automation Settings", doc.name, "last_execution", add_days(nowdate(), -1),
			update_modified=False,
		)
		self.assertTrue(is_due(doc.name))

	def test_not_due_before_processing_time(self):
		doc = self._saved(processing_time="23:59:00")
		self.assertFalse(is_due(doc.name))

	def test_not_due_when_disabled(self):
		doc = self._saved()
		frappe.db.set_value("Payment Automation Settings", doc.name, "enabled", 0, update_modified=False)
		self.assertFalse(is_due(doc.name))

	def test_not_due_when_no_step_enabled(self):
		doc = self._saved()
		frappe.db.set_value(
			"Payment Automation Settings", doc.name, "auto_create_advice", 0, update_modified=False
		)
		self.assertFalse(is_due(doc.name))

	def test_not_due_on_an_unselected_weekday(self):
		doc = self._saved()
		today = now_datetime().strftime("%A").lower()
		frappe.db.set_value(
			"Payment Automation Settings", doc.name, "automate_on_" + today, 0, update_modified=False
		)
		self.assertFalse(is_due(doc.name))
