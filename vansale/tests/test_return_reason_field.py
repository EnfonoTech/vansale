"""`Sales Invoice-custom_return_reason`: create it when missing, never touch one
a site already has.

Steel Force owns a Data field of that name (mandatory on return / debit note,
read by sf_trading as free text). It used to be a vansale fixture, and Frappe
re-imports fixtures on install-app and on EVERY migrate, so each deploy
replaced SFT's row with vansale's Select. These tests pin the replacement:
not a fixture, created only when missing, and `_set_reason` works with either
field type.

Run: cd ~/frappe-bench/sites && PYTHONPATH=$HOME/dev/vansale \
     ../env/bin/python -m unittest vansale.tests.test_return_reason_field -v
"""

from __future__ import annotations

import json
import pathlib
import unittest
from unittest.mock import patch

import frappe

from vansale import hooks, setup
from vansale.api.sales_return import RETURN_REASONS, reason_field_value
from vansale.tests import _site_free

FIELD = "Sales Invoice-custom_return_reason"
CREATE = "frappe.custom.doctype.custom_field.custom_field.create_custom_fields"


def _select_def() -> dict:
    return setup.CREATE_ONLY_CUSTOM_FIELDS["Sales Invoice"][0]


class TestNotAFixture(unittest.TestCase):
    def test_fixture_file_does_not_ship_it(self):
        path = pathlib.Path(setup.__file__).parent / "fixtures" / "custom_field.json"
        names = {row["name"] for row in json.loads(path.read_text())}
        self.assertNotIn(FIELD, names)
        # the app's other fixture fields are still there
        self.assertIn("Sales Invoice-custom_client_id", names)

    def test_export_fixtures_filter_keeps_it_out(self):
        (custom_field,) = [f for f in hooks.fixtures if f["dt"] == "Custom Field"]
        self.assertIn(["module", "=", "Vansale"], custom_field["filters"])
        self.assertIn(["name", "!=", FIELD], custom_field["filters"])

    def test_not_in_the_always_update_dict(self):
        names = {df["fieldname"] for fields in setup.VANSALE_CUSTOM_FIELDS.values() for df in fields}
        self.assertNotIn("custom_return_reason", names)

    def test_install_hook_registered(self):
        self.assertEqual(hooks.after_install, "vansale.setup.after_install")

    def test_select_options_match_return_reasons(self):
        df = _select_def()
        self.assertEqual(df["fieldtype"], "Select")
        self.assertEqual(df["module"], "Vansale")
        options = df["options"].split("\n")
        self.assertEqual(options[0], "")  # blank first option, as before
        self.assertEqual(tuple(options[1:]), RETURN_REASONS)


class TestCreateOnly(unittest.TestCase):
    def setUp(self):
        _site_free.setup_site_free()
        self.addCleanup(_site_free.teardown_site_free)

    def _run(self, *, custom_field_row, in_doctype=False):
        frappe.local.db.exists.return_value = FIELD if custom_field_row else None
        with patch("frappe.get_meta") as get_meta, patch(CREATE) as create:
            get_meta.return_value.has_field.return_value = in_doctype
            setup.ensure_create_only_custom_fields()
        return create

    def test_site_that_has_the_field_is_left_alone(self):
        create = self._run(custom_field_row=True)
        create.assert_not_called()
        # looked up by doctype + fieldname, whoever owns the row
        frappe.local.db.exists.assert_called_with(
            "Custom Field", {"dt": "Sales Invoice", "fieldname": "custom_return_reason"}
        )

    def test_field_the_doctype_defines_is_left_alone(self):
        self._run(custom_field_row=False, in_doctype=True).assert_not_called()

    def test_site_without_the_field_gets_the_select(self):
        create = self._run(custom_field_row=False)
        create.assert_called_once()
        args, kwargs = create.call_args
        self.assertIs(kwargs.get("update"), False, "update=True could rewrite a foreign row")
        self.assertEqual(args[0], {"Sales Invoice": [_select_def()]})

    def test_migrate_does_not_pass_it_to_the_update_call(self):
        """after_migrate's update=True call must not carry the field, even when
        the site has none (the create-only call makes it, with update=False)."""
        frappe.local.db.exists.return_value = None
        with patch("frappe.get_meta") as get_meta, patch(CREATE) as create:
            get_meta.return_value.has_field.return_value = False
            setup._ensure_custom_fields()
        updating = [c for c in create.call_args_list if c.kwargs.get("update") is True]
        self.assertEqual(len(updating), 1)
        carried = {df["fieldname"] for fields in updating[0].args[0].values() for df in fields}
        self.assertNotIn("custom_return_reason", carried)
        creating = [c for c in create.call_args_list if c.kwargs.get("update") is False]
        self.assertEqual(len(creating), 1)

    def test_after_install_creates_it_on_a_fresh_site(self):
        frappe.local.db.exists.return_value = None
        with patch("frappe.get_meta") as get_meta, patch(CREATE) as create:
            get_meta.return_value.has_field.return_value = False
            setup.after_install()
        create.assert_called_once()
        self.assertEqual(create.call_args.args[0], {"Sales Invoice": [_select_def()]})


class TestReasonFieldValue(unittest.TestCase):
    """What `_set_reason` stores, by the field type the site has."""

    SELECT = frappe._dict(fieldtype="Select", options="\n" + "\n".join(RETURN_REASONS))

    def test_select_takes_a_listed_option(self):
        self.assertEqual(reason_field_value(self.SELECT, "Damaged", "Damaged"), "Damaged")

    def test_select_free_text_arrives_as_other(self):
        # resolve_return_reason turns free text into ("Other", text)
        self.assertEqual(reason_field_value(self.SELECT, "Other", "box was crushed"), "Other")

    def test_select_with_a_different_list_falls_back_to_other(self):
        df = frappe._dict(fieldtype="Select", options="\nBroken\nOther")
        self.assertEqual(reason_field_value(df, "Short Delivery", "Short Delivery"), "Other")

    def test_select_with_a_list_that_has_no_other_stores_nothing(self):
        df = frappe._dict(fieldtype="Select", options="\nBroken\nLate")
        self.assertIsNone(reason_field_value(df, "Short Delivery", "Short Delivery"))

    def test_data_field_keeps_the_free_text(self):
        """Steel Force: Data, read by sf_trading as 'Other' + text."""
        df = frappe._dict(fieldtype="Data")
        self.assertEqual(reason_field_value(df, "Other", "box was crushed"), "box was crushed")
        self.assertEqual(reason_field_value(df, "Damaged", "Damaged"), "Damaged")

    def test_data_field_is_cut_to_its_140_characters(self):
        df = frappe._dict(fieldtype="Data")
        value = reason_field_value(df, "Other", "x" * 500)
        self.assertEqual(len(value), 140)

    def test_text_field_keeps_the_whole_text(self):
        df = frappe._dict(fieldtype="Small Text")
        self.assertEqual(reason_field_value(df, "Other", "y" * 500), "y" * 500)

    def test_other_types_store_nothing(self):
        self.assertIsNone(reason_field_value(frappe._dict(fieldtype="Link"), "Damaged", "Damaged"))
