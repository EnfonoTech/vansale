# apps/vansale/vansale/sf_trading/api/test_payment_advice_workflow.py
"""Tests for the Payment Advice PM Workflow definition.

setup_workflow() commits, so it is not executed here — a test that commits would survive the
per-test rollback and leave a workflow on the site. What is tested is the definition itself
(the part that can be wrong) and the integration switch that makes the advice's own approver
rule stand down.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from vansale.sf_trading.api.payment_advice_workflow import (
	DOCTYPE,
	FINANCE_ROLES,
	PREPARER_ROLES,
	ROLE_APPROVER,
	ROLE_HO_ACCOUNTS,
	ROLE_PURCHASE_MANAGER,
	ROUTE_ENTRY_STATE,
	STATE_APPROVED,
	STATE_DRAFT,
	STATE_PENDING_ACCOUNTANT,
	STATE_PENDING_FINANCE,
	STATE_PENDING_HO,
	STATE_PENDING_PURCHASE,
	STATE_REJECTED,
	WORKFLOW_NAME,
	_states,
	_transitions,
	has_active_workflow,
	pm_workflow_available,
	route_readiness,
	workflow_status,
)


class TestPaymentAdviceWorkflowDefinition(FrappeTestCase):
	def test_states_cover_the_lifecycle(self):
		states = {s["state"] for s in _states("X")}
		self.assertEqual(
			states,
			{
				STATE_DRAFT,
				STATE_PENDING_PURCHASE,
				STATE_PENDING_HO,
				STATE_PENDING_FINANCE,
				STATE_PENDING_ACCOUNTANT,
				STATE_APPROVED,
				STATE_REJECTED,
			},
		)

	def test_only_approved_is_submitted(self):
		for state in _states("X"):
			expected = "1" if state["state"] == STATE_APPROVED else "0"
			self.assertEqual(state["doc_status"], expected, state["state"])

	def test_every_transition_targets_a_declared_state(self):
		declared = {s["state"] for s in _states("X")}
		for transition in _transitions("X"):
			self.assertIn(transition["state"], declared)
			self.assertIn(transition["next_state"], declared)

	def test_rejection_is_recoverable_on_every_route(self):
		"""A rejected advice must have a way back on each route, or work dies there."""
		out_of_rejected = [t for t in _transitions("X") if t["state"] == STATE_REJECTED]
		self.assertTrue(out_of_rejected)
		self.assertEqual(
			{t["next_state"] for t in out_of_rejected}, set(ROUTE_ENTRY_STATE.values())
		)

	def test_every_route_leaves_draft(self):
		out_of_draft = [t for t in _transitions("X") if t["state"] == STATE_DRAFT]
		self.assertEqual({t["next_state"] for t in out_of_draft}, set(ROUTE_ENTRY_STATE.values()))
		for route, entry in ROUTE_ENTRY_STATE.items():
			matching = [t for t in out_of_draft if t["next_state"] == entry]
			self.assertTrue(matching, route)
			for transition in matching:
				# the condition is the only thing that keeps the four routes apart
				self.assertEqual(transition["condition"], 'doc.approval_route == "%s"' % route)

	def test_both_preparer_roles_can_raise_every_route(self):
		out_of_draft = [t for t in _transitions("X") if t["state"] == STATE_DRAFT]
		for entry in ROUTE_ENTRY_STATE.values():
			roles = {t["allowed"] for t in out_of_draft if t["next_state"] == entry}
			self.assertEqual(roles, set(PREPARER_ROLES), entry)

	def test_each_route_reaches_the_accountant(self):
		"""Walk every route to the end: no state may be a dead end short of Approved."""
		steps = {}
		for t in _transitions("X"):
			if t["action"] == "Approve":
				steps.setdefault(t["state"], set()).add(t["next_state"])

		for entry in ROUTE_ENTRY_STATE.values():
			state, seen = entry, set()
			while state != STATE_APPROVED:
				self.assertIn(state, steps, "%s is a dead end" % state)
				self.assertNotIn(state, seen, "loop at %s" % state)
				seen.add(state)
				state = sorted(steps[state])[0]
			self.assertEqual(state, STATE_APPROVED)

	def test_the_second_approval_takes_either_finance_role(self):
		finance = [
			t for t in _transitions("X")
			if t["state"] == STATE_PENDING_FINANCE and t["action"] == "Approve"
		]
		self.assertEqual({t["allowed"] for t in finance}, set(FINANCE_ROLES))
		for t in finance:
			self.assertEqual(t["next_state"], STATE_PENDING_ACCOUNTANT)

	def test_first_approvals_hand_over_to_finance(self):
		for state, role in ((STATE_PENDING_PURCHASE, ROLE_PURCHASE_MANAGER),
		                    (STATE_PENDING_HO, ROLE_HO_ACCOUNTS)):
			step = next(t for t in _transitions("X") if t["state"] == state and t["action"] == "Approve")
			self.assertEqual(step["allowed"], role)
			self.assertEqual(step["next_state"], STATE_PENDING_FINANCE)

	def test_only_the_accountant_submits(self):
		submitting = [t for t in _transitions("X") if t["next_state"] == STATE_APPROVED]
		self.assertEqual(len(submitting), 1)
		self.assertEqual(submitting[0]["allowed"], ROLE_APPROVER)
		self.assertEqual(submitting[0]["state"], STATE_PENDING_ACCOUNTANT)

	def test_every_pending_state_can_be_rejected(self):
		rejectable = {t["state"] for t in _transitions("X") if t["action"] == "Reject"}
		self.assertEqual(
			rejectable,
			{STATE_PENDING_PURCHASE, STATE_PENDING_HO, STATE_PENDING_FINANCE, STATE_PENDING_ACCOUNTANT},
		)

	def test_conditions_stay_within_safe_eval(self):
		"""PM Workflow evaluates conditions with almost no globals — a call would raise."""
		for transition in _transitions("X"):
			condition = transition.get("condition")
			if not condition:
				continue
			self.assertNotIn("(", condition, condition)
			self.assertTrue(condition.startswith("doc.approval_route =="), condition)

	def test_the_initiator_attaches_the_paperwork(self):
		"""The raiser holds the slip; approvers have nothing new to attach."""
		raising = [t for t in _transitions("X") if t["action"] == "Send for Approval"]
		self.assertTrue(raising)
		for transition in raising:
			self.assertTrue(transition.get("require_attachment"), transition["next_state"])
		for transition in [t for t in _transitions("X") if t["action"] == "Approve"]:
			self.assertFalse(transition.get("require_attachment"), transition["state"])
		for reject in [t for t in _transitions("X") if t["action"] == "Reject"]:
			self.assertTrue(reject.get("require_comment"))
			self.assertTrue(reject.get("is_return_for_correction"))

	def test_approver_is_not_a_preparer_role(self):
		"""Separation of duties: the roles that raise must not be the role that releases."""
		self.assertNotIn(ROLE_APPROVER, PREPARER_ROLES)

	def test_only_submission_steps_allow_self_approval(self):
		for transition in _transitions("X"):
			if transition["action"] == "Approve":
				self.assertFalse(transition.get("allow_self_approval"))

	def test_preparer_and_approval_roles_exist_on_this_site(self):
		for role in list(PREPARER_ROLES) + [ROLE_PURCHASE_MANAGER, ROLE_HO_ACCOUNTS] + list(FINANCE_ROLES):
			self.assertTrue(frappe.db.exists("Role", role), role)

	def test_readiness_reports_unstaffed_roles(self):
		"""A role nobody holds strands documents; the check has to say so, not hide it."""
		readiness = route_readiness()
		self.assertIn("ready", readiness)
		self.assertIn("unstaffed_roles", readiness)
		self.assertIsInstance(readiness["holders"], dict)

	def test_workflow_state_field_exists_on_payment_advice(self):
		"""PM Workflow writes into this field; without it the engine has nowhere to store state."""
		meta = frappe.get_meta(DOCTYPE)
		self.assertTrue(meta.has_field("workflow_state"))
		self.assertTrue(meta.get_field("workflow_state").allow_on_submit)


class TestWorkflowIntegration(FrappeTestCase):
	def test_availability_matches_permission_manager(self):
		self.assertEqual(pm_workflow_available(), bool(frappe.db.exists("DocType", "PM Workflow")))

	def test_has_active_workflow_returns_bool(self):
		self.assertIsInstance(has_active_workflow(), bool)

	def test_status_payload_shape(self):
		status = workflow_status()
		self.assertIn("available", status)
		self.assertIn("active", status)

	def test_approver_rule_stands_down_when_workflow_active(self):
		"""The advice's single-approver rule must yield to the workflow, not fight it."""
		from vansale.sf_trading.doctype.payment_advice import payment_advice as pa

		advice = frappe.new_doc("Payment Advice")
		advice.company = frappe.db.get_value("Company", {}, "name")
		advice.approver = None  # would normally be fatal at submit

		original = pa.workflow_controls_submission
		try:
			pa.workflow_controls_submission = lambda company=None: True
			advice.validate_approver()  # must not raise
		finally:
			pa.workflow_controls_submission = original

	def test_approver_rule_still_applies_without_a_workflow(self):
		from vansale.sf_trading.doctype.payment_advice import payment_advice as pa

		advice = frappe.new_doc("Payment Advice")
		advice.company = frappe.db.get_value("Company", {}, "name")
		advice.approver = None

		original = pa.workflow_controls_submission
		try:
			pa.workflow_controls_submission = lambda company=None: False
			with self.assertRaises(frappe.ValidationError):
				advice.validate_approver()
		finally:
			pa.workflow_controls_submission = original

	def test_workflow_name_is_stable(self):
		"""The name is the idempotency key for setup_workflow; changing it would duplicate."""
		self.assertEqual(WORKFLOW_NAME, "Payment Advice Approval")
