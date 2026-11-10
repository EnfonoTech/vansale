# apps/vansale/vansale/sf_trading/patches/v0_1/approver_employee_to_user.py
"""Approver moved from Employee to User on Payment Advice and Payment Automation Settings.

The field used to link an Employee, and submission compared the session user against that
Employee's User ID. An approver whose Employee carried no User ID could therefore be selected and
then nobody could submit the advice. The field is now the user itself.

Stored values are Employee names, so they are translated here: Employee -> user_id. An Employee with
no linked user cannot be translated; the value is cleared and named in the Error Log, because
leaving an Employee name in a User link shows as a broken link and would never match a session user.
A value that is not an Employee name is already a user and is left alone, so a replay is a no-op.
"""

import frappe

TARGETS = ("Payment Advice", "Payment Automation Settings")


def execute():
    for doctype in TARGETS:
        if not frappe.db.exists("DocType", doctype):
            continue

        rows = frappe.get_all(
            doctype, filters={"approver": ["not in", ["", None]]}, fields=["name", "approver"]
        )
        if not rows:
            continue

        # only values that are Employee names need moving; anything else is already a user
        employees = {
            e.name: e.user_id
            for e in frappe.get_all(
                "Employee",
                filters={"name": ["in", list({r.approver for r in rows})]},
                fields=["name", "user_id"],
            )
        }
        if not employees:
            continue

        cleared = []
        for row in rows:
            if row.approver not in employees:
                continue
            user = employees[row.approver] or None
            # update_modified stays off: an approver on a submitted advice must not look edited,
            # and this rewrites how the value is stored rather than changing anyone's intent
            frappe.db.set_value(doctype, row.name, "approver", user, update_modified=False)
            if not user:
                cleared.append("%s: %s had no User ID" % (row.name, row.approver))

        if cleared:
            frappe.log_error(
                message="\n".join(cleared),
                title="sf_trading: approver cleared, Employee had no User ID (%s)" % doctype,
            )
