# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""One expense account for a whole Material Issue, instead of one per row.

A Material Issue writes off stock, and the write-off lands in whatever expense account each
item row names. Core only offers that account row by row, so issuing twenty items to the same
cost meant picking the same account twenty times — slow, and easy to get wrong on row
nineteen, where a single odd row quietly splits the charge across two accounts.

The account is asked for once on the header and stamped onto every row before the document
validates, so ERPNext still checks it (company, group, root type) exactly as it would a
hand-typed row. It applies ONLY when the purpose is Material Issue: the other purposes either
have no write-off at all (a transfer stays in stock) or derive their accounts from the BOM or
the receiving item, and overwriting those would be wrong.

Leaving the header blank changes nothing — every row keeps whatever it already had and core's
own defaulting applies — so the field adds a shortcut without taking the row-level control
away from anyone who needs it.
"""

import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

MATERIAL_ISSUE = "Material Issue"
HEADER_FIELD = "custom_expense_account"


def apply_expense_account(doc, method=None):
    """before_validate on Stock Entry: push the header account down to every row.

    Runs before validation rather than after, so the account faces ERPNext's own checks
    instead of slipping past them into the database.
    """
    if doc.get("purpose") != MATERIAL_ISSUE:
        return

    account = doc.get(HEADER_FIELD)
    if not account:
        return

    for row in doc.get("items") or []:
        row.expense_account = account


def ensure_custom_fields():
    """after_migrate: the header field, shown only where it means something."""
    only_material_issue = 'eval:doc.purpose=="%s"' % MATERIAL_ISSUE

    create_custom_fields(
        {
            "Stock Entry": [
                {
                    "fieldname": HEADER_FIELD,
                    "label": "Expense Account (All Items)",
                    "fieldtype": "Link",
                    "options": "Account",
                    "insert_after": "stock_entry_type",
                    "depends_on": only_material_issue,
                    "ignore_user_permissions": 1,
                    "description": (
                        "Applied to every item row when the entry is saved. Leave it blank to "
                        "set the account row by row instead."
                    ),
                }
            ]
        },
        ignore_validate=True,
    )
