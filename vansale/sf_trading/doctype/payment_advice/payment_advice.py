# apps/vansale/vansale/sf_trading/doctype/payment_advice/payment_advice.py
"""Payment Advice — authorise payment against several outstanding documents of one party.

A Payment Advice groups many references (Purchase Invoices, Sales Invoices, Expense Claims…)
for a SINGLE party and carries one authorised `payment_amount`, allocated across those
references in row order. Submitting it records approval; creating the Payment Entry turns it
into money movement. This is what ERPNext's Payment Request cannot express: PR is
one-document-per-request, so it cannot say "pay these nine invoices for this supplier".

Ported from EnfonoTech/payment_advice (MIT) and corrected. Fixes versus that app:
  * Payment Entry takes `company` from THIS document instead of the session user's default.
  * `get_exchange_rate()` is called as (from_currency, to_currency, date) — the original
    passed `company` as the target currency, so every multi-currency advice was wrong.
  * All money maths goes through `flt()`; nulls no longer raise or write None amounts.
  * Allocation stops once the authorised amount is exhausted instead of appending
    zero-allocation reference rows, which ERPNext rejects.
  * The Payment Entry is finished with `set_missing_values()`, so base amounts, party balance
    and unallocated amount are computed by ERPNext instead of left unset.
  * The whitelisted endpoint checks permissions and no longer inserts with
    `ignore_permissions=True`.
  * Party and company account lookups use ERPNext's own helpers.
  * The advice is stamped with its Payment Entry on the PE's `on_submit` (cleared on
    `on_cancel`), not in `before_submit` — a failed submit can no longer leave a false link.
  * Adds a real `status` lifecycle and a `payment_entry` Link (was a free-text Data field).
  * Every user-facing string is translatable.

No SQL is constructed here: reads go through frappe.db.get_value / frappe.get_all.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, cint, flt, getdate, get_link_to_form, money_in_words, nowdate

from erpnext.accounts.party import get_party_account
from erpnext.setup.utils import get_exchange_rate

PAY_PARTY_TYPES = ("Supplier",)
RECEIVE_PARTY_TYPES = ("Customer",)
PARTY_TYPES = PAY_PARTY_TYPES + RECEIVE_PARTY_TYPES

# ── Approval routing ──────────────────────────────────────────────────────────────────
# Which approvers an advice needs depends on what it pays for. The decision is worked out
# here and stored on the document, because the approval workflow's conditions run through
# frappe.safe_eval with a deliberately tiny globals set — no len(), no flt(), no way to walk
# the references table. A condition can compare a stored string and nothing more.
ROUTE_ACCOUNTANT = "Accountant"            # straight to the Bahrain Accountant
ROUTE_PURCHASE_MANAGER = "Purchase Manager"  # several POs: Purchase Manager, then Finance
ROUTE_HO_ACCOUNTS = "HO Accounts"          # overdue invoices: HO Accounts, then Finance
ROUTE_FINANCE = "Finance"                  # over the limit: GM or Finance Manager

# Above this, an advice against invoices that are not overdue still needs GM/Finance sign-off.
# The rule is "more than BHD 500", so the limit itself goes straight through.
FINANCE_APPROVAL_LIMIT = 500.0

# Reference types per party type, copied from ERPNext's own Payment Entry
# (PaymentEntry.get_valid_reference_doctypes) so an advice can never carry a reference its
# Payment Entry would later reject. Enforced server-side as well as in the form, because a
# Dynamic Link accepts any DocType name over the API otherwise.
VALID_REFERENCE_DOCTYPES = {
    "Customer": ("Sales Order", "Sales Invoice", "Journal Entry", "Dunning"),
    "Supplier": ("Purchase Order", "Purchase Invoice", "Journal Entry"),
}

ORDER_DOCTYPES = ("Sales Order", "Purchase Order")

ALLOWED_REFERENCE_DOCTYPES = tuple(
    sorted({dt for types in VALID_REFERENCE_DOCTYPES.values() for dt in types})
)


def valid_reference_doctypes(party_type):
    """What this party type may be paid against — identical to Payment Entry's list."""
    return VALID_REFERENCE_DOCTYPES.get(party_type, ())

STATUS_DRAFT = "Draft"
STATUS_PENDING = "Pending Approval"
STATUS_APPROVED = "Approved"
STATUS_PARTLY_PAID = "Partly Paid"
STATUS_PAID = "Paid"
STATUS_CANCELLED = "Cancelled"

PARTY_NAME_FIELD = {
    "Supplier": "supplier_name",
    "Customer": "customer_name",
}


