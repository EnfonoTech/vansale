"""Web Push for approvals (`vansale.steelforce.approvals_push`) without a site,
without `permission_manager` (PM) and without a network: PM goes through
`approvals._pm()`, `pywebpush` through `approvals_push._webpush()`, and every
database call is a stub the test controls.

Run: cd ~/frappe-bench/sites && PYTHONPATH=$HOME/dev/vansale \
     ../env/bin/python -m unittest vansale.tests.test_approvals_push -v
"""

from __future__ import annotations

import json
import types
import unittest
from unittest.mock import MagicMock

import frappe

from vansale.steelforce import approvals_push as push
from vansale.tests.test_approvals_api import SiteFreeCase

SARA = "sara@example.com"
OMAR = "omar@example.com"
ALI = "ali@example.com"
FCM = "https://fcm.googleapis.com/fcm/send/abc"
APPLE = "https://web.push.apple.com/QK1"
P256 = "BNcRdreALRFXTkOOUHK1EtK2wtaz5Ry4YfYCA_0QTpQtUbVlUls0VJXg7A8u-Ts1XbjhazAkj7I99e8QcYP7DkM"
AUTH = "tBHItJI5svbpez7KI4CCXg"

_MISSING = object()


class FakeWebPushException(Exception):
    def __init__(self, message, response=None):
        super().__init__(message)
        self.response = response


def response(status: int):
    return types.SimpleNamespace(status_code=status)


class PushCase(SiteFreeCase):
    def setUp(self):
        super().setUp()
        frappe.local.session.user = SARA
        saved_conf = getattr(frappe.local, "conf", _MISSING)

        def restore_conf():
            if saved_conf is _MISSING:
                try:
                    del frappe.local.conf
                except AttributeError:
                    pass
            else:
                frappe.local.conf = saved_conf

        self.addCleanup(restore_conf)
        frappe.local.conf = frappe._dict(
            {push.PRIVATE_KEY_CONF: "PRIVATE-SECRET", push.PUBLIC_KEY_CONF: "PUBLIC-KEY"}
        )
        self.available = self._patch("vansale.steelforce.approvals.is_available", return_value=True)
        frappe.local.db.table_exists.return_value = True
        self.webpush_module = types.SimpleNamespace(
            webpush=MagicMock(name="webpush"), WebPushException=FakeWebPushException
        )
        self._patch("vansale.steelforce.approvals_push._webpush", return_value=self.webpush_module)
        self.log_error = self._patch("frappe.log_error")


# ─── Pure helpers ─────────────────────────────────────────────────────────────


