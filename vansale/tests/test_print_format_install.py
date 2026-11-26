"""Print format upsert (`patches.v1_0.install_vansale_tax_invoice`).

Frappe saves a *standard* Print Format only in developer mode (or inside a
migrate / install / test); everywhere else `PrintFormat.validate` raises
"Standard Print Format cannot be updated" and the format never got created.
With developer mode off the upsert now writes a *custom* format. printview
renders a format's own HTML only when `custom_format` is on (or `standard` is
Yes), so `custom_format = 1` is part of the contract, not a detail.

Run: cd ~/frappe-bench/sites && PYTHONPATH=$HOME/dev/vansale \
     ../env/bin/python -m unittest vansale.tests.test_print_format_install -v
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

import frappe

from vansale.patches.v1_0 import install_vansale_tax_invoice as pf
from vansale.tests import _site_free

HTML = "<div>{{ doc.name }}</div>"
_MISSING = object()


class FakeDoc:
    """Just enough of a Print Format Document for `upsert`."""

    def __init__(self, **values):
        self.__dict__.update(values)
        self.inserts = 0
        self.saves = 0

    def get(self, key, default=None):
        return self.__dict__.get(key, default)

    def set(self, key, value):
        self.__dict__[key] = value

    def update(self, values):
        self.__dict__.update(values)

    def insert(self, **kwargs):
        self.inserts += 1

    def save(self, **kwargs):
        self.saves += 1


class TestUpsert(unittest.TestCase):
    def setUp(self):
        _site_free.setup_site_free()
        self.addCleanup(_site_free.teardown_site_free)
        self._conf = getattr(frappe.local, "conf", _MISSING)
        self.addCleanup(self._restore_conf)
        load = patch.object(pf, "_load_html", return_value=HTML)
        load.start()
        self.addCleanup(load.stop)

    def _restore_conf(self):
        if self._conf is _MISSING:
            del frappe.local.conf
        else:
            frappe.local.conf = self._conf

    def _site(self, developer_mode, existing=None):
        frappe.local.conf = frappe._dict(developer_mode=developer_mode)
        frappe.local.db.exists.return_value = bool(existing)
        return existing

    def _upsert_new(self, developer_mode):
        self._site(developer_mode)
        doc = FakeDoc()
        with patch("frappe.new_doc", return_value=doc) as new_doc:
            pf.upsert(pf.FORMAT_NAME, pf.DOC_TYPE)
        new_doc.assert_called_once_with("Print Format")
        self.assertEqual((doc.inserts, doc.saves), (1, 0))
        return doc

    def _upsert_existing(self, developer_mode, **values):
        doc = self._site(developer_mode, existing=FakeDoc(**values))
        with patch("frappe.get_doc", return_value=doc):
            pf.upsert(pf.FORMAT_NAME, pf.DOC_TYPE)
        self.assertEqual(doc.inserts, 0)
        return doc

    # --- production: developer mode off -----------------------------------

    def test_production_creates_a_custom_format(self):
        doc = self._upsert_new(developer_mode=0)
        self.assertEqual(doc.standard, "No")
        self.assertEqual(doc.custom_format, 1)
        self.assertEqual(doc.print_format_type, "Jinja")
        self.assertEqual(doc.doc_type, "Sales Invoice")
        self.assertEqual(doc.module, "Vansale")
        self.assertEqual(doc.name, pf.FORMAT_NAME)
        self.assertEqual(doc.html, HTML)

    def test_developer_mode_unset_counts_as_production(self):
        frappe.local.conf = frappe._dict()
        frappe.local.db.exists.return_value = False
        doc = FakeDoc()
        with patch("frappe.new_doc", return_value=doc):
            pf.upsert(pf.FORMAT_NAME, pf.DOC_TYPE)
        self.assertEqual((doc.standard, doc.custom_format), ("No", 1))

    def test_production_converts_a_row_left_standard(self):
        """A row an earlier migrate saved as standard: saving it later outside
        a migrate would raise, so it becomes a custom format too."""
        doc = self._upsert_existing(
            0, standard="Yes", custom_format=0, doc_type="Sales Invoice", print_format_type="Jinja", html=HTML
        )
        self.assertEqual((doc.standard, doc.custom_format), ("No", 1))
        self.assertEqual(doc.saves, 1)

    def test_production_refreshes_stale_html(self):
        doc = self._upsert_existing(
            0, standard="No", custom_format=1, doc_type="Sales Invoice", print_format_type="Jinja", html="<old>"
        )
        self.assertEqual(doc.html, HTML)
        self.assertEqual(doc.saves, 1)

    def test_production_up_to_date_row_is_not_saved(self):
        doc = self._upsert_existing(
            0, standard="No", custom_format=1, doc_type="Sales Invoice", print_format_type="Jinja", html=HTML
        )
        self.assertEqual(doc.saves, 0)

    # --- dev sites: developer mode on (unchanged behaviour) ---------------

    def test_developer_mode_creates_a_standard_format(self):
        doc = self._upsert_new(developer_mode=1)
        self.assertEqual(doc.standard, "Yes")
        self.assertEqual(doc.custom_format, 0)
        self.assertEqual(doc.print_format_type, "Jinja")
        self.assertEqual(doc.module, "Vansale")
        self.assertEqual(doc.html, HTML)

    def test_developer_mode_up_to_date_row_is_not_saved(self):
        doc = self._upsert_existing(
            1, standard="Yes", custom_format=0, doc_type="Sales Invoice", print_format_type="Jinja", html=HTML
        )
        self.assertEqual(doc.saves, 0)

    def test_developer_mode_makes_a_row_standard_and_leaves_custom_format(self):
        doc = self._upsert_existing(
            1, standard="No", custom_format=1, doc_type="Sales Invoice", print_format_type="Jinja", html=HTML
        )
        self.assertEqual(doc.standard, "Yes")
        self.assertEqual(doc.custom_format, 1)  # not touched, as before
        self.assertEqual(doc.saves, 1)


class TestFormatFiles(unittest.TestCase):
    def test_execute_upserts_both_formats(self):
        with patch.object(pf, "upsert") as upsert:
            pf.execute()
        self.assertEqual(
            [c.args for c in upsert.call_args_list],
            [("Vansale Tax Invoice", "Sales Invoice"), ("Vansale Payment Receipt", "Payment Entry")],
        )

    def test_html_files_load(self):
        for name, _doctype in pf.PRINT_FORMATS:
            self.assertIn("{{", pf._load_html(name), name)