class PaymentAdvice(Document):
    # ── lifecycle ────────────────────────────────────────────────────────────────
    def validate(self):
        self.set_advice_type()
        self.validate_references()
        self.set_defaults_from_references()
        self.set_party_name()
        self.set_reference_details()
        self.compute_totals()
        self.validate_transaction_reference()
        self.validate_payment_amount()
        self.allocate_payment()
        self.report_payable_changes()
        self.set_words()
        self.set_approval_route()
        self.set_status()

    def set_approval_route(self):
        """Stamp which approval route this advice takes, for the workflow to read.

        Only the part that cannot be expressed in a PM Workflow condition is decided here -
        counting orders and looking for an overdue invoice both need to walk the child rows,
        and conditions are evaluated by frappe.safe_eval with no len() and no loops. The
        amount rules, including who may send their own advice straight through, are conditions
        on the transitions, where they can be read and changed without a deployment.
        """
        if self.meta.has_field("approval_route"):
            self.approval_route = compute_approval_route(self)

    def before_submit(self):
        self.validate_approver()

    def on_submit(self):
        self.db_set("status", STATUS_APPROVED, update_modified=False)

    def on_cancel(self):
        if self.payment_entry:
            docstatus = frappe.db.get_value("Payment Entry", self.payment_entry, "docstatus")
            if cint(docstatus) == 1:
                frappe.throw(
                    _("Cancel Payment Entry %s before cancelling this advice.")
                    % frappe.bold(self.payment_entry)
                )
        self.db_set("status", STATUS_CANCELLED, update_modified=False)
        # the vouchers are free again — make sure their status on this advice reads true
        refresh_reference_status(self.name)

    def set_advice_type(self):
        """Inward collects from a customer, Outward pays a supplier.

        Derived here rather than left to the form: the builder, the invoice-list action and the
        automation all insert advices without any client script, and a customer advice was being
        stored as Outward through those paths.
        """
        self.payment_advice_type = (
            "Inward" if self.party_type in RECEIVE_PARTY_TYPES else "Outward"
        )

    # ── reference integrity ──────────────────────────────────────────────────────
    def validate_references(self):
        """Dynamic Link safety: right doctype, right company, right party, no doubles.

        The form filters these pickers, but a Dynamic Link will accept anything over the
        API, so every rule is enforced here too.
        """
        seen = {}

        for row in self.payment_advice_reference:
            if not (row.reference_doctype and row.reference_record):
                frappe.throw(
                    _("Row #%s: select both a reference type and a reference document.") % row.idx
                )

            allowed = valid_reference_doctypes(self.party_type)
            if row.reference_doctype not in allowed:
                frappe.throw(
                    _("Row #%(idx)s: a %(party_type)s advice cannot reference a %(dt)s. Allowed: %(allowed)s")
                    % {
                        "idx": row.idx,
                        "party_type": _(self.party_type or ""),
                        "dt": _(row.reference_doctype),
                        "allowed": ", ".join(_(d) for d in allowed),
                    }
                )

            if not frappe.db.exists(row.reference_doctype, row.reference_record):
                frappe.throw(
                    _("Row #%(idx)s: %(dt)s %(name)s does not exist.")
                    % {
                        "idx": row.idx,
                        "dt": _(row.reference_doctype),
                        "name": frappe.bold(row.reference_record),
                    }
                )

            key = (row.reference_doctype, row.reference_record)
            if key in seen:
                frappe.throw(
                    _("Row #%(idx)s: %(name)s is already on row #%(other)s.")
                    % {"idx": row.idx, "name": frappe.bold(row.reference_record), "other": seen[key]}
                )
            seen[key] = row.idx

            meta = frappe.get_meta(row.reference_doctype)
            values = frappe.db.get_value(
                row.reference_doctype,
                row.reference_record,
                ["docstatus", "company"] + ([self.party_field()] if meta.has_field(self.party_field()) else []),
                as_dict=True,
            ) or frappe._dict()

            if cint(values.get("docstatus")) != 1:
                frappe.throw(
                    _("Row #%(idx)s: %(name)s is not submitted.")
                    % {"idx": row.idx, "name": frappe.bold(row.reference_record)}
                )

            if values.get("company") and values.get("company") != self.company:
                frappe.throw(
                    _("Row #%(idx)s: %(name)s belongs to company %(other)s, not %(company)s.")
                    % {
                        "idx": row.idx,
                        "name": frappe.bold(row.reference_record),
                        "other": frappe.bold(values.get("company")),
                        "company": frappe.bold(self.company),
                    }
                )

            row_party = values.get(self.party_field())
            if row_party and row_party != self.party:
                frappe.throw(
                    _("Row #%(idx)s: %(name)s belongs to %(other)s, not %(party)s.")
                    % {
                        "idx": row.idx,
                        "name": frappe.bold(row.reference_record),
                        "other": frappe.bold(row_party),
                        "party": frappe.bold(self.party),
                    }
                )

        self.validate_not_advised_elsewhere()

    def set_defaults_from_references(self):
        """Inherit branch and cost centre from the vouchers being paid.

        Every voucher in this system carries a branch, and Branch Configuration holds that
        branch's cost centre — so the branch is the source of truth, not a guess. Only blank
        fields are filled, so a deliberate choice is never overwritten.

        Mode of payment is deliberately NOT inherited: Purchase Invoice carries a real Mode of
        Payment link but Sales Invoice only has a Cash/Credit/Cheque Select, and Branch
        Configuration lists several modes per branch (Cash-SFSB, Swipe-SFSB, Cheque, BPAY-SFSB)
        with no single default. Picking one would be a guess about how the money actually moves.
        """
        rows = [r for r in self.payment_advice_reference if r.reference_record]
        if not rows:
            return

        if not self.branch:
            self.branch = self.branch_from_references(rows)

        if not self.cost_center:
            # the voucher's own cost centre first, then the branch's configured one
            for row in rows:
                if row.cost_center:
                    self.cost_center = row.cost_center
                    break
            else:
                self.cost_center = get_branch_cost_center(self.branch, self.company)

        if self.cost_center:
            for row in rows:
                if not row.cost_center:
                    row.cost_center = self.cost_center

    def branch_from_references(self, rows):
        """The branch of the vouchers being paid, when they agree on one."""
        branches = []
        for row in rows:
            meta = frappe.get_meta(row.reference_doctype)
            if not meta.has_field("branch"):
                continue
            branch = frappe.db.get_value(row.reference_doctype, row.reference_record, "branch")
            if branch and branch not in branches:
                branches.append(branch)

        # mixed branches on one advice: leave it blank rather than pick a side
        return branches[0] if len(branches) == 1 else None

    def party_field(self):
        return {"Supplier": "supplier", "Customer": "customer"}.get(self.party_type, "supplier")

    def validate_not_advised_elsewhere(self):
        """Stop the same voucher being paid twice through two live advices."""
        records = [r.reference_record for r in self.payment_advice_reference if r.reference_record]
        if not records:
            return

        clashes = frappe.get_all(
            "Payment Advice Reference",
            filters={
                "reference_record": ["in", records],
                "parenttype": "Payment Advice",
                "parent": ["!=", self.name or ""],
                # anything not cancelled holds the voucher — a draft advice counts, which is
                # what the builder already assumed. Submitted-only would let a hand-typed
                # advice duplicate an invoice already sitting on someone's draft.
                "docstatus": ["!=", 2],
            },
            fields=["parent", "reference_record", "allocated_amount"],
        )

        for clash in clashes:
            if flt(clash.allocated_amount) <= 0:
                continue
            advice_status = frappe.db.get_value("Payment Advice", clash.parent, "status")
            if advice_status == STATUS_CANCELLED:
                continue
            frappe.throw(
                _("%(name)s is already allocated on Payment Advice %(advice)s (%(status)s). "
                  "Cancel or remove it there first.")
                % {
                    "name": frappe.bold(clash.reference_record),
                    "advice": frappe.bold(clash.parent),
                    "status": advice_status or _("Draft"),
                }
            )

    # ── derivation ───────────────────────────────────────────────────────────────
    def set_party_name(self):
        if not (self.party_type and self.party):
            return
        field = PARTY_NAME_FIELD.get(self.party_type)
        if field:
            self.party_name = frappe.db.get_value(self.party_type, self.party, field) or self.party

    def set_reference_details(self):
        """Fill each row from its source document. Ageing is measured from the due date."""
        # what the rows said when this advice was last saved, so a shift can be reported
        before = self.get_doc_before_save()
        self._payable_before = (
            {r.name: flt(r.net_payable_amount) for r in before.payment_advice_reference}
            if before
            else {}
        )
        # what WE last wrote into the allocation column; anything different now was typed by
        # the accountant and must not be redistributed underneath them
        self._allocation_before = (
            {r.name: flt(r.allocated_amount) for r in before.payment_advice_reference}
            if before
            else {}
        )
        self._payable_changes = []

        today = getdate(nowdate())
        company_currency = get_company_currency(self.company)

        for row in self.payment_advice_reference:
            if not (row.reference_doctype and row.reference_record):
                continue

            meta = frappe.get_meta(row.reference_doctype)

            def source(fieldname):
                if not meta.has_field(fieldname):
                    return None
                return frappe.db.get_value(row.reference_doctype, row.reference_record, fieldname)

            if not row.date:
                row.date = source("posting_date") or source("transaction_date")
            # Always re-read, never trust what is on the row: these fields are read-only, the
            # source document can be amended, and rows written before the currency fix hold a
            # foreign-currency total. A stale figure here misstates the whole advice.
            total, payable = get_reference_amounts(
                row.reference_doctype, row.reference_record, meta
            )
            row.amount = total
            # Amounts on these rows are company-currency figures: ERPNext stores invoice
            # outstanding in the party account currency, which is the company currency here.
            # Stamping the invoice's own currency (SAR on an import PI, say) would render a
            # BHD number with an SAR symbol.
            row.currency = company_currency
            if not row.exchange_rate:
                row.exchange_rate = flt(source("conversion_rate")) or 1.0
            if not row.cost_center:
                row.cost_center = source("cost_center")

            # payable figure comes from the same helper, so orders net off advance_paid
            previous = self._payable_before.get(row.name)
            if previous is not None and abs(flt(previous) - flt(payable)) > 0.0005:
                # the voucher moved since this advice was last saved — say so by row, because
                # an advice with a dozen references gives no clue which one shifted
                self._payable_changes.append(
                    {
                        "idx": row.idx,
                        "reference": row.reference_record,
                        "was": flt(previous, 3),
                        "now": flt(payable, 3),
                    }
                )
            row.net_payable_amount = payable
            row.settled_amount = flt(flt(row.amount) - payable, 3)

            due = None
            for fieldname in ("due_date", "schedule_date"):
                if meta.has_field(fieldname):
                    due = source(fieldname)
                    if due:
                        break
            due = getdate(due or row.date or today)
            row.ageing = max(0, (today - due).days)

            # live status of the voucher, so the advice never shows a stale picture
            row.reference_status = source("status") if meta.has_field("status") else None

            rate = flt(row.exchange_rate) or 1.0
            row.amount_in_currency = flt(flt(row.amount) / rate, 3)
            row.settled_amount_in_currency = flt(flt(row.settled_amount) / rate, 3)
            row.net_payable_amount_in_currency = flt(flt(row.net_payable_amount) / rate, 3)

    def compute_totals(self):
        self.amount = flt(sum(flt(r.amount) for r in self.payment_advice_reference), 3)
        self.amount_paid = flt(sum(flt(r.settled_amount) for r in self.payment_advice_reference), 3)
        self.amount_to_be_settled = flt(
            sum(flt(r.net_payable_amount) for r in self.payment_advice_reference), 3
        )

        pending = flt(self.amount_to_be_settled) - flt(self.payment_amount)
        self.pending_amount = flt(pending, 3) if pending > 0 else 0.0

        rate = flt(self.exchange_rate) or 1.0
        if self.transaction_currency:
            self.amount_in_trans_cur = flt(flt(self.amount) / rate, 3)
            self.amount_paid_in_trans_curr = flt(flt(self.amount_paid) / rate, 3)
            self.amount_to_be_settled_trans_curr = flt(flt(self.amount_to_be_settled) / rate, 3)

    def validate_transaction_reference(self):
        """Mirror ERPNext's PaymentEntry.validate_transaction_reference().

        There the company-side account is checked, not the Mode of Payment: if that account is
        of type Bank, reference no and date are mandatory. Enforcing it on the advice means a
        bank payment cannot be approved only to have its Payment Entry refuse to post.
        """
        if not self.company:
            return

        company_account = get_company_account(self.company, self.mode_of_payment) or self.get(
            "bank_account_account"
        )
        if self.bank_account and not company_account:
            company_account = frappe.db.get_value("Bank Account", self.bank_account, "account")
        if not company_account:
            return

        if frappe.get_cached_value("Account", company_account, "account_type") != "Bank":
            return

        if not (self.reference_no and self.reference_date):
            frappe.throw(
                _("Reference No and Reference Date are mandatory for a bank transaction (%s).")
                % frappe.bold(company_account)
            )

    def report_payable_changes(self):
        """One notice covering everything that moved, named row by row.

        Three things can shift under an advice between saves: a reference gets part-paid, a
        row allocation no longer fits what is owed, and the payment amount no longer fits the
        total. Reporting them separately made the accountant hunt; they are one list here.
        """
        if self.docstatus != 0:
            return

        sections = []

        if getattr(self, "_payable_changes", None):
            sections.append(
                _("Settled further since this advice was last saved:")
                + "<ul>"
                + "".join(
                    _("<li>Row #%(idx)s %(ref)s: payable was %(was)s, now %(now)s</li>")
                    % {
                        "idx": c["idx"],
                        "ref": frappe.bold(c["reference"]),
                        "was": frappe.utils.fmt_money(c["was"]),
                        "now": frappe.utils.fmt_money(c["now"]),
                    }
                    for c in self._payable_changes
                )
                + "</ul>"
            )

        if getattr(self, "_allocation_trims", None):
            sections.append(
                _("Allocations trimmed to what the voucher still owes:")
                + "<ul>"
                + "".join(
                    _("<li>Row #%(idx)s %(ref)s: allocated %(was)s, now %(now)s</li>")
                    % {
                        "idx": t["idx"],
                        "ref": frappe.bold(t["reference"]),
                        "was": frappe.utils.fmt_money(t["was"]),
                        "now": frappe.utils.fmt_money(t["now"]),
                    }
                    for t in self._allocation_trims
                )
                + "</ul>"
            )

        trim = getattr(self, "_payment_amount_trim", None)
        if trim:
            sections.append(
                _("Payment Amount reduced from %(was)s to %(now)s, the total now payable.")
                % {
                    "was": frappe.bold(frappe.utils.fmt_money(trim["was"])),
                    "now": frappe.bold(frappe.utils.fmt_money(trim["now"])),
                }
            )

        if not sections:
            return

        frappe.msgprint(
            "".join(sections)
            + _("Change the Payment Amount or any row allocation and save again if this is not what you want."),
            title=_("References Updated"),
            indicator="orange",
        )

    def validate_payment_amount(self):
        """Only a nonsensical amount is refused; anything too high is trimmed to what is owed.

        Refusing an over-payable amount used to block the save, and because the references are
        refreshed during that same save the accountant never got to see the corrected figures —
        they were told a number was wrong without being shown the right one. Trimming only ever
        reduces a payment, so it cannot cause an overpayment, and every trim is reported.
        """
        self._payment_amount_trim = None

        if flt(self.payment_amount) <= 0:
            frappe.throw(_("Payment Amount must be greater than zero."))

        payable = flt(self.amount_to_be_settled)
        if flt(self.payment_amount) > payable:
            self._payment_amount_trim = {"was": flt(self.payment_amount, 3), "now": flt(payable, 3)}
            self.payment_amount = flt(payable, 3)

    def allocate_payment(self):
        """Honour what the accountant allocated, spread the rest, never exceed the payable.

        This follows Payment Entry: the row allocation is the accountant's to set, and no row
        may take more than it is owed.

        A row counts as the accountant's when its allocation differs from the figure this
        document wrote last time. Those are left exactly as typed; every other row is ours to
        fill, so `payment_amount` still spreads down the advice on its own. Without that
        distinction the leftover simply flowed back into the row somebody had just reduced.

        Nothing here throws. A row whose voucher has since been part-paid has its allocation
        trimmed to what is now owed, and `payment_amount` is reconciled to whatever ended up
        allocated, because refusing the save would leave the accountant looking at stale
        figures with no way to refresh them.
        """
        self._allocation_trims = []
        stored = getattr(self, "_allocation_before", {}) or {}

        deliberate = []
        automatic = []
        for row in self.payment_advice_reference:
            payable = flt(row.net_payable_amount)
            allocated = flt(row.allocated_amount)

            if allocated < 0:
                allocated = 0.0
            if allocated > payable:
                self._allocation_trims.append(
                    {"idx": row.idx, "reference": row.reference_record,
                     "was": flt(allocated, 3), "now": flt(payable, 3)}
                )
                allocated = flt(payable, 3)
            row.allocated_amount = flt(allocated, 3)

            was_ours = row.name in stored and abs(stored[row.name] - flt(row.allocated_amount)) < 0.0005
            untouched_new = row.name not in stored
            (automatic if (was_ours or untouched_new) else deliberate).append(row)

        budget = flt(self.payment_amount)
        held = flt(sum(flt(r.allocated_amount) for r in deliberate), 3)

        if held > budget:
            # the accountant asked for more than the advice authorises: trim their rows from
            # the bottom, leaving the earliest choices intact
            excess = flt(held - budget, 3)
            for row in reversed(deliberate):
                if excess <= 0:
                    break
                take = min(flt(row.allocated_amount), excess)
                row.allocated_amount = flt(flt(row.allocated_amount) - take, 3)
                excess = flt(excess - take, 3)
            held = flt(sum(flt(r.allocated_amount) for r in deliberate), 3)

        balance = flt(budget - held, 3)
        for row in automatic:
            payable = flt(row.net_payable_amount)
            if balance <= 0 or payable <= 0:
                row.allocated_amount = 0.0
                continue
            take = payable if payable <= balance else balance
            row.allocated_amount = flt(take, 3)
            balance = flt(balance - take, 3)

        # the advice pays what it allocated, no more
        allocated_total = flt(sum(flt(r.allocated_amount) for r in self.payment_advice_reference), 3)
        if allocated_total < flt(self.payment_amount) - 0.0005:
            self._payment_amount_trim = {
                "was": flt(self.payment_amount, 3),
                "now": allocated_total,
            }
            self.payment_amount = allocated_total

    def set_words(self):
        company_currency = get_company_currency(self.company)
        if self.amount_to_be_settled:
            self.amount_to_be_settled_in_words = money_in_words(
                self.amount_to_be_settled, company_currency
            )
        if self.amount_to_be_settled_trans_curr and self.transaction_currency:
            self.amount_words_trans_curr = money_in_words(
                self.amount_to_be_settled_trans_curr, self.transaction_currency
            )

    def set_status(self):
        if self.docstatus == 2:
            self.status = STATUS_CANCELLED
        elif self.docstatus == 0:
            self.status = STATUS_PENDING if self.approver else STATUS_DRAFT
        elif self.payment_entry:
            paid = flt(frappe.db.get_value("Payment Entry", self.payment_entry, "paid_amount"))
            self.status = STATUS_PAID if paid >= flt(self.payment_amount) else STATUS_PARTLY_PAID
        else:
            self.status = STATUS_APPROVED

    def validate_approver(self):
        # When a PM Workflow governs Payment Advice, IT decides who may submit: an Accountant
        # approving someone else's advice is the whole point of a workflow, and this rule
        # would reject exactly that. Standing down here rather than in the workflow keeps a
        # site without permission_manager working unchanged.
        if workflow_controls_submission(self.company):
            return

        if not self.approver:
            frappe.throw(_("Select an Approver before submitting."))

        # A System Manager can always release a stuck advice — including an automated submit,
        # which runs as Administrator rather than as the stamped approver.
        if "System Manager" in frappe.get_roles():
            return

        # The approver is the user itself. It used to be an Employee, which meant an approver
        # whose Employee carried no User ID could be selected and then nobody could submit;
        # patches/v0_1/approver_employee_to_user.py moved the stored values over.
        if frappe.session.user == self.approver:
            return

        frappe.throw(
            _("Only %s (the selected Approver) can submit this advice.") % frappe.bold(self.approver)
        )


