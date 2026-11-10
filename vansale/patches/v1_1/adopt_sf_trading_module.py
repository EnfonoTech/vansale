"""Point the "Sf Trading" Module Def at vansale.

The sf_trading app's DocTypes, reports and pages now live in this app. A site that
ran sf_trading still has a Module Def row naming sf_trading as the owner; repoint it
so developer-mode exports land here and the module list shows the right app.
"""

import frappe


def execute() -> None:
	if frappe.db.exists("Module Def", "Sf Trading"):
		frappe.db.set_value("Module Def", "Sf Trading", "app_name", "vansale")