class TestPureHelpers(SiteFreeCase):
    def test_endpoint_hash_is_sha256_hex(self):
        self.assertEqual(
            push.endpoint_hash("abc"), "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        )

    def test_subscription_problem(self):
        self.assertIsNone(push.subscription_problem(FCM, P256, AUTH))
        self.assertIsNone(push.subscription_problem(APPLE, P256, AUTH))
        self.assertIsNone(push.subscription_problem("https://wns2-par02p.notify.windows.com/w/?token=x", P256, AUTH))
        self.assertEqual(push.subscription_problem("http://fcm.googleapis.com/x", P256, AUTH), "endpoint")
        self.assertEqual(push.subscription_problem(FCM + "a" * 1000, P256, AUTH), "endpoint")
        self.assertEqual(push.subscription_problem(FCM + " x", P256, AUTH), "endpoint")
        self.assertEqual(push.subscription_problem("https://evil.example.com/fcm.googleapis.com", P256, AUTH), "service")
        self.assertEqual(push.subscription_problem("https://fcm.googleapis.com.evil.com/x", P256, AUTH), "service")
        self.assertEqual(push.subscription_problem("https://127.0.0.1/x", P256, AUTH), "service")
        self.assertEqual(push.subscription_problem(FCM, "", AUTH), "keys")
        self.assertEqual(push.subscription_problem(FCM, P256, ""), "keys")
        self.assertEqual(push.subscription_problem(FCM, "a" * 256, AUTH), "keys")
        self.assertEqual(push.subscription_problem(FCM, P256, "a b"), "keys")

    def test_payload_readable_carries_type_name_and_quoted_link(self):
        payload = push.build_payload("Sales Invoice", "SI/2026 #1", "ACT-1", True)
        self.assertEqual(
            payload,
            {
                "title": "Approval needed",
                "body": "Sales Invoice SI/2026 #1",
                "url": "/vansale/approvals/Sales%20Invoice/SI%2F2026%20%231",
                "tag": "ACT-1",
            },
        )

    def test_payload_unreadable_is_generic(self):
        payload = push.build_payload("Sales Invoice", "SI-1", "ACT-1", False)
        self.assertEqual(
            payload,
            {
                "title": "Approval needed",
                "body": "A document is waiting for your decision",
                "url": "/vansale/approvals",
                "tag": "ACT-1",
            },
        )
        self.assertNotIn("SI-1", json.dumps(payload))

    def test_failure_outcome(self):
        self.assertEqual(push.failure_outcome(404, 0), "delete")
        self.assertEqual(push.failure_outcome(410, 0), "delete")
        self.assertEqual(push.failure_outcome(500, 0), "count")
        self.assertEqual(push.failure_outcome(None, 3), "count")
        self.assertEqual(push.failure_outcome(None, 4), "delete")
        self.assertEqual(push.failure_outcome(429, 4), "delete")

    def test_wants_push(self):
        self.assertFalse(push.wants_push(SARA, SARA, False))
        self.assertTrue(push.wants_push(SARA, SARA, True))
        self.assertTrue(push.wants_push(SARA, OMAR, False))

    def test_vapid_subject_is_https_base(self):
        self.assertEqual(push.vapid_subject("http://sft.example.com/"), "https://sft.example.com")
        self.assertEqual(push.vapid_subject("https://sft.example.com"), "https://sft.example.com")


# ─── Endpoints ────────────────────────────────────────────────────────────────


class TestPushConfig(PushCase):
    def test_guest_refused(self):
        frappe.local.session.user = "Guest"
        for call in (
            lambda: push.push_config(FCM),
            lambda: push.push_subscribe(FCM, P256, AUTH),
            lambda: push.push_unsubscribe(FCM),
        ):
            with self.assertRaises(frappe.PermissionError):
                call()
        frappe.local.db.exists.assert_not_called()

    def test_enabled_and_subscribed_for_session_user(self):
        frappe.local.db.exists.return_value = "x"
        answer = push.push_config(FCM)
        self.assertEqual(answer, {"enabled": True, "public_key": "PUBLIC-KEY", "subscribed": True})
        frappe.local.db.exists.assert_called_once_with(
            push.SUBSCRIPTION, {"name": push.endpoint_hash(FCM), "user": SARA}
        )

    def test_no_endpoint_is_not_subscribed(self):
        answer = push.push_config("")
        self.assertFalse(answer["subscribed"])
        frappe.local.db.exists.assert_not_called()

    def test_disabled_without_keys_hides_public_key(self):
        del frappe.local.conf[push.PRIVATE_KEY_CONF]
        self.assertEqual(push.push_config(FCM), {"enabled": False, "public_key": "", "subscribed": False})

    def test_disabled_without_pm(self):
        self.available.return_value = False
        self.assertFalse(push.push_config(FCM)["enabled"])

    def test_disabled_without_pywebpush(self):
        self._patch("vansale.steelforce.approvals_push._webpush", side_effect=ImportError("no"))
        self.assertFalse(push.push_config()["enabled"])

    def test_disabled_without_table(self):
        frappe.local.db.table_exists.return_value = False
        self.assertFalse(push.push_config()["enabled"])


class TestPushSubscribe(PushCase):
    def setUp(self):
        super().setUp()
        self.get_doc = self._patch("frappe.get_doc")
        self.delete_doc = self._patch("frappe.delete_doc")
        self.get_all = self._patch("frappe.get_all", return_value=[])

    def test_refused_when_disabled(self):
        self.available.return_value = False
        with self.assertRaises(frappe.ValidationError):
            push.push_subscribe(FCM, P256, AUTH)
        self.get_doc.assert_not_called()

    def test_invalid_refused(self):
        with self.assertRaises(frappe.ValidationError):
            push.push_subscribe("https://intranet.local/hook", P256, AUTH)
        with self.assertRaises(frappe.ValidationError):
            push.push_subscribe(FCM, "", AUTH)
        self.get_doc.assert_not_called()

    def test_new_subscription_inserted_for_session_user(self):
        frappe.local.db.exists.return_value = None
        self.assertEqual(push.push_subscribe(FCM, P256, AUTH, "UA" * 200), {"ok": True})
        values = self.get_doc.call_args.args[0]
        self.assertEqual(values["doctype"], push.SUBSCRIPTION)
        self.assertEqual(values["user"], SARA)
        self.assertEqual(values["endpoint_hash"], push.endpoint_hash(FCM))
        self.assertEqual(values["endpoint"], FCM)
        self.assertEqual(len(values["user_agent"]), 255)
        self.get_doc.return_value.insert.assert_called_once_with(ignore_permissions=True)

    def test_existing_endpoint_moves_to_session_user(self):
        frappe.local.db.exists.return_value = push.endpoint_hash(FCM)
        doc = frappe._dict(user=OMAR, failures=3)
        doc.update = lambda values: dict.update(doc, values)
        doc.save = MagicMock()
        self.get_doc.return_value = doc
        push.push_subscribe(FCM, P256, AUTH)
        self.get_doc.assert_called_once_with(push.SUBSCRIPTION, push.endpoint_hash(FCM))
        self.assertEqual(doc["user"], SARA)
        self.assertEqual(doc["failures"], 0)
        doc.save.assert_called_once_with(ignore_permissions=True)

    def test_keeps_newest_ten(self):
        frappe.local.db.exists.return_value = None
        mine = push.endpoint_hash(FCM)
        older = [f"old{i}" for i in range(11)]
        self.get_all.return_value = older[:5] + [mine] + older[5:]
        push.push_subscribe(FCM, P256, AUTH)
        self.assertEqual(self.get_all.call_args.kwargs["filters"], {"user": SARA})
        deleted = [c.args[1] for c in self.delete_doc.call_args_list]
        self.assertEqual(deleted, older[9:])
        self.assertNotIn(mine, deleted)


class TestPushUnsubscribe(PushCase):
    def test_deletes_only_own_row(self):
        delete_doc = self._patch("frappe.delete_doc")
        frappe.local.db.exists.return_value = None
        self.assertEqual(push.push_unsubscribe(FCM), {"ok": True})
        frappe.local.db.exists.assert_called_once_with(
            push.SUBSCRIPTION, {"name": push.endpoint_hash(FCM), "user": SARA}
        )
        delete_doc.assert_not_called()

        frappe.local.db.exists.return_value = "x"
        push.push_unsubscribe(FCM)
        delete_doc.assert_called_once_with(
            push.SUBSCRIPTION, push.endpoint_hash(FCM), ignore_permissions=True, force=True
        )


# ─── Keys ─────────────────────────────────────────────────────────────────────


class TestSetupKeys(PushCase):
    def setUp(self):
        super().setUp()
        self.update = self._patch("frappe.installer.update_site_config")

    def test_idempotent_when_present(self):
        self.assertEqual(push.setup_keys(), "PUBLIC-KEY")
        self.update.assert_not_called()

    def test_generates_a_working_pair_and_returns_only_public(self):
        frappe.local.conf = frappe._dict()
        public = push.setup_keys()
        written = {c.args[0]: c.args[1] for c in self.update.call_args_list}
        self.assertEqual(set(written), {push.PRIVATE_KEY_CONF, push.PUBLIC_KEY_CONF})
        self.assertEqual(public, written[push.PUBLIC_KEY_CONF])
        self.assertNotEqual(public, written[push.PRIVATE_KEY_CONF])

        from py_vapid import Vapid
        from py_vapid.utils import b64urldecode

        raw_public = b64urldecode(public.encode())
        self.assertEqual(len(raw_public), 65)
        self.assertEqual(raw_public[0], 4)
        self.assertEqual(len(b64urldecode(written[push.PRIVATE_KEY_CONF].encode())), 32)
        # pywebpush loads the private key this way; its public point must match.
        from cryptography.hazmat.primitives import serialization

        loaded = Vapid.from_string(private_key=written[push.PRIVATE_KEY_CONF])
        self.assertEqual(
            loaded.public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint),
            raw_public,
        )
        frappe.local.db.delete.assert_not_called()

    def test_force_replaces_and_clears_subscriptions(self):
        public = push.setup_keys(force=1)
        self.assertNotEqual(public, "PUBLIC-KEY")
        frappe.local.db.delete.assert_called_once_with(push.SUBSCRIPTION)