def workflow_controls_submission(company=None):
    """True when a PM Workflow is active for Payment Advice on this site.

    Imported lazily so sf_trading keeps working on a bench without permission_manager.
    """
    try:
        from vansale.sf_trading.api.payment_advice_workflow import has_active_workflow
    except Exception:
        return False

    try:
        return has_active_workflow(company)
    except Exception:
        # never let an approval-mode probe block a save
        return False


# ── Approval routing ─────────────────────────────────────────────────────────────

def compute_approval_route(advice):
    """Which approval route this advice takes, from what it is paying for.

    The rules, in the order they are tested:

      1. any overdue Purchase Invoice   → HO Accounts, then GM/Finance, then the Accountant
      2. any Purchase Order that is either one of several, or on its own worth more than
         BHD 500                        → Purchase Manager, then GM/Finance, then the Accountant
      3. a single Purchase Order at or below BHD 500 → straight to the Accountant
      4. invoices, none overdue:
           BHD 500 or less              → straight to the Accountant
           more than BHD 500            → GM or Finance Manager, then the Accountant

    Orders and invoices part company above the limit. A large order goes through the Purchase
    Manager first, because somebody who knows the purchase should see it before Finance does;
    a large invoice goes straight to Finance, the order having already been approved when it
    was raised. A single order used to reach the Accountant on the raiser's send alone whatever
    it was worth, which is how BHD 6,364 was released with one signature.

    An advice may mix orders and invoices, which the rules above do not name. Overdue wins,
    because an overdue payable is the case the extra scrutiny exists for; the order count is
    tested next, and the amount rule last. The longest route wins any tie, deliberately: the
    failure worth avoiding is money leaving with too few approvals, not too many.
    """
    rows = [r for r in (advice.get("payment_advice_reference") or []) if r.get("reference_record")]

    invoices = [r.reference_record for r in rows if r.reference_doctype == "Purchase Invoice"]
    orders = [r.reference_record for r in rows if r.reference_doctype == "Purchase Order"]

    if invoices and _has_overdue_invoice(invoices):
        return ROUTE_HO_ACCOUNTS

    # One order or several, the purchase route applies as soon as the money is worth a second
    # opinion from the person who knows the purchase.
    if orders and (len(orders) > 1 or flt(advice.get("payment_amount")) > FINANCE_APPROVAL_LIMIT):
        return ROUTE_PURCHASE_MANAGER

    if flt(advice.get("payment_amount")) <= FINANCE_APPROVAL_LIMIT:
        return ROUTE_ACCOUNTANT

    return ROUTE_FINANCE


