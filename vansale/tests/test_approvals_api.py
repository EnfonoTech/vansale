"""Approvals endpoints (`vansale.steelforce.approvals`) without a site and
without `permission_manager` (PM): every PM call goes through `approvals._pm()`,
which these tests replace, and every database read is a stub that answers from
a table the test writes down (an unexpected read fails the test).

Run: cd ~/frappe-bench/sites && PYTHONPATH=$HOME/dev/vansale \
     ../env/bin/python -m unittest vansale.tests.test_approvals_api -v
"""

from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import MagicMock, patch, sentinel

import frappe
import pymysql
from frappe.query_builder import get_query_builder
from frappe.query_builder.utils import patch_query_execute

from vansale.steelforce import approvals
from vansale.steelforce.approvals_rules import inbox_stats
from vansale.tests import _site_free


_MISSING = object()


def pm_item(name: str, **overrides) -> dict:
    """One item as PM's `get_my_pending_approvals()` returns it."""
    item = {
        "name": name,
        "doctype": "Sales Invoice",
        "transaction": "Sales Invoice",
        "transaction_filter": "Sales Invoice",
        "docname": f"DOC-{name}",
        "date": "10/11/26 09:30",
        "creation_iso": "2026-11-10T09:30:00",
        "priority": "Medium",
        "state": "Pending Approval",
        "role_id": "Finance Head",
        "holder": "",
        "days": 2,
        "creator": "Ali Hassan",
        "category": "Approval Pending",
        "available_actions": ["Approve", "Reject"],
        "doc_url": f"/app/sales-invoice/DOC-{name}",
        "is_adhoc": False,
        "adhoc_for": "",
        "return_to_originator": False,
        "is_waiting": False,
        "waiting_with": "",
    }
    item.update(overrides)
    return item


def pm_waiting(name: str, **overrides) -> dict:
    """An item forwarded away: no buttons, someone else holds it."""
    return pm_item(
        name,
        is_waiting=True,
        waiting_with="Fatima Noor",
        holder="Fatima Noor",
        available_actions=[],
        **overrides,
    )


def pm_pending(*items: dict, total: int | None = None) -> dict:
    """PM's answer: the items grouped by category in first-seen order."""
    groups: dict[str, list] = {}
    for item in items:
        groups.setdefault(item["category"], []).append(item)
    return {
        "total": len(items) if total is None else total,
        "groups": [{"label": label, "items": rows} for label, rows in groups.items()],
    }


def fake_reader(function: str, rows_by_doctype: dict[str, list[dict]]):
    """A stand-in for `frappe.get_all` / `frappe.get_list` (`function` names it
    in the failure message) that answers from `rows_by_doctype` and fails on any
    other doctype. `.calls` lists `(doctype, kwargs)` for every call."""
    calls: list = []

    def read(doctype, *args, **kwargs):
        calls.append((doctype, kwargs))
        if doctype not in rows_by_doctype:
            raise AssertionError(f"unexpected {function}({doctype!r}, {kwargs})")
        return [frappe._dict(row) for row in rows_by_doctype[doctype]]

    read.calls = calls
    return read


def meta_with(*fieldnames: str):
    """A stand-in for `frappe.get_meta(doctype)` that has these fields."""
    return types.SimpleNamespace(has_field=lambda fieldname: fieldname in fieldnames)


class SiteFreeCase(unittest.TestCase):
    def setUp(self):
        _site_free.setup_site_free()
        self.addCleanup(_site_free.teardown_site_free)

    def _patch(self, target: str, *args, **kwargs):
        patcher = patch(target, *args, **kwargs)
        mock = patcher.start()
        self.addCleanup(patcher.stop)
        return mock

    def _use_get_all(self, rows_by_doctype: dict[str, list[dict]]):
        get_all = fake_reader("get_all", rows_by_doctype)
        self._patch("frappe.get_all", get_all)
        return get_all

    def _use_get_list(self, rows_by_doctype: dict[str, list[dict]]):
        get_list = fake_reader("get_list", rows_by_doctype)
        self._patch("frappe.get_list", get_list)
        return get_list


