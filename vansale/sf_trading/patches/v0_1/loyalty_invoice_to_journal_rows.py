# apps/vansale/vansale/sf_trading/patches/v0_1/loyalty_invoice_to_journal_rows.py
"""Copy the header loyalty Sales Invoice link onto the journal's debit rows.

The link moved from `Journal Entry.custom_loyalty_sales_invoice` to
`Journal Entry Account.custom_loyalty_sales_invoice` so one journal can reward invoices belonging
to different customers. The journals booked before the move carry the header link only; without
this they would read as unlinked in the Loyalty Rewards Report.

Where a legacy journal has several debit rows, the header link was by definition the one invoice
for the whole voucher, so every debit row gets it. Nothing is double counted: each row keeps its
own debit as its reward, and the report's summary adds each invoice's value once through a set.

The field is created here as well as shipped as a fixture, because `bench migrate` runs
post_model_sync patches during the schema updates and only calls `sync_fixtures()` afterwards — on
the first migrate the column would not exist yet and this patch would silently do nothing.

Replay-safe: a row that already carries a link is skipped, and the whole patch no-ops on a site
that never had the header field. Writes go through `frappe.db.set_value(..., update_modified=False)`
— no document is loaded, so no validation fires on the submitted journals and none of them look
edited afterwards.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.utils import flt

TEMPLATE = "Loyalty Reward Entry"
FIELD = "custom_loyalty_sales_invoice"
PARENT_DT = "Journal Entry"
CHILD_DT = "Journal Entry Account"

# the same definition the fixture ships
ROW_FIELD = {
    "fieldname": FIELD,
    "label": "Loyalty Sales Invoice",
    "fieldtype": "Link",
    "options": "Sales Invoice",
    "insert_after": "credit",
    "in_list_view": 1,
    "columns": 2,
    "allow_on_submit": 1,
    "depends_on": (
        'eval:parent.from_template=="%s" && (doc.debit || doc.debit_in_account_currency)' % TEMPLATE
    ),
    "mandatory_depends_on": (
        'eval:parent.from_template=="%s" && (doc.debit || doc.debit_in_account_currency)' % TEMPLATE
    ),
    "link_filters": (
        '[["Sales Invoice", "company", "=", "eval:parent.company"], '
        '["Sales Invoice", "docstatus", "=", 1]]'
    ),
    "description": (
        "Sales Invoice this reward row relates to. Mandatory on every debit row of a "
        "Loyalty Reward Entry journal."
    ),
    "module": "Sf Trading",
    "is_system_generated": 0,
}


def execute():
    if not frappe.db.has_column(PARENT_DT, FIELD):
        # nothing was ever linked on this site
        return

    if not frappe.db.has_column(CHILD_DT, FIELD):
        create_custom_fields({CHILD_DT: [ROW_FIELD]})

    linked = frappe.get_all(
        PARENT_DT,
        filters={"from_template": TEMPLATE, FIELD: ["is", "set"]},
        fields=["name", FIELD],
    )
    if not linked:
        return

    invoice_by_journal = {row.name: row.get(FIELD) for row in linked}

    rows = frappe.get_all(
        CHILD_DT,
        filters={"parent": ["in", list(invoice_by_journal)], "parenttype": PARENT_DT},
        fields=["name", "parent", "idx", "debit", "debit_in_account_currency", FIELD],
        order_by="parent asc, idx asc",
    )

    stamped = 0
    touched = set()
    for row in rows:
        if row.get(FIELD):
            continue  # already carries its own link, and that one wins
        if not (flt(row.debit) or flt(row.debit_in_account_currency)):
            continue  # a funding (credit) row rewards nobody

        frappe.db.set_value(
            CHILD_DT, row.name, FIELD, invoice_by_journal[row.parent], update_modified=False
        )
        touched.add(row.parent)
        stamped += 1

    frappe.db.commit()

    orphans = sorted(set(invoice_by_journal) - touched)
    if orphans:
        # a linked journal with no debit row is a data oddity, not a reason to abort a migrate;
        # the report still shows it through the header fallback
        frappe.log_error(
            message="Header link kept but no debit row to stamp it on:\n" + "\n".join(orphans),
            title="sf_trading: loyalty invoice row backfill (%d rows stamped)" % stamped,
        )
