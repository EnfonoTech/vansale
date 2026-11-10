import frappe


def item_permission_query(user=None):
	"""Restrict Item list/search based on Company User Permissions.

	List view:
	  - No Company User Permission → show all items.
	  - Has Company User Permission(s) → show only items that have an Item Default
	    for at least one of the user's permitted companies.

	Link fields:
	  Items with no Item Default row are excluded when a company filter is present
	  (enforced by search_items_with_stock_and_rate per-request; this query covers
	  list view and any search that doesn't pass a company filter explicitly).

	Bypassed for System Manager and Administrator.
	"""
	user = user or frappe.session.user
	if user in ("Administrator", "Guest"):
		return ""

	if "System Manager" in frappe.get_roles(user):
		return ""

	# Link-field searches go through /api/method/frappe.desk.search.search_link.
	# For those, return "" — search_items_with_stock_and_rate pre-filters by
	# Item Default for the form's company before calling item_query, so the
	# User Permission restriction here would fight that and block valid items.
	try:
		req = getattr(frappe.local, "request", None)
		if req and "search_link" in (req.path or ""):
			return ""
	except Exception:
		pass

	companies = frappe.get_all(
		"User Permission",
		filters={"user": user, "allow": "Company"},
		pluck="for_value",
		ignore_permissions=True,
	)
	if not companies:
		return ""

	company_list = ", ".join([frappe.db.escape(c) for c in companies])
	return (
		"`tabItem`.`name` IN ("
		"  SELECT `parent` FROM `tabItem Default`"
		"  WHERE `company` IN ({0})"
		")".format(company_list)
	)


def override_cost_center_from_branch(doc, method=None):
	"""before_validate: if the document has cost_center set, push it to every
	tax row (and item row) unconditionally. If the form cost_center is blank,
	nothing is changed."""
	doc_cc = doc.get("cost_center")
	if not doc_cc:
		return

	for item in doc.get("items") or []:
		if hasattr(item, "cost_center"):
			item.cost_center = doc_cc

	for tax in doc.get("taxes") or []:
		if hasattr(tax, "cost_center"):
			tax.cost_center = doc_cc


# Accounting dimensions pushed from the document header down to each item row.
# cost_center is also pushed to tax rows (handled separately below).
_ITEM_DIMENSIONS = ("branch", "cost_center", "project")


def propagate_dimensions_to_items(doc, method=None):
	"""before_validate: push every accounting dimension set on the header
	(branch, cost_center, project) down to each item row, and cost_center to
	tax rows. Blank header dimensions are left untouched so nothing is wiped.
	"""
	for field in _ITEM_DIMENSIONS:
		val = doc.get(field)
		if not val:
			continue
		for item in doc.get("items") or []:
			if hasattr(item, field):
				item.set(field, val)

	doc_cc = doc.get("cost_center")
	if doc_cc:
		for tax in doc.get("taxes") or []:
			if hasattr(tax, "cost_center"):
				tax.cost_center = doc_cc


def _branch_letter_head(branch):
	"""Return the custom letter head defined on a Branch, or None.

	Guards against the custom_letter_head column not existing yet (fixture
	not migrated) so callers never hit a SQL 'Unknown column' error.
	"""
	if not branch:
		return None
	if not frappe.db.has_column("Branch", "custom_letter_head"):
		return None
	return frappe.db.get_value("Branch", branch, "custom_letter_head")


def set_letter_head_from_branch(doc, method=None):
	"""before_validate: set the document's letter head from its Branch.

	When the document has a branch whose Branch master defines a custom
	letter head, apply it. Blank branch / blank branch letter head leaves
	the document's own letter head untouched.
	"""
	if not doc.get("branch"):
		return
	if not doc.meta.has_field("letter_head"):
		return

	letter_head = _branch_letter_head(doc.branch)
	if letter_head:
		doc.letter_head = letter_head


@frappe.whitelist()
def get_branch_dimension_defaults(branch: str):
	"""Return the form defaults driven by a Branch.

	- letter_head: from the Branch master's custom_letter_head
	- cost_center / set_warehouse: first row of the linked Branch Configuration

	Used by the form to refill values when the branch changes.
	"""
	if not branch:
		return {}

	result = {}

	letter_head = _branch_letter_head(branch)
	if letter_head:
		result["letter_head"] = letter_head

	cfg = frappe.db.get_value("Branch Configuration", {"branch": branch}, "name")
	if cfg:
		result["cost_center"] = frappe.db.get_value(
			"Branch Configuration Cost Center",
			{"parent": cfg, "parenttype": "Branch Configuration"},
			"cost_center",
			order_by="idx asc",
		)
		result["set_warehouse"] = frappe.db.get_value(
			"Branch Configuration Warehouse",
			{"parent": cfg, "parenttype": "Branch Configuration"},
			"warehouse",
			order_by="idx asc",
		)

	return result



