# apps/vansale/vansale/sf_trading/api/loyalty_reward_rows.py
"""Every debit row of a Loyalty Reward Entry journal must name the Sales Invoice it rewards.

The link used to live on the journal header (`Journal Entry.custom_loyalty_sales_invoice`), which
could only ever express one invoice per voucher. A counter does batch one journal across several
customers' invoices, so the link now lives on each Accounts row and the header field is legacy.

The row Custom Field carries `mandatory_depends_on`, which paints the red star and blocks Save in
the desk — but v15 evaluates that expression **client-side only**: the server's mandatory pass
tests a literal `reqd` and nothing else, so REST, `frappe.client.insert`, Data Import, Server
Scripts and background jobs would sail straight past it. This handler is the enforcement; the
Custom Field property is only the UX.

Plain `reqd = 1` on that field is not an option: it is unconditional and server-enforced, so it
would reject every Journal Entry Account row on the site, including the journals ERPNext posts
itself for tax withholding, exchange gain/loss, depreciation and period closing.

It cannot fire on the journals already booked. `run_before_save_methods` dispatches on the action:
`save`/`submit` run `validate`, a cancel runs only `before_cancel`, and an `allow_on_submit` edit
runs only `before_update_after_submit`. So a submitted loyalty journal can still be cancelled, and
its Cost Center still corrected, without anyone being asked for an invoice. Amending one does
re-check it, which is right — an amendment is a fresh draft being entered again.
"""

import frappe
from frappe import _
from frappe.utils import flt

TEMPLATE = "Loyalty Reward Entry"
LINK_FIELD = "custom_loyalty_sales_invoice"


def validate_loyalty_reward_rows(doc, method=None):
    """Reject a Loyalty Reward Entry journal whose debit rows do not name their Sales Invoice."""
    if (doc.get("from_template") or "") != TEMPLATE:
        # every other journal on the site is untouched, including ERPNext's automatic ones,
        # which never carry a template at all
        return

    if doc.docstatus == 2:
        # cancelling does not run validate, so this is belt and braces — but an amend-from-
        # cancelled path must never be held up by a rule about the row it is replacing
        return

    if not frappe.get_meta("Journal Entry Account").has_field(LINK_FIELD):
        # the fixture only lands on `bench migrate`; until then there is nothing to enforce
        return

    missing = []
    for row in doc.get("accounts") or []:
        # `debit` is read-only and derived (debit_in_account_currency * exchange_rate), so it is
        # 0 on an API insert that left exchange_rate unset even though a figure was supplied.
        # Test the derived field first, fall back to the entered one.
        if not (flt(row.debit) or flt(row.debit_in_account_currency)):
            continue  # a funding (credit) row rewards nobody

        if not row.get(LINK_FIELD):
            missing.append(
                _("Row #%(idx)s (%(account)s): link the Sales Invoice this reward is for.")
                % {"idx": row.idx, "account": row.account or _("no account")}
            )

    if missing:
        frappe.throw(
            _("A %(template)s journal must name the Sales Invoice on every debit row:")
            % {"template": frappe.bold(TEMPLATE)}
            + "<br><br>"
            + "<br>".join(missing),
            title=_("Loyalty Sales Invoice Missing"),
        )
