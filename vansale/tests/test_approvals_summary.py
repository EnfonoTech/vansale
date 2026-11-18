"""Pure summary builders behind the Approvals detail screen: which fields name
the party and the amount, how a value is shown, the key facts and the first
few lines of a document.

The summary module imports no `frappe`, so nothing here needs a site. Fields
are plain `SimpleNamespace` objects, the same duck type a `DocField` has.

Run: cd ~/frappe-bench/sites && PYTHONPATH=$HOME/dev/vansale \
     ../env/bin/python -m unittest vansale.tests.test_approvals_summary -v
"""

from __future__ import annotations

import unittest
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace

from vansale.steelforce.approvals_summary import (
    LINE_TABLES,
    first_lines,
    format_value,
    key_facts,
    pick_party_amount,
)

# The desk's own lists (permission_manager approval_inbox.js `_load_preview`),
# written out here so a slip in the module's copy of them fails a test.
DESK_SKIP_TYPES = (
    "Section Break", "Column Break", "HTML", "Button", "Tab Break", "Code",
    "JSON", "Long Text", "Small Text", "Text", "Text Editor", "Signature",
    "Attach", "Attach Image", "Barcode", "Geolocation", "Table",
    "Table MultiSelect", "Password",
)  # fmt: skip
DESK_SKIP_NAMES = (
    "exchange_rate", "conversion_rate", "base_exchange_rate", "naming_series",
    "amended_from", "amended_to", "docstatus", "idx", "owner", "modified",
    "modified_by", "creation", "name", "workflow_state", "letter_head",
    "select_print_heading", "tc_name", "terms", "taxes_and_charges",
    "shipping_rule", "discount_amount", "additional_discount_percentage",
    "apply_discount_on", "in_words", "base_in_words", "language", "meta_image",
    "status_field", "source", "base_grand_total", "base_net_total",
    "base_total", "base_tax_withholding_net_total", "outstanding_amount",
    "debit_to", "credit_to", "against_expense_account",
    "against_income_account", "remarks", "user_remark", "instructions",
    "total_advance", "total_taxes_and_charges", "total_billing_amount",
    "update_stock", "set_warehouse", "set_target_warehouse", "scan_barcode",
    "barcode", "image", "company_address_display", "customer_address",
    "contact_display", "contact_email", "contact_mobile",
    "shipping_address_name", "billing_address",
)  # fmt: skip


def _field(fieldname: str, fieldtype: str = "Data", **attrs) -> SimpleNamespace:
    label = fieldname.replace("_", " ").title()
    return SimpleNamespace(
        fieldname=fieldname, label=label, fieldtype=fieldtype, **attrs
    )


def _has(*fieldnames: str):
    return set(fieldnames).__contains__


class TestPickPartyAmount(unittest.TestCase):
    def test_title_and_total_debit(self):
        self.assertEqual(
            pick_party_amount(_has("total_debit", "title")),
            ("title", "total_debit"),
        )

    def test_supplier_name_and_grand_total(self):
        self.assertEqual(
            pick_party_amount(_has("supplier_name", "grand_total")),
            ("supplier_name", "grand_total"),
        )

    def test_party_name_and_paid_amount(self):
        self.assertEqual(
            pick_party_amount(_has("party_name", "paid_amount")),
            ("party_name", "paid_amount"),
        )

    def test_no_fields_gives_none_for_both(self):
        self.assertEqual(pick_party_amount(_has()), (None, None))

    def test_the_first_present_field_in_each_list_wins(self):
        party, amount = pick_party_amount(
            _has(
                "title", "supplier", "customer", "party", "party_name",
                "supplier_name", "customer_name",
                "total_amount", "amount", "paid_amount", "total_debit",
                "rounded_total", "grand_total",
            )  # fmt: skip
        )
        self.assertEqual((party, amount), ("customer_name", "grand_total"))

    def test_party_and_amount_are_picked_independently(self):
        self.assertEqual(pick_party_amount(_has("customer")), ("customer", None))
        self.assertEqual(pick_party_amount(_has("amount")), (None, "amount"))