def _resolve_user_branch(user, company=None):
	"""Return the most relevant Branch Configuration name for the user.

	Resolution order:
	  1. Branch Configuration whose company matches the doc's company.
	  2. First Branch Configuration the user belongs to (any company).
	"""
	branches = frappe.get_all(
		"Branch Configuration User",
		filters={"user": user},
		pluck="parent",
		ignore_permissions=True,
	)
	if not branches:
		return None

	if company:
		same_company = frappe.get_all(
			"Branch Configuration",
			filters={"name": ["in", branches], "company": company},
			pluck="name",
			ignore_permissions=True,
		)
		if same_company:
			return same_company[0]

	return branches[0]


def _branch_mops_by_type(branch_name):
	"""Return (cash_mops, bank_mops) lists for the branch, in child-table order."""
	cash, bank = [], []
	if not branch_name:
		return cash, bank

	rows = frappe.get_all(
		"Branch Configuration Mode of Payment",
		filters={"parent": branch_name, "parenttype": "Branch Configuration"},
		fields=["mode_of_payment"],
		order_by="idx asc",
		ignore_permissions=True,
	)
	if not rows:
		return cash, bank

	mop_names = [r.mode_of_payment for r in rows if r.mode_of_payment]
	if not mop_names:
		return cash, bank

	type_map = {
		m["name"]: (m.get("type") or "")
		for m in frappe.get_all(
			"Mode of Payment",
			filters={"name": ["in", mop_names]},
			fields=["name", "type"],
			ignore_permissions=True,
		)
	}
	for r in rows:
		t = type_map.get(r.mode_of_payment)
		if t == "Cash":
			cash.append(r.mode_of_payment)
		elif t == "Bank":
			bank.append(r.mode_of_payment)
	return cash, bank


def _mop_account_for_company(mop, company):
	if not (mop and company):
		return None
	return frappe.db.get_value(
		"Mode of Payment Account",
		{"parent": mop, "company": company},
		"default_account",
	)


def override_payment_accounts_from_branch(doc, method=None):
	"""before_validate on Sales Invoice: constrain payment rows to the
	user's Branch Configuration MoP allowlist.

	- Cash/Bank rows not in the branch list are swapped to the branch default.
	- If the branch has no MoPs of a type, rows of that type are dropped.
	- Other types (General, Phone, etc.) pass through untouched.
	- Bypassed for Administrator, Guest, System Manager, Sales Manager.
	"""
	user = frappe.session.user
	if user in ("Administrator", "Guest"):
		return

	roles = set(frappe.get_roles(user))
	if roles & {"System Manager", "Sales Manager", "Sales Master Manager"}:
		return

	payments = doc.get("payments") or []
	if not payments:
		return

	branch = _resolve_user_branch(user, company=doc.company)
	if not branch:
		return

	cash_mops, bank_mops = _branch_mops_by_type(branch)
	if not cash_mops and not bank_mops:
		# Branch has no MoP rows configured — opt-out, leave untouched
		return

	type_cache = {}

	def mop_type(name):
		if name not in type_cache:
			type_cache[name] = frappe.db.get_value("Mode of Payment", name, "type") or ""
		return type_cache[name]

	kept_rows = []
	for row in payments:
		mop = getattr(row, "mode_of_payment", None)
		if not mop:
			kept_rows.append(row)
			continue

		t = mop_type(mop)
		if t == "Cash":
			allowed = cash_mops
		elif t == "Bank":
			allowed = bank_mops
		else:
			kept_rows.append(row)
			continue

		if not allowed:
			# Branch opted out of this type — drop the row
			continue

		if mop not in allowed:
			row.mode_of_payment = allowed[0]

		new_account = _mop_account_for_company(row.mode_of_payment, doc.company)
		if new_account:
			row.account = new_account

		kept_rows.append(row)

	if len(kept_rows) != len(payments):
		doc.set("payments", [])
		for r in kept_rows:
			doc.append("payments", r.as_dict() if hasattr(r, "as_dict") else r)