class ApiCase(SiteFreeCase):
    """PM is installed (stubbed as `self.pm`); the three enrichment reads are
    stubbed to "nothing known" and any other `get_all` fails the test."""

    def setUp(self):
        super().setUp()
        self.available = self._patch("vansale.steelforce.approvals.is_available", return_value=True)
        self.pm = MagicMock(name="pm")
        self._patch("vansale.steelforce.approvals._pm", return_value=self.pm)
        self.party_amounts = self._patch("vansale.steelforce.approvals._party_amounts", return_value={})
        self.action_flags = self._patch("vansale.steelforce.approvals._action_flags", return_value={})
        self.get_all = self._use_get_all({})


# ─── availability ─────────────────────────────────────────────────────────────


class TestAvailability(SiteFreeCase):
    def test_available_when_pm_is_installed_and_its_table_exists(self):
        self._patch("frappe.get_installed_apps", return_value=["frappe", "permission_manager"])
        frappe.local.db.table_exists.return_value = True

        self.assertTrue(approvals.is_available())
        frappe.local.db.table_exists.assert_called_once_with("PM Workflow Action")

    def test_not_available_without_the_pm_app(self):
        self._patch("frappe.get_installed_apps", return_value=["frappe", "erpnext"])

        self.assertFalse(approvals.is_available())
        frappe.local.db.table_exists.assert_not_called()

    def test_not_available_while_the_action_table_is_missing(self):
        self._patch("frappe.get_installed_apps", return_value=["frappe", "permission_manager"])
        frappe.local.db.table_exists.return_value = False

        self.assertFalse(approvals.is_available())

    def test_availability_endpoint_says_whether_it_is_enabled(self):
        with patch.object(approvals, "is_available", return_value=True):
            self.assertEqual(approvals.availability(), {"enabled": True})
        with patch.object(approvals, "is_available", return_value=False):
            self.assertEqual(approvals.availability(), {"enabled": False})


class TestEndpointsAreWhitelistedGet(unittest.TestCase):
    def test_availability_inbox_and_count_answer_get_only(self):
        for function in (approvals.availability, approvals.inbox, approvals.count):
            with self.subTest(function=function.__name__):
                self.assertIn(function, frappe.whitelisted)
                self.assertEqual(frappe.allowed_http_methods_for_whitelisted_func[function], ["GET"])
                self.assertNotIn(function, frappe.guest_methods)


# ─── the PM wiring ────────────────────────────────────────────────────────────


def _module(name: str, **attrs) -> types.ModuleType:
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    return module


class TestPmNamespace(unittest.TestCase):
    def test_pm_imports_lazily_and_maps_every_callable(self):
        pm_approvals = _module(
            "approvals",
            get_my_pending_approvals=sentinel.pending,
            get_document_lifecycle=sentinel.lifecycle,
            get_sent_back_documents=sentinel.sent_back,
            get_my_approval_history=sentinel.history,
        )
        pm_workflow = _module(
            "workflow",
            get_transitions=sentinel.transitions,
            apply_workflow=sentinel.apply,
            has_approval_access=sentinel.access,
            get_open_return_adhoc_action=sentinel.open_return,
        )
        pm_actions = _module(
            "pm_workflow_action",
            forward_workflow_action=sentinel.forward,
            return_adhoc_to_originator=sentinel.return_adhoc,
            _can_act_on=sentinel.can_act,
        )
        modules = {
            "permission_manager.permission_manager.api": _module("api", approvals=pm_approvals),
            "permission_manager.permission_manager": _module("pm", workflow=pm_workflow),
            "permission_manager.permission_manager.doctype.pm_workflow_action": _module(
                "action", pm_workflow_action=pm_actions
            ),
        }

        with patch.dict(sys.modules, modules):
            pm = approvals._pm()

        self.assertEqual(
            vars(pm),
            {
                "get_my_pending_approvals": sentinel.pending,
                "get_transitions": sentinel.transitions,
                "apply_workflow": sentinel.apply,
                "has_approval_access": sentinel.access,
                "get_open_return_adhoc_action": sentinel.open_return,
                "get_document_lifecycle": sentinel.lifecycle,
                "forward_workflow_action": sentinel.forward,
                "return_adhoc_to_originator": sentinel.return_adhoc,
                "get_sent_back_documents": sentinel.sent_back,
                "get_my_approval_history": sentinel.history,
                "can_act_on": sentinel.can_act,
            },
        )


# ─── inbox and count ──────────────────────────────────────────────────────────