class TestFormatValue(unittest.TestCase):
    def test_currency_uses_the_given_decimals(self):
        self.assertEqual(format_value("Currency", 749.82, 3), "749.820")
        self.assertEqual(format_value("Currency", 1200, 2), "1,200.00")

    def test_currency_groups_thousands_and_keeps_the_sign(self):
        self.assertEqual(format_value("Currency", 1234567.5, 2), "1,234,567.50")
        self.assertEqual(format_value("Currency", -1234.5, 2), "-1,234.50")

    def test_currency_rounds_half_up_like_frappe(self):
        self.assertEqual(format_value("Currency", 2.675, 2), "2.68")
        self.assertEqual(format_value("Currency", Decimal("0.0005"), 3), "0.001")

    def test_a_tiny_negative_does_not_show_as_negative_zero(self):
        self.assertEqual(format_value("Currency", -0.0001, 2), "0.00")

    def test_float_and_percent_are_grouped_like_currency(self):
        self.assertEqual(format_value("Float", 12000.5, 3), "12,000.500")
        self.assertEqual(format_value("Percent", 15, 1), "15.0")

    def test_numeric_strings_are_formatted(self):
        self.assertEqual(format_value("Currency", "12.5", 2), "12.50")

    def test_a_non_numeric_value_in_a_number_field_is_shown_as_is(self):
        self.assertEqual(format_value("Currency", "n/a", 2), "n/a")

    def test_int_is_plain(self):
        self.assertEqual(format_value("Int", 1234567, 3), "1234567")
        self.assertEqual(format_value("Int", "42", 3), "42")

    def test_check_is_yes_or_no(self):
        self.assertEqual(format_value("Check", 1, 0), "Yes")
        self.assertEqual(format_value("Check", 0, 0), "No")
        self.assertEqual(format_value("Check", "0", 0), "No")
        self.assertEqual(format_value("Check", "1", 0), "Yes")

    def test_date_and_datetime_are_iso(self):
        self.assertEqual(format_value("Date", date(2026, 11, 19), 0), "2026-11-19")
        self.assertEqual(
            format_value("Datetime", datetime(2026, 11, 19, 9, 30, 5), 0),
            "2026-11-19T09:30:05",
        )
        self.assertEqual(format_value("Date", "2026-11-19", 0), "2026-11-19")

    def test_a_table_or_other_complex_value_gives_none(self):
        self.assertIsNone(format_value("Table", [1], 0))
        self.assertIsNone(format_value("Data", {"a": 1}, 0))

    def test_everything_else_is_the_string(self):
        self.assertEqual(format_value("Link", "CUST-001", 0), "CUST-001")
        self.assertEqual(format_value("Select", "Draft", 0), "Draft")

    def test_no_value_gives_none_not_the_word_none(self):
        self.assertIsNone(format_value("Data", None, 0))
        self.assertIsNone(format_value("Currency", None, 2))