def _has_overdue_invoice(invoice_names):
    """Is any of these Purchase Invoices past its due date with money still on it?

    One query for the whole table — a per-row lookup here would run once per reference on
    every save of every advice.
    """
    if not invoice_names:
        return False

    today = getdate(nowdate())
    for invoice in frappe.get_all(
        "Purchase Invoice",
        filters={"name": ["in", list(set(invoice_names))], "docstatus": 1},
        fields=["name", "due_date", "outstanding_amount"],
    ):
        if not invoice.due_date:
            continue
        if getdate(invoice.due_date) < today and flt(invoice.outstanding_amount) > 0:
            return True

    return False


# ── Payment Entry creation ───────────────────────────────────────────────────────

def get_reference_amounts(doctype, name, meta=None):
    """(total, still payable) for a reference document, both in COMPANY currency.

    Mirrors ERPNext's Payment Request get_amount() while expressing everything in company
    currency, because that is the only currency this document speaks:

      * Sales / Purchase Order — orders carry no outstanding_amount. Payable is
        (rounded total or grand total) minus advance_paid, exactly as Payment Request computes
        it, and advance_paid is already a company-currency figure. Without this an order that
        is fully advanced still looked fully payable: PUR-ORD-2026-00048 on UAT is 27.5 with
        27.5 advanced, i.e. nothing to pay.
      * Sales / Purchase Invoice — outstanding_amount, which ERPNext keeps in the party account
        (company) currency. The total comes from base_* so a foreign invoice is not mixed.
      * Journal Entry — total_debit; there is no outstanding concept, so both figures match.
      * anything else (Dunning) — grand_total converted at the document's rate.

    base_rounded_total is checked before base_grand_total but is genuinely 0 on documents with
    rounding disabled, which is why each step falls through on a zero rather than trusting it.
    """
    meta = meta or frappe.get_meta(doctype)

    def value(*fieldnames):
        for fieldname in fieldnames:
            if meta.has_field(fieldname):
                amount = flt(frappe.db.get_value(doctype, name, fieldname))
                if amount:
                    return amount
        return 0.0

    if doctype in ORDER_DOCTYPES:
        total = value("base_rounded_total", "base_grand_total", "grand_total")
        advance = flt(frappe.db.get_value(doctype, name, "advance_paid"))
        return total, max(0.0, flt(total - advance, 3))

    if meta.has_field("outstanding_amount"):
        total = value("base_rounded_total", "base_grand_total", "grand_total")
        outstanding = flt(frappe.db.get_value(doctype, name, "outstanding_amount"))
        return (total or outstanding), outstanding

    if meta.has_field("total_debit"):
        total = value("total_debit")
        return total, total

    total = value("base_grand_total")
    if not total and meta.has_field("grand_total"):
        rate = flt(frappe.db.get_value(doctype, name, "conversion_rate")) or 1.0
        total = flt(flt(frappe.db.get_value(doctype, name, "grand_total")) * rate, 3)
    return total, total