class TestInbox(ApiCase):
    def setUp(self):
        super().setUp()
        # Needs you: a (High, 40 days), b (Critical, 5), c (Low, 31).
        # Waiting on others: d (High, 50 days), e.
        self.a = pm_item("A", doctype="Sales Invoice", priority="High", days=40, category="Approval Pending")
        self.b = pm_item("B", doctype="Journal Entry", transaction="Journal Entry", priority="Critical", days=5,
                         category="Approval Pending")
        self.c = pm_item("C", doctype="Purchase Order", transaction="Purchase Order", priority="Low", days=31,
                         category="Decision Pending")
        self.d = pm_waiting("D", doctype="Sales Order", transaction="Sales Order", priority="High", days=50,
                            category="Approval Pending")
        self.e = pm_waiting("E", doctype="Quotation", transaction="Quotation", priority="Medium", days=1,
                            category="Decision Pending")
        self.pm.get_my_pending_approvals.return_value = pm_pending(self.a, self.b, self.c, self.d, self.e)

    def test_totals_split_between_needs_you_and_waiting(self):
        result = approvals.inbox()

        self.assertEqual(result["total"], 5)
        self.assertEqual(result["waiting"], 2)
        self.assertEqual(result["needs_you"], 3)
        self.assertEqual([i["action_id"] for i in result["waiting_items"]], ["D", "E"])
        self.assertTrue(all(i["is_waiting"] for i in result["waiting_items"]))

    def test_needs_you_items_are_grouped_by_category_in_pm_order(self):
        result = approvals.inbox()

        self.assertEqual(
            [(s["category"], [i["action_id"] for i in s["items"]]) for s in result["sections"]],
            [("Approval Pending", ["A", "B"]), ("Decision Pending", ["C"])],
        )

    def test_a_category_holding_only_waiting_items_makes_no_section(self):
        self.pm.get_my_pending_approvals.return_value = pm_pending(self.a, self.e)

        result = approvals.inbox()

        self.assertEqual([s["category"] for s in result["sections"]], ["Approval Pending"])
        self.assertEqual([i["action_id"] for i in result["waiting_items"]], ["E"])

    def test_stats_count_only_the_items_waiting_on_the_user(self):
        result = approvals.inbox()

        # d is High and 50 days old but waits on someone else.
        self.assertEqual(result["stats"], {"high": 2, "overdue": 2})
        self.assertEqual(result["stats"], inbox_stats([self.a, self.b, self.c]))

    def test_count_gives_the_same_numbers_without_building_items(self):
        result = approvals.count()

        self.assertEqual(result, {"total": 5, "needs_you": 3, "waiting": 2, "high": 2, "overdue": 2})
        self.party_amounts.assert_not_called()
        self.action_flags.assert_not_called()
        self.assertEqual(self.get_all.calls, [])

    def test_total_is_pms_own_total(self):
        self.pm.get_my_pending_approvals.return_value = pm_pending(self.a, self.d, total=9)

        self.assertEqual(approvals.count()["total"], 9)
        self.assertEqual(approvals.count()["needs_you"], 8)
        self.assertEqual(approvals.inbox()["total"], 9)

    def test_an_empty_pm_answer_is_an_empty_inbox(self):
        self.pm.get_my_pending_approvals.return_value = {"groups": [], "total": 0}

        result = approvals.inbox()

        self.assertEqual(
            {k: v for k, v in result.items() if k != "fetched_at"},
            {
                "total": 0,
                "needs_you": 0,
                "waiting": 0,
                "stats": {"high": 0, "overdue": 0},
                "sections": [],
                "waiting_items": [],
            },
        )
        self.assertEqual(
            approvals.count(), {"total": 0, "needs_you": 0, "waiting": 0, "high": 0, "overdue": 0}
        )

    def test_fetched_at_is_a_utc_iso_stamp(self):
        stamp = approvals.inbox()["fetched_at"]

        self.assertIsInstance(stamp, str)
        self.assertTrue(stamp.endswith("Z"), stamp)

    def test_an_item_carries_the_contract_fields(self):
        item = pm_item(
            "W-1",
            doctype="Sales Invoice",
            transaction="Sales Return",
            docname="SINV-0001",
            priority="High",
            days=3,
            state="Pending Finance",
            role_id="Finance Head",
            creator="Ali Hassan",
            category="Approval Pending",
            is_adhoc=False,
            return_to_originator=False,
        )
        self.pm.get_my_pending_approvals.return_value = pm_pending(item)
        self.party_amounts.return_value = {
            ("Sales Invoice", "SINV-0001"): {"party": "Acme Trading", "amount": 1250.5, "currency": "BHD"}
        }

        result = approvals.inbox()

        self.assertEqual(
            result["sections"][0]["items"][0],
            {
                "action_id": "W-1",
                "doctype": "Sales Invoice",
                "docname": "SINV-0001",
                "transaction": "Sales Return",
                "area": "Sales",
                "party": "Acme Trading",
                "amount": 1250.5,
                "currency": "BHD",
                "priority": "High",
                "state": "Pending Finance",
                "role_id": "Finance Head",
                "days": 3,
                "creator": "Ali Hassan",
                "category": "Approval Pending",
                "is_adhoc": False,
                "forwarded_by": "",
                "return_to_originator": False,
                "is_waiting": False,
                "waiting_with": "",
                "available_actions": [
                    {
                        "action": "Approve",
                        "require_comment": False,
                        "require_attachment": False,
                        "is_return_for_correction": False,
                    },
                    {
                        "action": "Reject",
                        "require_comment": False,
                        "require_attachment": False,
                        "is_return_for_correction": False,
                    },
                ],
            },
        )

    def test_a_document_nothing_is_known_about_still_shows(self):
        # The enrichment found no row (deleted, or the doctype has no such
        # fields): no party, no amount, no currency, and the area is "Other".
        self.pm.get_my_pending_approvals.return_value = pm_pending(
            pm_item("X", doctype="Gate Pass", transaction="Gate Pass", docname="GP-1")
        )

        item = approvals.inbox()["sections"][0]["items"][0]

        self.assertEqual((item["party"], item["amount"], item["currency"]), ("", None, ""))
        self.assertEqual(item["area"], "Other")

    def test_available_actions_are_pms_names_with_the_transition_flags(self):
        self.pm.get_my_pending_approvals.return_value = pm_pending(
            pm_item("A", available_actions=["Approve", "Reject", "Escalate"]), self.d
        )
        self.action_flags.return_value = {
            ("Sales Invoice", "Pending Approval"): {
                "Approve": {"require_comment": False, "require_attachment": True, "is_return_for_correction": False},
                "Reject": {"require_comment": True, "require_attachment": False, "is_return_for_correction": True},
            }
        }

        result = approvals.inbox()

        actions = result["sections"][0]["items"][0]["available_actions"]
        self.assertEqual(
            actions,
            [
                {"action": "Approve", "require_comment": False, "require_attachment": True,
                 "is_return_for_correction": False},
                {"action": "Reject", "require_comment": True, "require_attachment": False,
                 "is_return_for_correction": True},
                # no transition row found for this name: nothing is required
                {"action": "Escalate", "require_comment": False, "require_attachment": False,
                 "is_return_for_correction": False},
            ],
        )
        self.assertEqual(result["waiting_items"][0]["available_actions"], [])

    def test_the_enrichment_reads_the_items_once(self):
        self.action_flags.return_value = {}

        approvals.inbox()

        (party_items,) = self.party_amounts.call_args.args
        self.assertEqual(sorted(i["name"] for i in party_items), ["A", "B", "C", "D", "E"])
        (flag_items,) = self.action_flags.call_args.args
        self.assertEqual(sorted(i["name"] for i in flag_items), ["A", "B", "C", "D", "E"])
        self.assertEqual(self.party_amounts.call_count, 1)
        self.assertEqual(self.action_flags.call_count, 1)

    def test_an_ad_hoc_item_names_the_user_who_forwarded_it(self):
        forwarded = pm_item(
            "WA-2", is_adhoc=True, adhoc_for="WA-1", return_to_originator=True, category="Decision Pending"
        )
        self.pm.get_my_pending_approvals.return_value = pm_pending(self.a, forwarded)
        self._use_get_all(
            {
                "PM Workflow Action": [{"name": "WA-1", "completed_by": "ali@example.com"}],
                "User": [{"name": "ali@example.com", "full_name": "Ali Hassan"}],
            }
        )

        result = approvals.inbox()

        by_id = {i["action_id"]: i for s in result["sections"] for i in s["items"]}
        self.assertEqual(by_id["WA-2"]["forwarded_by"], "Ali Hassan")
        self.assertTrue(by_id["WA-2"]["is_adhoc"])
        self.assertTrue(by_id["WA-2"]["return_to_originator"])
        self.assertEqual(by_id["A"]["forwarded_by"], "")