class TestKeyFacts(unittest.TestCase):
    def _twelve_fields(self):
        fields = [_field(f"f{i}") for i in range(1, 13)]
        fields[9].in_preview = 1  # f10
        fields[10].in_preview = 1  # f11
        fields[11].bold = 1  # f12
        fields[8].in_list_view = 1  # f9
        doc = {f.fieldname: f"v-{f.fieldname}" for f in fields}
        return fields, doc

    def test_twelve_candidates_are_capped_at_eight_preview_first(self):
        fields, doc = self._twelve_fields()
        facts = key_facts(fields, doc, 3)
        self.assertEqual(len(facts), 8)
        self.assertEqual(
            [fact["label"] for fact in facts],
            ["F10", "F11", "F12", "F9", "F1", "F2", "F3", "F4"],
        )
        self.assertEqual(facts[0], {"label": "F10", "value": "v-f10"})

    def test_the_limit_can_be_changed(self):
        fields, doc = self._twelve_fields()
        self.assertEqual(len(key_facts(fields, doc, 3, limit=2)), 2)

    def test_naming_series_docstatus_and_tables_are_skipped(self):
        fields = [
            _field("naming_series"),
            _field("docstatus", "Int"),
            _field("accounts", "Table"),
            _field("posting_date", "Date"),
        ]
        doc = {
            "naming_series": "ACC-JV-.YYYY.-",
            "docstatus": 0,
            "accounts": [{"account": "Cash"}],
            "posting_date": date(2026, 11, 19),
        }
        self.assertEqual(
            key_facts(fields, doc, 3),
            [{"label": "Posting Date", "value": "2026-11-19"}],
        )

    def test_every_desk_skip_name_is_skipped(self):
        for name in DESK_SKIP_NAMES:
            with self.subTest(fieldname=name):
                self.assertEqual(key_facts([_field(name)], {name: "x"}, 3), [])

    def test_every_desk_skip_type_is_skipped(self):
        for fieldtype in DESK_SKIP_TYPES:
            with self.subTest(fieldtype=fieldtype):
                self.assertEqual(
                    key_facts([_field("f", fieldtype)], {"f": "x"}, 3), []
                )

    def test_hidden_and_print_hidden_fields_are_skipped(self):
        fields = [
            _field("a", hidden=1),
            _field("b", print_hide=1),
            _field("c", hidden=0, print_hide=0),
        ]
        doc = {"a": "x", "b": "x", "c": "x"}
        self.assertEqual([f["label"] for f in key_facts(fields, doc, 3)], ["C"])

    def test_fields_without_a_value_are_dropped(self):
        fields = [_field("a"), _field("b"), _field("c")]
        self.assertEqual(
            key_facts(fields, {"a": None, "b": ""}, 3),
            [],
        )

    def test_a_zero_is_a_value_and_is_kept(self):
        fields = [_field("qty", "Int"), _field("urgent", "Check")]
        facts = key_facts(fields, {"qty": 0, "urgent": 0}, 3)
        self.assertEqual(
            facts,
            [{"label": "Qty", "value": "0"}, {"label": "Urgent", "value": "No"}],
        )

    def test_no_value_anywhere_gives_an_empty_list(self):
        fields = [_field("a"), _field("b", "Currency")]
        self.assertEqual(key_facts(fields, {}, 3), [])
        self.assertEqual(key_facts([], {"a": 1}, 3), [])

    def test_a_complex_value_is_dropped_without_using_up_a_slot(self):
        fields = [_field("blob")] + [_field(f"f{i}") for i in range(8)]
        doc = {"blob": {"a": 1}, **{f"f{i}": f"v{i}" for i in range(8)}}
        facts = key_facts(fields, doc, 3)
        self.assertEqual(len(facts), 8)
        self.assertNotIn("Blob", [fact["label"] for fact in facts])

    def test_values_are_formatted_by_field_type(self):
        fields = [_field("grand_total", "Currency"), _field("is_return", "Check")]
        doc = {"grand_total": 1200, "is_return": 1}
        self.assertEqual(
            key_facts(fields, doc, 3),
            [
                {"label": "Grand Total", "value": "1,200.000"},
                {"label": "Is Return", "value": "Yes"},
            ],
        )

    def test_a_missing_label_falls_back_to_the_fieldname(self):
        field = SimpleNamespace(fieldname="supplier", fieldtype="Link")
        self.assertEqual(
            key_facts([field], {"supplier": "SUP-1"}, 0),
            [{"label": "supplier", "value": "SUP-1"}],
        )

    def test_a_bare_field_object_needs_only_a_name_and_type(self):
        field = SimpleNamespace(fieldname="title", fieldtype="Data")
        self.assertEqual(
            key_facts([field], {"title": "Rent"}, 0),
            [{"label": "title", "value": "Rent"}],
        )