def get_document_total(doctype, name, meta=None):
    """Company-currency total only — kept for callers that do not need the payable figure."""
    return get_reference_amounts(doctype, name, meta)[0]


def get_branch_cost_center(branch, company=None):
    """The cost centre configured for a branch, from Branch Configuration.

    Branch Configuration holds a cost_center child table per branch (one row in practice, e.g.
    SFSB -> "SFSB - SFB"). This is what the rest of sf_trading treats as the branch default, so
    the advice follows the same source rather than inventing its own.
    """
    if not branch:
        return None

    filters = {"branch": branch}
    if company:
        filters["company"] = company
    config = frappe.db.get_value("Branch Configuration", filters, "name") or frappe.db.get_value(
        "Branch Configuration", {"branch": branch}, "name"
    )
    if not config:
        return None

    return frappe.db.get_value(
        "Branch Configuration Cost Center",
        {"parent": config, "parenttype": "Branch Configuration"},
        "cost_center",
        order_by="idx asc",
    )


def get_company_currency(company):
    """The one currency this document speaks in."""
    return (
        frappe.get_cached_value("Company", company, "default_currency")
        if company
        else None
    ) or frappe.db.get_default("currency")


def get_payment_type(party_type):
    if party_type in RECEIVE_PARTY_TYPES:
        return "Receive"
    if party_type in PAY_PARTY_TYPES:
        return "Pay"
    frappe.throw(_("Unsupported Party Type for payment: %s") % party_type)