class TestNothingWithoutPm(ApiCase):
    def setUp(self):
        super().setUp()
        self.available.return_value = False

    def test_every_endpoint_answers_empty_and_asks_nobody(self):
        self.assertEqual(approvals.availability(), {"enabled": False})
        self.assertEqual(
            approvals.count(), {"total": 0, "needs_you": 0, "waiting": 0, "high": 0, "overdue": 0}
        )
        inbox = approvals.inbox()
        self.assertEqual(
            {k: v for k, v in inbox.items() if k != "fetched_at"},
            {
                "total": 0,
                "needs_you": 0,
                "waiting": 0,
                "stats": {"high": 0, "overdue": 0},
                "sections": [],
                "waiting_items": [],
            },
        )
        self.assertTrue(inbox["fetched_at"].endswith("Z"))

        self.assertEqual(self.pm.mock_calls, [])
        self.assertEqual(self.get_all.calls, [])
        frappe.local.db.sql.assert_not_called()


# ─── enrichment helpers ───────────────────────────────────────────────────────


def _doc(doctype: str, docname: str) -> dict:
    return {"doctype": doctype, "docname": docname}


class TestPartyAmounts(SiteFreeCase):
    """Party and amount are read as the signed-in user: `frappe.get_list` (roles,
    User Permissions, field-level permissions), never `frappe.get_all`."""

    def setUp(self):
        super().setUp()
        self.metas = {
            "Sales Invoice": meta_with("customer", "customer_name", "grand_total", "currency", "company"),
            "Journal Entry": meta_with("title", "total_debit", "company"),
        }
        self._patch("frappe.get_meta", side_effect=lambda doctype: self._meta(doctype))
        self.currency_of = self._patch(
            "frappe.get_cached_value", side_effect=lambda doctype, name, field: {"Steel Co": "BHD"}.get(name)
        )
        self.unreadable: set[str] = set()
        self.has_permission = self._patch(
            "frappe.has_permission",
            side_effect=lambda doctype, ptype="read", **kwargs: doctype not in self.unreadable,
        )
        # `get_all` would skip the user's permissions: any call fails the test.
        self.get_all = self._use_get_all({})
        # frappe.db is a MagicMock here; give it the driver's real error classes.
        for name in ("ProgrammingError", "OperationalError", "InternalError", "DataError"):
            setattr(frappe.local.db, name, getattr(pymysql, name))

    def _meta(self, doctype):
        if doctype not in self.metas:
            raise frappe.DoesNotExistError(doctype)
        return self.metas[doctype]

    def test_one_query_per_doctype_never_per_row(self):
        get_list = self._use_get_list(
            {
                "Sales Invoice": [
                    {"name": "SINV-1", "customer_name": "Acme", "grand_total": 120.5, "currency": "USD",
                     "company": "Steel Co"},
                    {"name": "SINV-2", "customer_name": "Beta", "grand_total": 0, "currency": "",
                     "company": "Steel Co"},
                ],
                "Journal Entry": [
                    {"name": "JV-1", "title": "Rent", "total_debit": 1000, "company": "Steel Co"},
                ],
            }
        )
        items = [
            _doc("Sales Invoice", "SINV-1"),
            _doc("Sales Invoice", "SINV-2"),
            _doc("Sales Invoice", "SINV-1"),
            _doc("Journal Entry", "JV-1"),
            _doc("Sales Invoice", "SINV-9"),
        ]

        result = approvals._party_amounts(items)

        self.assertEqual([call[0] for call in get_list.calls], ["Sales Invoice", "Journal Entry"])
        invoice_call = get_list.calls[0][1]
        self.assertEqual(invoice_call["filters"], {"name": ["in", ["SINV-1", "SINV-2", "SINV-9"]]})
        self.assertEqual(
            invoice_call["fields"], ["name", "customer_name", "grand_total", "currency", "company"]
        )
        self.assertEqual(invoice_call["limit_page_length"], 0)  # every name asked for, no page of 20
        self.assertEqual(
            result,
            {
                ("Sales Invoice", "SINV-1"): {"party": "Acme", "amount": 120.5, "currency": "USD"},
                # no currency on the document: the company's own
                ("Sales Invoice", "SINV-2"): {"party": "Beta", "amount": 0.0, "currency": "BHD"},
                ("Journal Entry", "JV-1"): {"party": "Rent", "amount": 1000.0, "currency": "BHD"},
            },
        )
        # SINV-9 is not found, so it is not in the answer.
        self.assertNotIn(("Sales Invoice", "SINV-9"), result)
        self.assertEqual(self.get_all.calls, [])

    def test_a_company_is_looked_up_once_not_per_row(self):
        self._use_get_list(
            {
                "Sales Invoice": [
                    {"name": "SINV-1", "customer_name": "Acme", "grand_total": 1, "currency": "", "company": "Steel Co"},
                    {"name": "SINV-2", "customer_name": "Beta", "grand_total": 2, "currency": "", "company": "Steel Co"},
                ],
            }
        )

        approvals._party_amounts([_doc("Sales Invoice", "SINV-1"), _doc("Sales Invoice", "SINV-2")])

        self.assertEqual(self.currency_of.call_count, 1)

    def test_a_doctype_the_user_may_not_read_gives_nothing_and_no_error(self):
        self.unreadable.add("Sales Invoice")
        get_list = self._use_get_list(
            {"Journal Entry": [{"name": "JV-1", "title": "Rent", "total_debit": 5, "company": "Steel Co"}]}
        )
        log_error = self._patch("frappe.log_error")

        result = approvals._party_amounts([_doc("Sales Invoice", "SINV-1"), _doc("Journal Entry", "JV-1")])

        self.assertEqual(list(result), [("Journal Entry", "JV-1")])
        self.has_permission.assert_any_call("Sales Invoice", "read")
        self.assertEqual([call[0] for call in get_list.calls], ["Journal Entry"])  # never asked
        log_error.assert_not_called()
        self.assertEqual(frappe.local.message_log, [])

    def test_a_row_the_users_permissions_filter_out_is_left_out(self):
        # A User Permission (a branch, a company) makes `get_list` drop SINV-2
        # from the answer; PM still lists the document, so it shows with no
        # party and no amount (see TestInbox).
        get_list = self._use_get_list(
            {
                "Sales Invoice": [
                    {"name": "SINV-1", "customer_name": "Acme", "grand_total": 3, "currency": "BHD",
                     "company": "Steel Co"},
                ]
            }
        )

        result = approvals._party_amounts([_doc("Sales Invoice", "SINV-1"), _doc("Sales Invoice", "SINV-2")])

        self.assertEqual(get_list.calls[0][1]["filters"], {"name": ["in", ["SINV-1", "SINV-2"]]})
        self.assertEqual(list(result), [("Sales Invoice", "SINV-1")])

    def test_a_field_the_user_may_not_read_comes_back_with_no_value(self):
        # `get_list` leaves out a field above the user's permission level, so
        # the row has no `grand_total` key at all: no amount, not 0.
        self._use_get_list(
            {"Sales Invoice": [{"name": "SINV-1", "customer_name": "Acme", "currency": "USD", "company": "Steel Co"}]}
        )

        result = approvals._party_amounts([_doc("Sales Invoice", "SINV-1")])

        self.assertEqual(result, {("Sales Invoice", "SINV-1"): {"party": "Acme", "amount": None, "currency": "USD"}})

    def test_a_permission_error_from_the_read_is_blank_not_an_error_or_a_toast(self):
        def get_list(doctype, *args, **kwargs):
            if doctype == "Sales Invoice":
                # what `frappe.throw(..., PermissionError)` does before raising
                frappe.local.message_log.append({"message": "No permission to read Sales Invoice"})
                raise frappe.PermissionError
            return [frappe._dict(name="JV-1", title="Rent", total_debit=5, company="Steel Co")]

        self._patch("frappe.get_list", get_list)
        log_error = self._patch("frappe.log_error")

        result = approvals._party_amounts([_doc("Sales Invoice", "SINV-1"), _doc("Journal Entry", "JV-1")])

        self.assertEqual(list(result), [("Journal Entry", "JV-1")])
        self.assertEqual(frappe.local.message_log, [])  # no stray toast on the 200 response
        log_error.assert_not_called()  # and no Error Log row every minute

    def test_a_permission_error_that_left_no_message_keeps_the_earlier_ones(self):
        frappe.local.message_log.append({"message": "earlier"})

        def get_list(doctype, *args, **kwargs):
            raise frappe.PermissionError

        self._patch("frappe.get_list", get_list)

        self.assertEqual(approvals._party_amounts([_doc("Sales Invoice", "SINV-1")]), {})
        self.assertEqual(frappe.local.message_log, [{"message": "earlier"}])

    def test_a_database_error_is_deferred_to_the_error_log_and_that_doctype_skipped(self):
        error_log = MagicMock(name="Error Log")
        get_doc = self._patch("frappe.get_doc", return_value=error_log)

        def get_list(doctype, *args, **kwargs):
            if doctype == "Sales Invoice":
                raise pymysql.err.OperationalError(1054, "Unknown column 'grand_total' in 'field list'")
            return [frappe._dict(name="JV-1", title="Rent", total_debit=5, company="Steel Co")]

        self._patch("frappe.get_list", get_list)

        result = approvals._party_amounts([_doc("Sales Invoice", "SINV-1"), _doc("Journal Entry", "JV-1")])

        self.assertEqual(list(result), [("Journal Entry", "JV-1")])
        # The real `frappe.log_error` ran. This request is a GET, which ends in
        # a rollback: a row inserted now would be discarded, so it is deferred.
        error_log.deferred_insert.assert_called_once_with()
        error_log.insert.assert_not_called()
        self.assertIn("Sales Invoice", get_doc.call_args.kwargs["method"])

    def test_an_error_that_is_not_a_database_error_is_not_swallowed(self):
        def get_list(doctype, *args, **kwargs):
            raise ValueError("a bug, not a bad field")

        self._patch("frappe.get_list", get_list)
        log_error = self._patch("frappe.log_error")

        with self.assertRaises(ValueError):
            approvals._party_amounts([_doc("Sales Invoice", "SINV-1")])
        log_error.assert_not_called()

    def test_a_doctype_that_does_not_exist_is_skipped(self):
        get_list = self._use_get_list({})

        result = approvals._party_amounts([_doc("Gone Doctype", "G-1")])

        self.assertEqual(result, {})
        self.assertEqual(get_list.calls, [])

    def test_a_doctype_with_no_party_or_amount_field_is_not_queried(self):
        self.metas["Gate Pass"] = meta_with("company", "currency")
        get_list = self._use_get_list({})

        result = approvals._party_amounts([_doc("Gate Pass", "GP-1")])

        self.assertEqual(result, {})
        self.assertEqual(get_list.calls, [])

    def test_a_document_with_no_amount_field_has_a_party_and_no_amount(self):
        self.metas["Customer"] = meta_with("customer_name")
        self._use_get_list({"Customer": [{"name": "CUST-1", "customer_name": "Acme"}]})

        result = approvals._party_amounts([_doc("Customer", "CUST-1")])

        self.assertEqual(result, {("Customer", "CUST-1"): {"party": "Acme", "amount": None, "currency": ""}})

    def test_no_items_no_queries(self):
        get_list = self._use_get_list({})

        self.assertEqual(approvals._party_amounts([]), {})
        self.assertEqual(get_list.calls, [])