class TestLineTables(unittest.TestCase):
    def test_the_doctypes_and_their_child_tables(self):
        self.assertEqual(
            {doctype: table for doctype, (table, _cols) in LINE_TABLES.items()},
            {
                "Journal Entry": "accounts",
                "Purchase Invoice": "items",
                "Purchase Order": "items",
                "Sales Invoice": "items",
                "Sales Order": "items",
                "Quotation": "items",
                "Payment Entry": "references",
                "Stock Reconciliation": "items",
            },
        )

    def test_the_columns_of_each_doctype(self):
        fieldnames = {
            doctype: [name for name, _header in cols]
            for doctype, (_table, cols) in LINE_TABLES.items()
        }
        self.assertEqual(
            fieldnames["Journal Entry"],
            ["account", "debit_in_account_currency", "credit_in_account_currency"],
        )
        for doctype in (
            "Purchase Invoice", "Purchase Order", "Sales Invoice",
            "Sales Order", "Quotation",
        ):  # fmt: skip
            self.assertEqual(fieldnames[doctype], ["item_name", "qty", "amount"])
        self.assertEqual(
            fieldnames["Payment Entry"],
            ["reference_doctype", "reference_name", "allocated_amount"],
        )
        self.assertEqual(
            fieldnames["Stock Reconciliation"],
            ["item_code", "qty", "valuation_rate"],
        )


class TestFirstLines(unittest.TestCase):
    def _journal_entry(self, rows: int) -> dict:
        return {
            "accounts": [
                {
                    "account": f"Account {i}",
                    "debit_in_account_currency": 100 * i,
                    "credit_in_account_currency": 0,
                }
                for i in range(1, rows + 1)
            ]
        }

    def test_journal_entry_with_five_rows_gives_three_and_the_total(self):
        lines = first_lines("Journal Entry", self._journal_entry(5), 3)
        self.assertEqual(lines["columns"], ["Account", "Debit", "Credit"])
        self.assertEqual(len(lines["rows"]), 3)
        self.assertEqual(lines["total"], 5)

    def test_rows_are_lists_of_formatted_strings_in_column_order(self):
        lines = first_lines("Journal Entry", self._journal_entry(2), 3)
        self.assertEqual(
            lines["rows"],
            [
                ["Account 1", "100.000", "0.000"],
                ["Account 2", "200.000", "0.000"],
            ],
        )

    def test_the_limit_can_be_changed(self):
        lines = first_lines("Journal Entry", self._journal_entry(5), 3, limit=5)
        self.assertEqual(len(lines["rows"]), 5)
        self.assertEqual(lines["total"], 5)

    def test_fewer_rows_than_the_limit(self):
        lines = first_lines("Journal Entry", self._journal_entry(2), 2)
        self.assertEqual(len(lines["rows"]), 2)
        self.assertEqual(lines["total"], 2)

    def test_text_cells_pass_through_and_a_missing_value_is_blank(self):
        doc = {
            "references": [
                {
                    "reference_doctype": "Purchase Invoice",
                    "reference_name": "PINV-0001",
                    "allocated_amount": 1500,
                },
                {"reference_doctype": "Journal Entry", "allocated_amount": None},
            ]
        }
        lines = first_lines("Payment Entry", doc, 2)
        self.assertEqual(lines["columns"], ["Type", "Reference", "Allocated"])
        self.assertEqual(
            lines["rows"],
            [
                ["Purchase Invoice", "PINV-0001", "1,500.00"],
                ["Journal Entry", "", ""],
            ],
        )

    def test_a_doctype_without_a_line_table_gives_the_empty_shape(self):
        self.assertEqual(
            first_lines("Customer", {}, 3),
            {"columns": [], "rows": [], "total": 0},
        )

    def test_a_known_doctype_with_no_rows_gives_the_empty_shape(self):
        empty = {"columns": [], "rows": [], "total": 0}
        self.assertEqual(first_lines("Journal Entry", {}, 3), empty)
        self.assertEqual(first_lines("Journal Entry", {"accounts": []}, 3), empty)
        self.assertEqual(first_lines("Journal Entry", {"accounts": None}, 3), empty)

    def test_the_result_does_not_share_state_with_the_module(self):
        lines = first_lines("Journal Entry", self._journal_entry(1), 3)
        lines["columns"].append("Tampered")
        again = first_lines("Journal Entry", self._journal_entry(1), 3)
        self.assertEqual(again["columns"], ["Account", "Debit", "Credit"])


if __name__ == "__main__":
    unittest.main()