def get_company_account(company, mode_of_payment=None):
    """Bank/cash account for the company side.

    Mirrors ERPNext's own lookup (the Mode of Payment Account child row for this company),
    then falls back to the company's default bank, then cash account.
    """
    if mode_of_payment:
        account = frappe.db.get_value(
            "Mode of Payment Account",
            {"parent": mode_of_payment, "company": company},
            "default_account",
        )
        if account:
            return account

    return frappe.db.get_value("Company", company, "default_bank_account") or frappe.db.get_value(
        "Company", company, "default_cash_account"
    )


def build_payment_entry(advice):
    """Return an unsaved Payment Entry for a submitted Payment Advice."""
    if not advice.payment_advice_reference:
        frappe.throw(_("Add at least one reference before creating a Payment Entry."))

    allocations = [r for r in advice.payment_advice_reference if flt(r.allocated_amount) > 0]
    if not allocations:
        frappe.throw(_("Nothing is allocated for payment on this advice."))

    company = advice.company
    party_account = get_party_account(advice.party_type, advice.party, company)
    if not party_account:
        frappe.throw(
            _("No default account is set for %(party_type)s %(party)s.")
            % {"party_type": _(advice.party_type), "party": frappe.bold(advice.party)}
        )

    company_account = get_company_account(company, advice.mode_of_payment)
    if not company_account:
        frappe.throw(
            _("Set a default bank or cash account for company %s, or pick a Mode of Payment that has one.")
            % frappe.bold(company)
        )

    payment_type = get_payment_type(advice.party_type)
    paid_from, paid_to = (
        (party_account, company_account)
        if payment_type == "Receive"
        else (company_account, party_account)
    )

    pe = frappe.new_doc("Payment Entry")
    pe.update(
        {
            "payment_type": payment_type,
            "company": company,
            "posting_date": nowdate(),
            "party_type": advice.party_type,
            "party": advice.party,
            "mode_of_payment": advice.mode_of_payment,
            "paid_from": paid_from,
            "paid_to": paid_to,
            "paid_amount": flt(advice.payment_amount),
            "received_amount": flt(advice.payment_amount),
            "cost_center": advice.cost_center,
            # Branch too, not just the cost center. Every advice carries both, but only the
            # cost center was copied, so every Payment Entry raised from an advice reached
            # the ledger with no branch at all — and the branch is what the DCR and the
            # branch-wise reports key on.
            "branch": advice.branch,
            "project": advice.project,
            "bank_account": advice.bank_account,
            "custom_payment_advice": advice.name,
            "remarks": advice.remarks,
        }
    )

    if advice.reference_no:
        pe.reference_no = advice.reference_no
        pe.reference_date = advice.reference_date or nowdate()

    for row in allocations:
        pe.append(
            "references",
            {
                "reference_doctype": row.reference_doctype,
                "reference_name": row.reference_record,
                "allocated_amount": flt(row.allocated_amount),
            },
        )

    # currencies: read them, never assume they match
    company_currency = frappe.db.get_value("Company", company, "default_currency")
    pe.paid_from_account_currency = frappe.db.get_value("Account", paid_from, "account_currency")
    pe.paid_to_account_currency = frappe.db.get_value("Account", paid_to, "account_currency")

    if pe.paid_from_account_currency and pe.paid_from_account_currency != company_currency:
        pe.source_exchange_rate = get_exchange_rate(
            pe.paid_from_account_currency, company_currency, pe.posting_date
        )
    if pe.paid_to_account_currency and pe.paid_to_account_currency != company_currency:
        pe.target_exchange_rate = get_exchange_rate(
            pe.paid_to_account_currency, company_currency, pe.posting_date
        )

    # Deliberately NOT calling pe.set_missing_values() here. ERPNext's validate() runs
    # setup_party_account_field() FIRST and set_missing_values() second (see
    # erpnext/accounts/doctype/payment_entry/payment_entry.py). Calling it standalone on a new
    # document leaves self.party_account unset, and hrms' EmployeePaymentEntry override — which
    # replaces the Payment Entry class on this bench — then fails with
    # "'EmployeePaymentEntry' object has no attribute 'party_account'". This killed every
    # customer (Receive) advice. insert() runs validate(), which does the whole job in the
    # right order, so nothing is lost by leaving it to ERPNext.
    return pe


@frappe.whitelist()
def create_payment_entry(payment_advice: str, submit: int = 0):
    """Create (and optionally submit) the Payment Entry for a submitted Payment Advice."""
    if not isinstance(payment_advice, str) or not payment_advice:
        frappe.throw(_("Payment Advice is required."))

    advice = frappe.get_doc("Payment Advice", payment_advice)
    advice.check_permission("read")

    if not frappe.has_permission("Payment Entry", "create"):
        frappe.throw(_("You are not permitted to create Payment Entries."), frappe.PermissionError)

    if advice.docstatus != 1:
        frappe.throw(_("Submit the Payment Advice before creating a Payment Entry."))

    if advice.payment_entry:
        existing = frappe.db.get_value("Payment Entry", advice.payment_entry, "docstatus")
        if cint(existing) != 2:
            frappe.throw(
                _("Payment Entry %s already exists for this advice.") % frappe.bold(advice.payment_entry)
            )

    pe = build_payment_entry(advice)
    pe.insert()

    if cint(submit):
        if not frappe.has_permission("Payment Entry", "submit"):
            frappe.throw(
                _("You are not permitted to submit Payment Entries."), frappe.PermissionError
            )
        pe.submit()

    frappe.msgprint(
        _("Payment Entry %s created.") % get_link_to_form("Payment Entry", pe.name),
        indicator="green",
        alert=True,
    )
    return pe.name


