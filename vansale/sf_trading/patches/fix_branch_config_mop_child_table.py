import frappe


def execute():
	if not frappe.db.has_column("Branch Configuration Mode of Payment", "parent"):
		frappe.db.sql("""
			ALTER TABLE `tabBranch Configuration Mode of Payment`
			ADD COLUMN `parent` varchar(140) DEFAULT NULL,
			ADD COLUMN `parentfield` varchar(140) DEFAULT NULL,
			ADD COLUMN `parenttype` varchar(140) DEFAULT NULL,
			ADD INDEX `parent`(`parent`)
		""")
