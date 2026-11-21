import frappe
from frappe import _
from frappe.model.document import Document


class VansalePushSubscription(Document):
    """One browser's Web Push subscription, named by sha256 of its endpoint.
    Written only by `vansale.steelforce.approvals_push`."""

    def before_insert(self):
        from vansale.steelforce.approvals_push import endpoint_hash

        self.endpoint_hash = endpoint_hash(self.endpoint)

    def validate(self):
        if not self.is_new() and self.has_value_changed("endpoint"):
            frappe.throw(_("The endpoint of a push subscription cannot change"))