# ─── Trigger ──────────────────────────────────────────────────────────────────


def action_doc(**overrides):
    values = dict(
        name="ACT-1",
        status="Open",
        reference_doctype="Sales Invoice",
        reference_name="SI-1",
        for_submitter=ALI,
        is_adhoc=0,
    )
    values.update(overrides)
    return frappe._dict(values)


class TestNotifyNewAction(PushCase):
    def setUp(self):
        super().setUp()
        self.enqueue = self._patch("frappe.enqueue")
        self.pm = MagicMock(name="pm")
        self.pm.hidden_doctypes.return_value = ["Material Request"]
        self._patch("vansale.steelforce.approvals._pm", return_value=self.pm)
        frappe.local.db.exists.return_value = "sub"

    def test_queues_for_open_action(self):
        push.notify_new_action(action_doc(), "after_insert")
        self.enqueue.assert_called_once_with(
            "vansale.steelforce.approvals_push.send_for_action",
            queue="short",
            action_name="ACT-1",
            enqueue_after_commit=True,
            job_id="vansale_push_ACT-1",
            deduplicate=True,
        )

    def test_skips_closed_action(self):
        push.notify_new_action(action_doc(status="Completed"))
        self.enqueue.assert_not_called()

    def test_skips_without_subscriptions(self):
        frappe.local.db.exists.return_value = None
        push.notify_new_action(action_doc())
        self.enqueue.assert_not_called()

    def test_skips_when_disabled(self):
        frappe.local.conf = frappe._dict()
        push.notify_new_action(action_doc())
        self.enqueue.assert_not_called()

    def test_skips_hidden_types(self):
        push.notify_new_action(action_doc(reference_doctype="Stock Entry"))
        push.notify_new_action(action_doc(reference_doctype="material request"))
        self.enqueue.assert_not_called()

    def test_never_raises(self):
        self.enqueue.side_effect = RuntimeError("redis down")
        push.notify_new_action(action_doc())
        self.log_error.assert_called_once()
        self.assertTrue(self.log_error.call_args.kwargs["defer_insert"])