class TestActionFlags(SiteFreeCase):
    def setUp(self):
        super().setUp()
        # frappe.init binds the query builder and patches `.run`; with no site
        # that is done here.
        saved = getattr(frappe.local, "qb", _MISSING)
        frappe.local.qb = get_query_builder("mariadb")
        patch_query_execute()
        self.addCleanup(self._restore_qb, saved)

    @staticmethod
    def _restore_qb(saved):
        if saved is _MISSING:
            try:
                delattr(frappe.local, "qb")
            except AttributeError:
                pass
        else:
            frappe.local.qb = saved

    def test_one_query_over_the_active_workflows_gives_the_flags_by_state(self):
        frappe.local.db.sql.return_value = [
            frappe._dict(document_type="Sales Invoice", state="Pending Approval", action="Approve",
                         require_comment=0, require_attachment=0, is_return_for_correction=0),
            frappe._dict(document_type="Sales Invoice", state="Pending Approval", action="Reject",
                         require_comment=1, require_attachment=0, is_return_for_correction=1),
            # the same action for a second approver role: flags are OR-ed
            frappe._dict(document_type="Sales Invoice", state="Pending Approval", action="Approve",
                         require_comment=0, require_attachment=1, is_return_for_correction=0),
            frappe._dict(document_type="Journal Entry", state="Draft", action="Send for Approval",
                         require_comment=0, require_attachment=1, is_return_for_correction=0),
            # a doctype and a state that were each asked for, but not together
            frappe._dict(document_type="Journal Entry", state="Pending Approval", action="Approve",
                         require_comment=1, require_attachment=0, is_return_for_correction=0),
        ]
        items = [
            pm_item("A", doctype="Sales Invoice", state="Pending Approval", available_actions=["Approve", "Reject"]),
            pm_item("B", doctype="Sales Invoice", state="Pending Approval", available_actions=["Approve", "Reject"]),
            pm_item("C", doctype="Journal Entry", state="Draft", available_actions=["Send for Approval"]),
            pm_waiting("D", doctype="Sales Order", state="Pending Approval"),
        ]

        result = approvals._action_flags(items)

        self.assertEqual(frappe.local.db.sql.call_count, 1)
        query, params = frappe.local.db.sql.call_args.args[:2]
        self.assertIn("is_active", query)
        self.assertEqual(
            sorted(v for v in params.values() if isinstance(v, str)),
            ["Draft", "Journal Entry", "Pending Approval", "Sales Invoice"],
        )
        self.assertEqual(
            result,
            {
                ("Sales Invoice", "Pending Approval"): {
                    "Approve": {"require_comment": False, "require_attachment": True,
                                "is_return_for_correction": False},
                    "Reject": {"require_comment": True, "require_attachment": False,
                               "is_return_for_correction": True},
                },
                ("Journal Entry", "Draft"): {
                    "Send for Approval": {"require_comment": False, "require_attachment": True,
                                          "is_return_for_correction": False},
                },
            },
        )

    def test_items_without_actions_need_no_query(self):
        result = approvals._action_flags([pm_waiting("D"), pm_item("E", available_actions=[])])

        self.assertEqual(result, {})
        frappe.local.db.sql.assert_not_called()


