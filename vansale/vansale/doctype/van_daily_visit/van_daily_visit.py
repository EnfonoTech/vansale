# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt
"""Van Daily Visit — per-user+customer+date visit state.

Replaces the `Van Route Stop` child table as the authoritative state
holder for a driver's day. Route plans are gone; the driver always sees
the live list of customers tagged to their sales_person, and each action
(start/end/skip) upserts one of these rows.

Uniqueness is enforced at the app layer (route.py `_upsert_visit`)
because Frappe doesn't support composite unique keys in doctype JSON —
we guard by always doing a `get_value({user, customer, visit_date})`
before insert.
"""
from __future__ import annotations

from frappe.model.document import Document


class VanDailyVisit(Document):
    pass
