# apps/vansale/vansale/sf_trading/doctype/payment_automation_settings/payment_automation_settings.py
"""Payment Automation Settings — one configuration per company + party type.

Holds *when* a run happens (weekdays + a time of day) and *how far* it goes: create the
advice, submit it, create the Payment Entry, submit that. Each step is gated by the one
before it, and by its own money threshold, so a configuration can be tightened without
touching code.

The engine lives in `vansale/sf_trading/api/payment_automation.py`; this controller only validates
that a configuration makes sense before it is allowed to run.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt

WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


class PaymentAutomationSettings(Document):
    def autoname(self):
        """One configuration per company + party type, named from the company abbreviation.

        Deterministic on purpose: it makes a duplicate configuration for the same company
        and party type impossible, which is what would otherwise let two runs pay the same
        invoices. The abbreviation is used rather than the company name so spaces and
        characters like & or / never reach the primary key or the URL.
        """
        abbr = frappe.db.get_value("Company", self.company, "abbr") or frappe.scrub(
            self.company or ""
        )
        self.name = "PAS-%s-%s" % (abbr, self.party_type or "Supplier")

    def validate(self):
        self.validate_level_chain()
        self.validate_schedule()
        self.validate_thresholds()
        self.validate_accounts()
        self.set_title()

    def validate_level_chain(self):
        """A later step without its predecessor is a configuration mistake, not a feature."""
        if cint(self.auto_submit_advice) and not cint(self.auto_create_advice):
            frappe.throw(_("Submitting advices requires creating them first."))

        if cint(self.auto_create_payment_entry) and not cint(self.auto_submit_advice):
            frappe.throw(
                _("A Payment Entry can only be raised from a submitted advice, so enable step 2 first.")
            )

        if cint(self.auto_submit_payment_entry) and not cint(self.auto_create_payment_entry):
            frappe.throw(_("Submitting Payment Entries requires creating them first."))

        # Payment Advice.before_submit demands an approver; without one every automated
        # submit would fail mid-run, after the advices had already been created.
        if cint(self.auto_submit_advice) and not self.approver:
            frappe.throw(_("Set an Approver before letting the run submit advices."))

        # the approver is stamped on every advice the run raises; a disabled user makes those
        # advices unsubmittable by a human afterwards
        if self.approver and not frappe.db.get_value("User", self.approver, "enabled"):
            frappe.throw(
                _("User %s is disabled, so nobody could submit the advices this run stamps. "
                  "Pick an active approver.") % frappe.bold(self.approver)
            )

    def validate_schedule(self):
        if not cint(self.enabled):
            return

        if not any(cint(self.get("automate_on_" + day)) for day in WEEKDAYS):
            frappe.throw(_("Pick at least one weekday, or untick Enabled."))

        if not self.processing_time:
            frappe.throw(_("Set a processing time."))

    def validate_thresholds(self):
        if flt(self.minimum_amount) < 0:
            frappe.throw(_("Minimum Amount cannot be negative."))

        if cint(self.max_parties_per_run) <= 0:
            frappe.throw(_("Max Parties Per Run must be at least 1."))

        if (
            flt(self.advice_threshold)
            and flt(self.minimum_amount)
            and flt(self.minimum_amount) > flt(self.advice_threshold)
        ):
            frappe.throw(
                _("Minimum Amount is above the Advice Threshold, so every party would be skipped.")
            )

    def validate_accounts(self):
        if self.bank_account:
            values = frappe.db.get_value(
                "Bank Account", self.bank_account, ["company", "is_company_account"], as_dict=True
            )
            if values and values.company and values.company != self.company:
                frappe.throw(
                    _("Bank Account %(account)s belongs to %(other)s, not %(company)s.")
                    % {
                        "account": frappe.bold(self.bank_account),
                        "other": frappe.bold(values.company),
                        "company": frappe.bold(self.company),
                    }
                )
            if values and not cint(values.is_company_account):
                frappe.throw(_("Pick a company bank account, not a party's."))

        if self.cost_center:
            cc_company = frappe.db.get_value("Cost Center", self.cost_center, "company")
            if cc_company and cc_company != self.company:
                frappe.throw(
                    _("Cost Center %(cc)s belongs to %(other)s.")
                    % {"cc": frappe.bold(self.cost_center), "other": frappe.bold(cc_company)}
                )

        if cint(self.auto_submit_payment_entry) and not (self.bank_account or self.mode_of_payment):
            frappe.throw(
                _("Set a Mode of Payment or Bank Account before letting the run submit Payment Entries.")
            )

    def set_title(self):
        if not self.title:
            self.title = _("%(party_type)s payments — %(company)s") % {
                "party_type": _(self.party_type or "Supplier"),
                "company": self.company,
            }

    # ── helpers used by the engine ───────────────────────────────────────────────
    def runs_today(self, weekday_name):
        return bool(cint(self.get("automate_on_" + weekday_name.lower())))

    def notify_role_names(self):
        return [row.role for row in (self.notify_roles or []) if row.role]

    def highest_enabled_step(self):
        if cint(self.auto_submit_payment_entry):
            return 4
        if cint(self.auto_create_payment_entry):
            return 3
        if cint(self.auto_submit_advice):
            return 2
        if cint(self.auto_create_advice):
            return 1
        return 0