class TestForwardedBy(SiteFreeCase):
    def test_names_the_user_who_completed_the_original_action(self):
        get_all = self._use_get_all(
            {
                "PM Workflow Action": [
                    {"name": "WA-1", "completed_by": "ali@example.com"},
                    {"name": "WA-5", "completed_by": "sara@example.com"},
                ],
                "User": [
                    {"name": "ali@example.com", "full_name": "Ali Hassan"},
                    {"name": "sara@example.com", "full_name": ""},
                ],
            }
        )
        items = [
            pm_item("WA-2", is_adhoc=True, adhoc_for="WA-1"),
            pm_item("WA-6", is_adhoc=True, adhoc_for="WA-5"),
            pm_item("WA-7", is_adhoc=True, adhoc_for="WA-1"),
            pm_item("WA-3"),
        ]

        result = approvals._forwarded_by(items)

        # a user with no full name shows as the user id
        self.assertEqual(result, {"WA-2": "Ali Hassan", "WA-6": "sara@example.com", "WA-7": "Ali Hassan"})
        self.assertEqual([call[0] for call in get_all.calls], ["PM Workflow Action", "User"])
        self.assertEqual(
            get_all.calls[0][1]["filters"], {"name": ["in", ["WA-1", "WA-5"]]}
        )
        self.assertEqual(
            get_all.calls[1][1]["filters"], {"name": ["in", ["ali@example.com", "sara@example.com"]]}
        )

    def test_an_original_action_nobody_completed_names_no_one(self):
        self._use_get_all({"PM Workflow Action": [{"name": "WA-1", "completed_by": None}]})

        result = approvals._forwarded_by([pm_item("WA-2", is_adhoc=True, adhoc_for="WA-1")])

        self.assertEqual(result, {})

    def test_no_ad_hoc_items_no_queries(self):
        get_all = self._use_get_all({})

        self.assertEqual(approvals._forwarded_by([pm_item("A"), pm_waiting("B")]), {})
        self.assertEqual(get_all.calls, [])


if __name__ == "__main__":
    unittest.main()
