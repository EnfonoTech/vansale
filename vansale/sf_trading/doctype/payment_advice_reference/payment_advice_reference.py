# apps/vansale/vansale/sf_trading/doctype/payment_advice_reference/payment_advice_reference.py
"""Child rows of a Payment Advice — one outstanding document each.

All derivation (amounts, ageing, allocation) happens in the parent's validate() so a single
pass fills the whole table; this controller holds no logic of its own.
"""

from frappe.model.document import Document


class PaymentAdviceReference(Document):
	pass
