# vansale/sf_trading/api/test_loyalty_reward_rows.py
"""The row Custom Field's mandatory_depends_on is client-side only; the server rule lives here.

Nothing is saved: each test builds an unsaved Journal Entry and calls the validate handler
directly, so a client site's live ledger is never touched.
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import nowdate

from vansale.sf_trading.api.loyalty_reward_rows import TEMPLATE, validate_loyalty_reward_rows

REWARD_ACCOUNT = "Loyalty Rewards"
FUNDING_ACCOUNT = "Petty Cash"


class TestLoyaltyRewardRowLink(FrappeTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = frappe.db.get_single_value("Global Defaults", "default_company") or frappe.db.get_value(
            "Company", {}, "name"
        )

    def _journal(self, rows, template=TEMPLATE, docstatus=0):
        journal = frappe.new_doc("Journal Entry")
        journal.update(
            {
                "company": self.company,
                "posting_date": nowdate(),
                "voucher_type": "Journal Entry",
                "from_template": template,
                "docstatus": docstatus,
            }
        )
        for row in rows:
            journal.append("accounts", row)
        return journal

    # ── the rule ──────────────────────────────────────────────────────────────────

    def test_debit_row_without_an_invoice_is_rejected(self):
        journal = self._journal(
            [
                {"account": REWARD_ACCOUNT, "debit": 5.0, "debit_in_account_currency": 5.0},
                {"account": FUNDING_ACCOUNT, "credit": 5.0, "credit_in_account_currency": 5.0},
            ]
        )
        with self.assertRaises(frappe.ValidationError):
            validate_loyalty_reward_rows(journal)

    def test_debit_row_with_an_invoice_passes(self):
        journal = self._journal(
            [
                {
                    "account": REWARD_ACCOUNT,
                    "debit": 5.0,
                    "debit_in_account_currency": 5.0,
                    "custom_loyalty_sales_invoice": "SI-TEST-0001",
                },
                {"account": FUNDING_ACCOUNT, "credit": 5.0, "credit_in_account_currency": 5.0},
            ]
        )
        validate_loyalty_reward_rows(journal)

    def test_credit_only_row_needs_no_invoice(self):
        """The funding side rewards nobody, so it is never asked for an invoice."""
        journal = self._journal(
            [{"account": FUNDING_ACCOUNT, "credit": 5.0, "credit_in_account_currency": 5.0}]
        )
        validate_loyalty_reward_rows(journal)

    def test_debit_in_account_currency_alone_still_requires_the_invoice(self):
        """`debit` is derived and stays 0 when exchange_rate is unset — the entered figure counts."""
        journal = self._journal(
            [{"account": REWARD_ACCOUNT, "debit": 0, "debit_in_account_currency": 5.0}]
        )
        with self.assertRaises(frappe.ValidationError):
            validate_loyalty_reward_rows(journal)

    def test_error_names_every_offending_row(self):
        journal = self._journal(
            [
                {"account": REWARD_ACCOUNT, "debit": 5.0, "debit_in_account_currency": 5.0},
                {"account": FUNDING_ACCOUNT, "credit": 8.0, "credit_in_account_currency": 8.0},
                {"account": REWARD_ACCOUNT, "debit": 3.0, "debit_in_account_currency": 3.0},
            ]
        )
        with self.assertRaises(frappe.ValidationError) as caught:
            validate_loyalty_reward_rows(journal)
        message = str(caught.exception)
        self.assertIn("Row #1", message)
        self.assertIn("Row #3", message)
        self.assertNotIn("Row #2", message)

    # ── what the rule must leave alone ────────────────────────────────────────────

    def test_journals_from_other_templates_are_untouched(self):
        unlinked_debit = [{"account": REWARD_ACCOUNT, "debit": 5.0, "debit_in_account_currency": 5.0}]
        validate_loyalty_reward_rows(self._journal(unlinked_debit, template=None))
        validate_loyalty_reward_rows(self._journal(unlinked_debit, template="Expense JV (Petty Cash)"))

    def test_cancelled_journal_is_not_validated(self):
        journal = self._journal(
            [{"account": REWARD_ACCOUNT, "debit": 5.0, "debit_in_account_currency": 5.0}], docstatus=2
        )
        validate_loyalty_reward_rows(journal)
