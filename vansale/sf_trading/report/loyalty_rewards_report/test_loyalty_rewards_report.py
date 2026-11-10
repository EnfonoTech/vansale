# apps/vansale/vansale/sf_trading/report/loyalty_rewards_report/test_loyalty_rewards_report.py
"""Tests for the Loyalty Rewards Report.

Read-only against live data: the report never writes. Reward vouchers are few, so the
tests assert filter behaviour, the two sources (template journals + payment deductions),
the linked/unlinked split, the reward split arithmetic, summary arithmetic and column
shape rather than fabricating vouchers on a client site.

Both sides are now one row per reward row — per allocated invoice for a payment, per debit row
for a journal — so a voucher legitimately appears on several rows and the tests reconcile rows
back to the voucher rather than assuming one each.
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_months, flt, nowdate

from vansale.sf_trading.report.loyalty_rewards_report.loyalty_rewards_report import (
    SOURCE_JOURNAL,
    SOURCE_PAYMENT,
    TEMPLATE,
    UNLINKED_LABEL,
    _split_reward,
    _template_accounts,
    execute,
    summarise,
)


class TestLoyaltyRewardsReport(FrappeTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = frappe.db.get_single_value("Global Defaults", "default_company") or frappe.db.get_value(
            "Company", {}, "name"
        )

    def _run(self, **filters):
        base = {
            "company": self.company,
            "from_date": add_months(nowdate(), -24),
            "to_date": nowdate(),
            "journal_template": TEMPLATE,
            "status": "All",
        }
        base.update(filters)
        return execute(base)

    def test_detail_columns(self):
        columns, _rows = self._run()
        fieldnames = [c["fieldname"] for c in columns]
        for expected in (
            "source",
            "voucher_no",
            "row_idx",
            "reward_amount",
            "sales_invoice",
            "allocated_amount",
            "customer",
            "invoice_total",
            "reward_pct",
        ):
            self.assertIn(expected, fieldnames)

    def test_voucher_column_is_dynamically_linked_to_the_source(self):
        columns, _rows = self._run()
        voucher = next(c for c in columns if c["fieldname"] == "voucher_no")
        self.assertEqual(voucher["fieldtype"], "Dynamic Link")
        self.assertEqual(voucher["options"], "source")

    def test_every_row_names_a_source_and_its_voucher(self):
        _columns, rows = self._run()
        for row in rows:
            self.assertIn(row["source"], (SOURCE_JOURNAL, SOURCE_PAYMENT))
            self.assertTrue(frappe.db.exists(row["source"], row["voucher_no"]))
            self.assertGreaterEqual(row["reward_amount"], 0)

    def test_journal_rows_come_from_the_template(self):
        _columns, rows = self._run(source=SOURCE_JOURNAL)
        for row in rows:
            self.assertEqual(row["source"], SOURCE_JOURNAL)
            self.assertEqual(
                frappe.db.get_value("Journal Entry", row["journal_entry"], "from_template"), TEMPLATE
            )

    def test_journal_rewards_add_up_to_the_journal_debit(self):
        """However many debit rows a journal has, its rows sum back to the amount booked."""
        _columns, rows = self._run(source=SOURCE_JOURNAL)
        by_journal = {}
        for row in rows:
            by_journal.setdefault(row["journal_entry"], 0.0)
            by_journal[row["journal_entry"]] += flt(row["reward_amount"])

        for journal, reward in list(by_journal.items())[:20]:
            total_debit = frappe.db.get_value("Journal Entry", journal, "total_debit")
            self.assertAlmostEqual(reward, flt(total_debit), places=2)

    def test_journal_rows_carry_their_own_row_debit(self):
        """Each row reports its own debit — never the whole voucher repeated per row."""
        _columns, rows = self._run(source=SOURCE_JOURNAL)
        checked = 0
        for row in rows:
            if row.get("row_idx") is None:
                continue
            debit = frappe.db.get_value(
                "Journal Entry Account",
                {"parent": row["voucher_no"], "idx": row["row_idx"]},
                "debit",
            )
            self.assertAlmostEqual(flt(row["reward_amount"]), flt(debit), places=3)
            checked += 1
            if checked == 20:
                break

    def test_journal_rows_carry_their_row_invoice(self):
        """The row's own link wins; the header link is only a fallback."""
        _columns, rows = self._run(source=SOURCE_JOURNAL)
        checked = 0
        for row in rows:
            if row.get("row_idx") is None:
                continue
            row_link = frappe.db.get_value(
                "Journal Entry Account",
                {"parent": row["voucher_no"], "idx": row["row_idx"]},
                "custom_loyalty_sales_invoice",
            )
            header_link = frappe.db.get_value(
                "Journal Entry", row["voucher_no"], "custom_loyalty_sales_invoice"
            )
            self.assertEqual(row["sales_invoice"], row_link or header_link)
            checked += 1
            if checked == 20:
                break

    def test_one_journal_can_reward_several_invoices(self):
        """The point of the row-level link: one voucher, several customers' invoices."""
        candidates = {}
        for account_row in frappe.get_all(
            "Journal Entry Account",
            filters={"parenttype": SOURCE_JOURNAL, "custom_loyalty_sales_invoice": ["is", "set"]},
            fields=["parent", "custom_loyalty_sales_invoice"],
        ):
            if frappe.db.get_value("Journal Entry", account_row.parent, "from_template") != TEMPLATE:
                continue
            candidates.setdefault(account_row.parent, set()).add(account_row.custom_loyalty_sales_invoice)

        multi = next((je for je, invoices in candidates.items() if len(invoices) > 1), None)
        if not multi:
            self.skipTest("no multi-invoice reward journal on this site")

        _columns, rows = self._run(source=SOURCE_JOURNAL)
        mine = [row for row in rows if row["voucher_no"] == multi]
        self.assertGreaterEqual(len(mine), 2)
        self.assertEqual(len({row["sales_invoice"] for row in mine}), len(mine))
        self.assertAlmostEqual(
            sum(flt(row["reward_amount"]) for row in mine),
            flt(frappe.db.get_value("Journal Entry", multi, "total_debit")),
            places=2,
        )

    def test_only_unlinked_returns_rows_not_vouchers(self):
        """A part-linked journal contributes only its unlinked rows."""
        part_linked = None
        for journal in frappe.get_all(
            "Journal Entry", filters={"from_template": TEMPLATE}, pluck="name"
        ):
            debit_rows = [
                account_row
                for account_row in frappe.get_all(
                    "Journal Entry Account",
                    filters={"parent": journal},
                    fields=["idx", "debit", "custom_loyalty_sales_invoice"],
                )
                if flt(account_row.debit)
            ]
            linked = [r for r in debit_rows if r.custom_loyalty_sales_invoice]
            unlinked = [r for r in debit_rows if not r.custom_loyalty_sales_invoice]
            if linked and unlinked:
                part_linked = (journal, linked, unlinked)
                break

        if not part_linked:
            self.skipTest("no part-linked reward journal on this site")

        journal, linked, _unlinked = part_linked
        _columns, rows = self._run(only_unlinked=1)
        mine = [row for row in rows if row["voucher_no"] == journal]
        self.assertTrue(mine)
        for row in mine:
            self.assertFalse(row["sales_invoice"])
        returned = {row["row_idx"] for row in mine}
        for linked_row in linked:
            self.assertNotIn(linked_row.idx, returned)

    def test_payment_rows_sit_on_the_template_account(self):
        """A payment row exists only because the PE deducts to the template's account."""
        accounts = _template_accounts(TEMPLATE)
        _columns, rows = self._run(source=SOURCE_PAYMENT)
        for row in rows[:20]:
            self.assertEqual(row["source"], SOURCE_PAYMENT)
            for account in (row["reward_account"] or "").split(", "):
                self.assertIn(account, accounts)

    def test_payment_rows_carry_their_invoice_allocation(self):
        _columns, rows = self._run(source=SOURCE_PAYMENT)
        for row in rows[:20]:
            self.assertTrue(row["sales_invoice"])
            allocated = frappe.db.get_value(
                "Payment Entry Reference",
                {
                    "parent": row["payment_entry"],
                    "reference_doctype": "Sales Invoice",
                    "reference_name": row["sales_invoice"],
                },
                "allocated_amount",
            )
            self.assertAlmostEqual(flt(row["allocated_amount"]), flt(allocated), places=3)

    def test_payment_rewards_add_up_to_the_deduction(self):
        """However many invoices a payment settles, the split matches the deduction."""
        _columns, rows = self._run(source=SOURCE_PAYMENT)
        by_payment = {}
        for row in rows:
            by_payment.setdefault(row["payment_entry"], 0.0)
            by_payment[row["payment_entry"]] += flt(row["reward_amount"])

        accounts = _template_accounts(TEMPLATE)
        for payment, reward in list(by_payment.items())[:20]:
            booked = sum(
                flt(d.amount)
                for d in frappe.get_all(
                    "Payment Entry Deduction",
                    filters={"parent": payment, "account": ["in", accounts]},
                    fields=["amount"],
                )
            )
            self.assertAlmostEqual(reward, booked, places=3)

    def test_split_reward_single_reference_keeps_the_whole_amount(self):
        refs = [frappe._dict({"reference_name": "SI-1", "allocated_amount": 100.0})]
        self.assertEqual(_split_reward(0.027, refs), [("SI-1", 100.0, 0.027)])

    def test_split_reward_follows_allocation_and_keeps_the_total(self):
        refs = [
            frappe._dict({"reference_name": "SI-1", "allocated_amount": 75.0}),
            frappe._dict({"reference_name": "SI-2", "allocated_amount": 25.0}),
        ]
        split = _split_reward(1.0, refs)
        self.assertEqual([s[0] for s in split], ["SI-1", "SI-2"])
        self.assertAlmostEqual(split[0][2], 0.75, places=3)
        self.assertAlmostEqual(sum(s[2] for s in split), 1.0, places=3)

    def test_split_reward_without_references_still_reports_the_reward(self):
        self.assertEqual(_split_reward(0.5, []), [(None, None, 0.5)])

    def test_source_filter_isolates_each_side(self):
        _columns, journals = self._run(source=SOURCE_JOURNAL)
        _columns, payments = self._run(source=SOURCE_PAYMENT)
        _columns, both = self._run()
        self.assertTrue(all(row["source"] == SOURCE_JOURNAL for row in journals))
        self.assertTrue(all(row["source"] == SOURCE_PAYMENT for row in payments))
        self.assertEqual(len(both), len(journals) + len(payments))

    def test_only_unlinked_filter(self):
        """Unchanged on purpose: it specifies that unlinked *rows* carry no invoice/customer."""
        _columns, rows = self._run(only_unlinked=1)
        for row in rows:
            self.assertEqual(row["source"], SOURCE_JOURNAL)
            self.assertFalse(row["sales_invoice"])
            self.assertIsNone(row["customer"])

    def test_linked_rows_carry_customer(self):
        _columns, rows = self._run()
        for row in rows:
            if row["sales_invoice"]:
                self.assertEqual(
                    row["customer"],
                    frappe.db.get_value("Sales Invoice", row["sales_invoice"], "customer"),
                )

    def test_min_amount_filter(self):
        _columns, rows = self._run(min_amount=1)
        for row in rows:
            self.assertGreaterEqual(row["reward_amount"], 1)

    def test_status_filter_draft_only(self):
        _columns, rows = self._run(status="Draft")
        for row in rows:
            self.assertEqual(row["status"], "Draft")

    def test_rows_are_newest_first(self):
        _columns, rows = self._run()
        dates = [row["posting_date"] for row in rows if row["posting_date"]]
        self.assertEqual(dates, sorted(dates, reverse=True))

    def test_summary_totals_match_detail(self):
        _columns, rows = self._run()
        summary = summarise(rows)
        self.assertAlmostEqual(
            sum(s["reward_amount"] for s in summary),
            sum(r["reward_amount"] for r in rows),
            places=2,
        )
        # "Reward Vouchers" counts distinct vouchers per customer bucket, so it can be fewer
        # than the number of rows — a voucher spanning several rows counts once in each bucket
        expected = len(
            {(row.get("customer") or UNLINKED_LABEL, row["source"], row["voucher_no"]) for row in rows}
        )
        self.assertEqual(sum(s["journals"] for s in summary), expected)
        self.assertLessEqual(sum(s["journals"] for s in summary), len(rows))

    def test_summary_splits_reward_by_source(self):
        _columns, rows = self._run()
        summary = summarise(rows)
        for bucket in summary:
            self.assertAlmostEqual(
                bucket["journal_reward"] + bucket["payment_reward"], bucket["reward_amount"], places=2
            )
        self.assertAlmostEqual(
            sum(s["payment_reward"] for s in summary),
            sum(r["reward_amount"] for r in rows if r["source"] == SOURCE_PAYMENT),
            places=2,
        )

    def test_summary_groups_unlinked(self):
        rows = [
            {"source": SOURCE_JOURNAL, "voucher_no": "JE-1", "customer": None, "customer_name": None,
             "sales_invoice": None, "reward_amount": 5.0, "invoice_total": 0.0},
            {"source": SOURCE_JOURNAL, "voucher_no": "JE-2", "customer": None, "customer_name": None,
             "sales_invoice": None, "reward_amount": 2.5, "invoice_total": 0.0},
        ]
        summary = summarise(rows)
        self.assertEqual(len(summary), 1)
        self.assertEqual(summary[0]["customer_name"], UNLINKED_LABEL)
        self.assertEqual(summary[0]["journals"], 2)
        self.assertAlmostEqual(summary[0]["reward_amount"], 7.5, places=2)
        self.assertEqual(summary[0]["invoices"], 0)

    def test_summary_counts_each_invoice_once(self):
        """A journal and a payment reward against the same invoice must not double it."""
        rows = [
            {"source": SOURCE_JOURNAL, "voucher_no": "JE-1", "customer": "CUST-1", "customer_name": "One",
             "sales_invoice": "SI-1", "reward_amount": 3.0, "invoice_total": 100.0},
            {"source": SOURCE_PAYMENT, "voucher_no": "PE-1", "customer": "CUST-1", "customer_name": "One",
             "sales_invoice": "SI-1", "reward_amount": 2.0, "invoice_total": 100.0},
        ]
        summary = summarise(rows)
        self.assertEqual(summary[0]["invoices"], 1)
        self.assertEqual(summary[0]["journals"], 2)
        self.assertAlmostEqual(summary[0]["invoice_total"], 100.0, places=2)
        self.assertAlmostEqual(summary[0]["reward_amount"], 5.0, places=2)
        self.assertAlmostEqual(summary[0]["journal_reward"], 3.0, places=2)
        self.assertAlmostEqual(summary[0]["payment_reward"], 2.0, places=2)
        self.assertAlmostEqual(summary[0]["reward_pct"], 5.0, places=2)

    def test_summary_columns_shape(self):
        columns, _rows = self._run(summarise_by_customer=1)
        fieldnames = [c["fieldname"] for c in columns]
        self.assertEqual(
            fieldnames,
            [
                "customer",
                "customer_name",
                "journals",
                "invoices",
                "reward_amount",
                "journal_reward",
                "payment_reward",
                "invoice_total",
                "reward_pct",
            ],
        )