# ─── Worker ───────────────────────────────────────────────────────────────────


def sub(name, user, endpoint=FCM, failures=0):
    return frappe._dict(name=name, user=user, endpoint=endpoint, p256dh=P256, auth=AUTH, failures=failures)


class TestSendForAction(PushCase):
    def setUp(self):
        super().setUp()
        self.action = action_doc()
        self._patch("frappe.get_doc", return_value=self.action)
        frappe.local.db.exists.return_value = "ACT-1"
        self.pm = MagicMock(name="pm")
        self.pm.hidden_doctypes.return_value = []
        self.can_act = {SARA, OMAR, ALI}
        self.pm.can_act_on.side_effect = lambda action, user: user in self.can_act
        self._patch("vansale.steelforce.approvals._pm", return_value=self.pm)
        self.readers = {SARA}
        self.has_permission = self._patch(
            "frappe.has_permission", side_effect=lambda dt, ptype, doc=None, user=None: user in self.readers
        )
        self._patch("vansale.steelforce.approvals_push.get_url", return_value="http://sft.example.com")
        self.subs = [sub("s1", SARA), sub("s2", SARA, APPLE), sub("o1", OMAR), sub("a1", ALI)]
        self.users = [
            frappe._dict(name=SARA, language="ar"),
            frappe._dict(name=OMAR, language=""),
            frappe._dict(name=ALI, language="en"),
        ]
        self.langs_seen = []
        self.webpush_module.webpush.side_effect = self.record_send
        self._patch("frappe.get_all", side_effect=self.get_all)

    def record_send(self, **kwargs):
        self.langs_seen.append(frappe.local.lang)

    def get_all(self, doctype, *args, **kwargs):
        if doctype == push.SUBSCRIPTION:
            return list(self.subs)
        if doctype == "User":
            self.user_filters = kwargs["filters"]
            return list(self.users)
        raise AssertionError(doctype)

    def sends(self):
        return [c.kwargs for c in self.webpush_module.webpush.call_args_list]

    def test_sends_to_each_device_of_permitted_users(self):
        push.send_for_action("ACT-1")
        self.assertEqual(self.user_filters["enabled"], 1)
        self.assertEqual(self.user_filters["user_type"], "System User")
        sends = self.sends()
        # ali is the submitter of a non-ad-hoc action: no push.
        self.assertEqual([s["subscription_info"]["endpoint"] for s in sends], [FCM, APPLE, FCM])
        sara = json.loads(sends[0]["data"])
        self.assertEqual(sara["url"], "/vansale/approvals/Sales%20Invoice/SI-1")
        self.assertEqual(sara["body"], "Sales Invoice SI-1")
        omar = json.loads(sends[2]["data"])
        self.assertEqual(omar["url"], "/vansale/approvals")
        self.assertNotIn("SI-1", sends[2]["data"])
        for s in sends:
            self.assertEqual(s["vapid_private_key"], "PRIVATE-SECRET")
            self.assertEqual(s["vapid_claims"], {"sub": "https://sft.example.com"})
            self.assertEqual(s["ttl"], 86400)
            self.assertEqual(s["timeout"], 10)
            self.assertEqual(s["subscription_info"]["keys"], {"p256dh": P256, "auth": AUTH})
        # a fresh claims dict per call (pywebpush writes aud/exp into it)
        self.assertIsNot(sends[0]["vapid_claims"], sends[1]["vapid_claims"])
        self.log_error.assert_not_called()

    def test_success_records_last_ok(self):
        push.send_for_action("ACT-1")
        updated = [c.args for c in frappe.local.db.set_value.call_args_list]
        self.assertEqual([args[1] for args in updated], ["s1", "s2", "o1"])
        for args in updated:
            self.assertEqual(args[2]["failures"], 0)
            self.assertIn("last_ok", args[2])

    def test_adhoc_action_reaches_submitter(self):
        self.action["is_adhoc"] = 1
        push.send_for_action("ACT-1")
        self.assertEqual(len(self.sends()), 4)

    def test_users_pm_refuses_or_disabled_get_nothing(self):
        self.can_act = {OMAR}
        self.users = [u for u in self.users if u.name != OMAR] + [frappe._dict(name="Administrator", language="")]
        self.subs.append(sub("adm", "Administrator"))
        push.send_for_action("ACT-1")
        self.assertEqual(self.sends(), [])

    def test_language_follows_recipient_and_is_restored(self):
        frappe.local.lang = "en"
        push.send_for_action("ACT-1")
        self.assertEqual(frappe.local.lang, "en")
        translate = self._patch("vansale.steelforce.approvals_push.build_payload", wraps=push.build_payload)
        langs = []
        translate.side_effect = lambda *a: langs.append(frappe.local.lang) or {"title": "x"}
        push.send_for_action("ACT-1")
        self.assertEqual(langs, ["ar", "en"])
        self.assertEqual(frappe.local.lang, "en")

    def test_gone_subscription_deleted_others_continue(self):
        def fail_first(**kwargs):
            if kwargs["subscription_info"]["endpoint"] == FCM and not getattr(self, "failed", False):
                self.failed = True
                raise FakeWebPushException("gone", response=response(410))

        self.webpush_module.webpush.side_effect = fail_first
        push.send_for_action("ACT-1")
        self.assertEqual(len(self.sends()), 3)
        frappe.local.db.delete.assert_called_once_with(push.SUBSCRIPTION, {"name": "s1"})
        # Pruning a gone subscription is routine: nothing goes to the Error Log.
        self.log_error.assert_not_called()

    def test_other_failures_counted_then_deleted_one_log(self):
        self.subs = [sub("s1", SARA, failures=0), sub("s2", SARA, APPLE, failures=4), sub("o1", OMAR)]
        self.webpush_module.webpush.side_effect = ConnectionError("timeout")
        push.send_for_action("ACT-1")
        frappe.local.db.set_value.assert_any_call(push.SUBSCRIPTION, "s1", "failures", 1, update_modified=False)
        frappe.local.db.set_value.assert_any_call(push.SUBSCRIPTION, "o1", "failures", 1, update_modified=False)
        frappe.local.db.delete.assert_called_once_with(push.SUBSCRIPTION, {"name": "s2"})
        self.log_error.assert_called_once()
        message = self.log_error.call_args.kwargs["message"]
        self.assertIn("3 push(es)", message)
        self.assertNotIn("fcm.googleapis.com", message)
        self.assertNotIn("PRIVATE-SECRET", message)
        self.assertNotIn(AUTH, message)

    def test_stops_when_action_not_open_or_missing(self):
        self.action["status"] = "Completed"
        push.send_for_action("ACT-1")
        frappe.local.db.exists.return_value = None
        push.send_for_action("ACT-2")
        self.assertEqual(self.sends(), [])

    def test_stops_for_hidden_type(self):
        self.action["reference_doctype"] = "Stock Entry"
        push.send_for_action("ACT-1")
        self.assertEqual(self.sends(), [])


if __name__ == "__main__":
    unittest.main()
