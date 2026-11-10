# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Show the Payment Advice a voucher was paid through, in its Connections.

An advice is raised FROM a voucher — an invoice, an order, a journal — but the link only
existed in one direction: you could open an advice and see its references, while standing on
the invoice there was nothing to say an advice had ever been raised for it, let alone which
one or what state it was in. Anyone chasing "has this been sent for payment?" had to search
the Payment Advice list.

The reference lives on the `Payment Advice Reference` child table as a Dynamic Link pair
(`reference_doctype` + `reference_record`), which is the same shape ERPNext uses for Payment
Entry, so it is declared the same way: name the field in `non_standard_fieldnames` and let
Frappe resolve the child table itself.

Wired through `override_doctype_dashboards` in hooks.py for every doctype an advice may
reference. Each handler receives the dashboard the previous owner built and returns it
extended, so ERPNext's own connections are kept rather than replaced.
"""

import frappe

PAYMENT_ADVICE = "Payment Advice"
REFERENCE_FIELD = "reference_record"

# where an advice belongs on the form: beside the other ways money moves
PAYMENT_GROUP_LABELS = ("Payment", "Payments")


def add_payment_advice(data):
    """Extend a dashboard with Payment Advice, leaving everything else intact."""
    data = frappe._dict(data or {})

    fieldnames = data.setdefault("non_standard_fieldnames", {})
    fieldnames[PAYMENT_ADVICE] = REFERENCE_FIELD

    transactions = data.setdefault("transactions", [])

    # already listed by someone else — nothing to do
    for group in transactions:
        if PAYMENT_ADVICE in (group.get("items") or []):
            return data

    for group in transactions:
        label = group.get("label")
        # labels arrive translated, so compare against the translation too
        if label in PAYMENT_GROUP_LABELS or label in [frappe._(l) for l in PAYMENT_GROUP_LABELS]:
            group.setdefault("items", []).append(PAYMENT_ADVICE)
            return data

    transactions.append({"label": frappe._("Payment"), "items": [PAYMENT_ADVICE]})
    return data


# One entry point per doctype so hooks.py reads explicitly, and so a doctype can later
# diverge without disturbing the others.
def get_dashboard_data(data):
    return add_payment_advice(data)