@frappe.whitelist()
def get_branch_default_cost_center(branch: str, company: str = None):
    """Exposed for the form: the cost centre Branch Configuration holds for this branch."""
    frappe.has_permission("Payment Advice", "read", throw=True)
    return get_branch_cost_center(branch, company)


@frappe.whitelist()
def mode_needs_reference(company: str, mode_of_payment: str = None, bank_account: str = None):
    """True when the company-side account is a Bank account.

    Same test ERPNext applies in PaymentEntry.validate_transaction_reference(), exposed so the
    form can mark reference no/date required as soon as the mode is chosen rather than at save.
    """
    account = get_company_account(company, mode_of_payment)
    if not account and bank_account:
        account = frappe.db.get_value("Bank Account", bank_account, "account")
    if not account:
        return False
    return frappe.get_cached_value("Account", account, "account_type") == "Bank"


@frappe.whitelist()
def get_reference_details(reference_doctype: str, reference_record: str, company: str = None,
                         party_type: str = None, party: str = None):
    """Details for ONE manually-picked reference row.

    Payment Entry fills a reference row the moment you choose the document; the advice grid now
    does the same instead of waiting for a save. Validation lives here too, so a wrong company
    or party is refused at the moment of picking rather than at submit.
    """
    frappe.has_permission("Payment Advice", "write", throw=True)

    allowed = valid_reference_doctypes(party_type) if party_type else ALLOWED_REFERENCE_DOCTYPES
    if reference_doctype not in allowed:
        frappe.throw(
            _("A %(party_type)s advice cannot reference a %(dt)s. Allowed: %(allowed)s")
            % {
                "party_type": _(party_type or ""),
                "dt": _(reference_doctype),
                "allowed": ", ".join(_(d) for d in allowed),
            }
        )
    if not frappe.db.exists(reference_doctype, reference_record):
        frappe.throw(
            _("%(dt)s %(name)s does not exist.")
            % {"dt": _(reference_doctype), "name": frappe.bold(reference_record)}
        )

    meta = frappe.get_meta(reference_doctype)
    wanted = [f for f in (
        "posting_date", "transaction_date", "due_date", "schedule_date", "grand_total",
        "outstanding_amount", "currency", "conversion_rate", "cost_center", "status",
        "docstatus", "company", "bill_no", "branch",
    ) if f == "docstatus" or meta.has_field(f)]
    values = frappe.db.get_value(reference_doctype, reference_record, wanted, as_dict=True) or frappe._dict()

    if cint(values.get("docstatus")) != 1:
        frappe.throw(_("%s is not submitted.") % frappe.bold(reference_record))

    if company and values.get("company") and values.get("company") != company:
        frappe.throw(
            _("%(name)s belongs to company %(other)s.")
            % {"name": frappe.bold(reference_record), "other": frappe.bold(values.get("company"))}
        )

    if party and party_type:
        party_field = {"Supplier": "supplier", "Customer": "customer"}.get(party_type)
        if party_field and meta.has_field(party_field):
            row_party = frappe.db.get_value(reference_doctype, reference_record, party_field)
            if row_party and row_party != party:
                frappe.throw(
                    _("%(name)s belongs to %(other)s, not %(party)s.")
                    % {
                        "name": frappe.bold(reference_record),
                        "other": frappe.bold(row_party),
                        "party": frappe.bold(party),
                    }
                )

    # already spoken for?
    clash = frappe.get_all(
        "Payment Advice Reference",
        filters={
            "reference_record": reference_record,
            "parenttype": "Payment Advice",
            "docstatus": ["!=", 2],
            "allocated_amount": [">", 0],
        },
        fields=["parent"],
        limit=1,
    )
    if clash:
        frappe.throw(
            _("%(name)s is already allocated on Payment Advice %(advice)s.")
            % {"name": frappe.bold(reference_record), "advice": frappe.bold(clash[0].parent)}
        )

    total, outstanding = get_reference_amounts(reference_doctype, reference_record, meta)
    if outstanding <= 0:
        if reference_doctype in ORDER_DOCTYPES:
            frappe.throw(
                _("%s is already fully advanced, so there is nothing left to pay against it.")
                % frappe.bold(reference_record)
            )
        frappe.throw(_("%s has nothing outstanding.") % frappe.bold(reference_record))

    today = getdate(nowdate())
    due = getdate(
        values.get("due_date")
        or values.get("schedule_date")     # orders age from their delivery/required date
        or values.get("posting_date")
        or values.get("transaction_date")
        or today
    )

    branch = (
        frappe.db.get_value(reference_doctype, reference_record, "branch")
        if meta.has_field("branch")
        else None
    )

    return {
        "bill_no": values.get("bill_no"),
        "date": values.get("posting_date") or values.get("transaction_date"),
        # offered to the parent form, which only takes these when its own fields are blank
        "parent_branch": branch,
        "parent_cost_center": values.get("cost_center") or get_branch_cost_center(branch, company),
        "amount": total,
        "settled_amount": flt(total - outstanding, 3),
        "net_payable_amount": outstanding,
        "ageing": max(0, (today - due).days),
        "currency": get_company_currency(company),
        "exchange_rate": flt(values.get("conversion_rate")) or 1.0,
        "cost_center": values.get("cost_center"),
        "reference_status": values.get("status"),
    }


@frappe.whitelist()
def get_outstanding_documents(
    company: str,
    party_type: str,
    party: str,
    party_account: str = None,
    from_posting_date: str = None,
    to_posting_date: str = None,
    from_due_date: str = None,
    to_due_date: str = None,
    cost_center: str = None,
    from_amount: float = None,
    to_amount: float = None,
    get_outstanding_invoices: int = 1,
    get_orders_to_be_billed: int = 0,
):
    """Outstanding vouchers for a party, using ERPNext's own Payment Entry engine.

    Delegates to `erpnext…payment_entry.get_outstanding_reference_documents`, which is the
    same code the Payment Entry form's "Get Outstanding Invoices" runs. That buys the real
    behaviour rather than an approximation of it: Payment Ledger based outstanding (so
    part-payments, credit notes and return invoices are already netted), payment-term
    splitting, supplier block-status checks, accounting-dimension filters, and the party
    permission check it performs internally.

    Returns rows shaped for the Payment Advice Reference table.
    """
    frappe.has_permission("Payment Advice", "write", throw=True)

    from erpnext.accounts.doctype.payment_entry.payment_entry import (
        get_outstanding_reference_documents,
    )

    if not company:
        frappe.throw(_("Company is required."))
    if not (party_type and party):
        frappe.throw(_("Party Type and Party are required."))
    if party_type not in PARTY_TYPES:
        frappe.throw(_("Unsupported Party Type: %s") % party_type)

    party_account = party_account or get_party_account(party_type, party, company)
    if not party_account:
        frappe.throw(
            _("No default account is set for %(party_type)s %(party)s.")
            % {"party_type": _(party_type), "party": frappe.bold(party)}
        )

    args = {
        "company": company,
        "party_type": party_type,
        "party": party,
        "party_account": party_account,
        "payment_type": get_payment_type(party_type),
        "posting_date": nowdate(),
        "get_outstanding_invoices": cint(get_outstanding_invoices),
        "get_orders_to_be_billed": cint(get_orders_to_be_billed),
        "cost_center": cost_center,
        "from_posting_date": from_posting_date,
        "to_posting_date": to_posting_date,
        "from_due_date": from_due_date,
        "to_due_date": to_due_date,
    }

    vouchers = get_outstanding_reference_documents(args) or []
    return shape_reference_rows(
        vouchers, cost_center=cost_center, from_amount=from_amount, to_amount=to_amount,
        company=company,
    )


def shape_reference_rows(vouchers, cost_center=None, from_amount=None, to_amount=None, company=None):
    """Map ERPNext's outstanding rows onto Payment Advice Reference rows.

    Verified against live data: the engine returns account, bill_no, currency, due_date,
    exchange_rate, invoice_amount, outstanding_amount, payment_amount, posting_date,
    voucher_no, voucher_type. `payment_term` appears only for term-allocated invoices and
    `total_amount` not at all, so both are read defensively. Only cost_center and status
    need a extra lookup, since the engine does not carry them.
    """
    today = getdate(nowdate())
    # every amount below is a company-currency figure, so label it as such
    default_currency = get_company_currency(company)
    rows = []

    for voucher in vouchers:
        voucher = frappe._dict(voucher)
        outstanding = flt(voucher.get("outstanding_amount"))
        if outstanding <= 0:
            continue
        if from_amount and outstanding < flt(from_amount):
            continue
        if to_amount and outstanding > flt(to_amount):
            continue

        doctype = voucher.get("voucher_type")
        name = voucher.get("voucher_no")
        if doctype not in ALLOWED_REFERENCE_DOCTYPES or not name:
            continue

        meta = frappe.get_meta(doctype)
        lookup = [f for f in ("cost_center", "status") if meta.has_field(f)]
        extra = (
            frappe.db.get_value(doctype, name, lookup, as_dict=True) if lookup else None
        ) or frappe._dict()

        invoice_amount = flt(voucher.get("invoice_amount")) or flt(voucher.get("total_amount"))
        due_date = voucher.get("due_date") or voucher.get("posting_date")

        rows.append(
            {
                "reference_doctype": doctype,
                "reference_record": name,
                "bill_no": voucher.get("bill_no"),
                "date": voucher.get("posting_date"),
                "amount": invoice_amount,
                "settled_amount": flt(invoice_amount - outstanding, 3),
                "net_payable_amount": outstanding,
                "ageing": max(0, (today - getdate(due_date)).days) if due_date else 0,
                "payment_term": voucher.get("payment_term"),
                "currency": default_currency,
                "exchange_rate": flt(voucher.get("exchange_rate")) or 1.0,
                "cost_center": extra.get("cost_center") or cost_center,
                "reference_status": extra.get("status"),
            }
        )

    rows.sort(key=lambda r: (-r["ageing"], -r["net_payable_amount"]))
    return rows


def refresh_reference_status(advice_name):
    """Re-read every referenced voucher's status and outstanding on a submitted advice.

    Child rows are written with `frappe.db.set_value` — never `parent.save()`, which would
    re-validate the submitted document and reject fields lacking allow_on_submit.
    """
    rows = frappe.get_all(
        "Payment Advice Reference",
        filters={"parent": advice_name, "parenttype": "Payment Advice"},
        fields=["name", "reference_doctype", "reference_record", "amount"],
    )

    for row in rows:
        if not (row.reference_doctype and row.reference_record):
            continue
        if not frappe.db.exists(row.reference_doctype, row.reference_record):
            continue

        meta = frappe.get_meta(row.reference_doctype)
        updates = {}

        if meta.has_field("status"):
            updates["reference_status"] = frappe.db.get_value(
                row.reference_doctype, row.reference_record, "status"
            )

        if meta.has_field("outstanding_amount"):
            outstanding = flt(
                frappe.db.get_value(row.reference_doctype, row.reference_record, "outstanding_amount")
            )
            updates["net_payable_amount"] = outstanding
            updates["settled_amount"] = flt(flt(row.amount) - outstanding, 3)

        if updates:
            frappe.db.set_value(
                "Payment Advice Reference", row.name, updates, update_modified=False
            )


def get_due_cutoff(days=0):
    """Cut-off date for "due within N days" — used by the automation layer."""
    return add_days(getdate(nowdate()), cint(days))

def get_advice_map(records, include_cancelled=False):
    """Map voucher name -> the Payment Advice holding it, for reports and list views.

    Returns {} when the DocType is not installed yet, so a report that shows this column
    keeps working on a site where the fixture has not migrated (the same guard the Loyalty
    Rewards Report needed).
    """
    if not records:
        return {}
    if not frappe.db.exists("DocType", "Payment Advice Reference"):
        return {}

    filters = {
        "reference_record": ["in", list(records)],
        "parenttype": "Payment Advice",
    }
    if not include_cancelled:
        filters["docstatus"] = ["!=", 2]

    rows = frappe.get_all(
        "Payment Advice Reference",
        filters=filters,
        fields=["reference_record", "parent", "allocated_amount"],
        order_by="modified desc",
    )

    advices = {}
    statuses = {}
    for row in rows:
        if row.reference_record in advices:
            continue  # newest advice wins
        advices[row.reference_record] = row.parent

    if advices:
        statuses = dict(
            frappe.get_all(
                "Payment Advice",
                filters={"name": ["in", list(set(advices.values()))]},
                fields=["name", "status"],
                as_list=True,
            )
        )

    return {
        record: {"advice": advice, "status": statuses.get(advice)}
        for record, advice in advices.items()
    }
