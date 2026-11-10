import frappe
from frappe.model.document import Document


class BranchConfiguration(Document):

	def validate(self):
		if self.company:
			for w in self.warehouse:
				if w.warehouse:
					wh_company = frappe.db.get_value("Warehouse", w.warehouse, "company")
					if wh_company and wh_company != self.company:
						frappe.throw(
							f"Warehouse <b>{w.warehouse}</b> belongs to company <b>{wh_company}</b>, "
							f"not <b>{self.company}</b>. Please select a warehouse from the correct company."
						)

			for c in self.cost_center:
				if c.cost_center:
					cc_company = frappe.db.get_value("Cost Center", c.cost_center, "company")
					if cc_company and cc_company != self.company:
						frappe.throw(
							f"Cost Center <b>{c.cost_center}</b> belongs to company <b>{cc_company}</b>, "
							f"not <b>{self.company}</b>. Please select a cost center from the correct company."
						)

	def before_save(self):
		if self.is_new():
			return

		old_doc = self.get_doc_before_save()

		old_users = {d.user for d in old_doc.user}
		new_users = {d.user for d in self.user}
		removed_users = old_users - new_users

		old_letter_head = _branch_letter_head(old_doc.get("branch"))

		for user in removed_users:
			if old_doc.get("branch"):
				_safe_delete_permission(user, "Branch", old_doc.branch, exclude_branch=self.name)

			if old_letter_head:
				_safe_delete_permission(user, "Letter Head", old_letter_head, exclude_branch=self.name)

			if old_doc.get("company"):
				_safe_delete_permission(user, "Company", old_doc.company, exclude_branch=self.name)

			for w in old_doc.warehouse:
				_safe_delete_permission(user, "Warehouse", w.warehouse, exclude_branch=self.name)

			for c in old_doc.cost_center:
				_safe_delete_permission(user, "Cost Center", c.cost_center, exclude_branch=self.name)

			for m in old_doc.mode_of_payment:
				_safe_delete_permission(user, "Mode of Payment", m.mode_of_payment, exclude_branch=self.name)

			old_role_profile = next(
				(u.get("role_profile") for u in old_doc.user if u.user == user), None
			)
			if old_role_profile:
				_maybe_remove_roles_from_profile(user, old_role_profile, exclude_branch=self.name)

		# Remove MoP permissions for retained users when MOPs are removed
		old_mops = {m.mode_of_payment for m in old_doc.mode_of_payment if m.mode_of_payment}
		new_mops = {m.mode_of_payment for m in self.mode_of_payment if m.mode_of_payment}
		removed_mops = old_mops - new_mops
		if removed_mops:
			for user in old_users & new_users:
				for mop in removed_mops:
					_safe_delete_permission(user, "Mode of Payment", mop, exclude_branch=self.name)

		# Remove old company permission for retained users when company changes
		old_company = old_doc.get("company")
		new_company = self.get("company")
		if old_company and old_company != new_company:
			for u in self.user:
				_safe_delete_permission(u.user, "Company", old_company, exclude_branch=self.name)

		# Remove old branch + letter head permissions for retained users when branch changes
		old_branch = old_doc.get("branch")
		new_branch = self.get("branch")
		if old_branch and old_branch != new_branch:
			for u in self.user:
				_safe_delete_permission(u.user, "Branch", old_branch, exclude_branch=self.name)
				if old_letter_head:
					_safe_delete_permission(u.user, "Letter Head", old_letter_head, exclude_branch=self.name)

	def on_update(self):
		self.create_permissions()

		# Enforce a single default branch per user: if a user is marked default
		# here, clear that flag on the same user in every other Branch Config.
		for u in self.user:
			if u.get("is_default_branch"):
				_clear_default_branch_elsewhere(u.user, keep_branch=self.name)

		# Recompute User Permission defaults so every default value for a user
		# (branch, company, warehouse, cost center, MoP) comes from ONE config.
		for user in {u.user for u in self.user}:
			_normalize_user_defaults(user)

	def create_permissions(self):
		branch_letter_head = _branch_letter_head(self.branch) if self.branch else None

		for u in self.user:
			if self.branch:
				create_permission(u.user, "Branch", self.branch)

			# Restrict the user to this branch's letter head (accumulates across
			# multiple branch configs; default follows the primary branch).
			if branch_letter_head:
				create_permission(u.user, "Letter Head", branch_letter_head)

			if self.company:
				create_permission(u.user, "Company", self.company)

			for w in self.warehouse:
				create_permission(u.user, "Warehouse", w.warehouse)

			for c in self.cost_center:
				create_permission(u.user, "Cost Center", c.cost_center)

			for m in self.mode_of_payment:
				create_permission(u.user, "Mode of Payment", m.mode_of_payment)

			# Grant access to the company's root cost center (used in tax templates)
			if self.company:
				company_default_cc = frappe.db.get_value("Company", self.company, "cost_center")
				if company_default_cc:
					create_permission(u.user, "Cost Center", company_default_cc)

			role_profile = u.get("role_profile")
			if role_profile:
				_apply_roles_from_profile(u.user, role_profile)


# ---------------------------------------------------------------------------
# User Permission helpers
# ---------------------------------------------------------------------------

def create_permission(user, allow, value):
	"""Create a non-default User Permission. Defaults are assigned afterwards
	by _normalize_user_defaults so they all come from one branch config."""
	if not value:
		return

	if frappe.db.exists("User Permission", {"user": user, "allow": allow, "for_value": value}):
		return

	try:
		doc = frappe.new_doc("User Permission")
		doc.user = user
		doc.allow = allow
		doc.for_value = value
		doc.is_default = 0
		doc.apply_to_all_doctypes = 1
		doc.insert(ignore_permissions=True)
	except frappe.exceptions.DuplicateEntryError:
		pass
	except Exception:
		frappe.log_error(frappe.get_traceback(), f"BranchConfig: create {allow} for {user}")


# Allow types managed by Branch Configuration — only these are touched when
# normalizing User Permission defaults (leaves permissions from other apps alone).
_MANAGED_ALLOWS = ("Branch", "Company", "Warehouse", "Cost Center", "Mode of Payment", "Letter Head")


def _branch_letter_head(branch):
	"""Return the custom letter head defined on a Branch, or None.

	Guards against the custom_letter_head column not existing yet (fixture not
	migrated) so this never raises an 'Unknown column' SQL error.
	"""
	if not branch:
		return None
	if not frappe.db.has_column("Branch", "custom_letter_head"):
		return None
	return frappe.db.get_value("Branch", branch, "custom_letter_head")


def _clear_default_branch_elsewhere(user, keep_branch):
	"""Untick is_default_branch for this user in every Branch Config except keep_branch."""
	frappe.db.sql(
		"""
		UPDATE `tabBranch Configuration User`
		SET is_default_branch = 0
		WHERE user = %s
		  AND parenttype = 'Branch Configuration'
		  AND parent != %s
		  AND is_default_branch = 1
		""",
		(user, keep_branch),
	)


def _get_primary_branch_config(user):
	"""Return the Branch Configuration that provides this user's default values.

	Prefers the config where the user's row has is_default_branch ticked;
	falls back to the earliest-created config the user belongs to.
	"""
	rows = frappe.get_all(
		"Branch Configuration User",
		filters={"user": user, "parenttype": "Branch Configuration"},
		fields=["parent", "is_default_branch"],
		ignore_permissions=True,
	)
	if not rows:
		return None

	marked = [r.parent for r in rows if r.is_default_branch]
	candidates = marked or [r.parent for r in rows]

	configs = frappe.get_all(
		"Branch Configuration",
		filters={"name": ["in", candidates]},
		pluck="name",
		order_by="creation asc",
		ignore_permissions=True,
	)
	return configs[0] if configs else candidates[0]


def _normalize_user_defaults(user):
	"""Make every default User Permission for the user come from one branch config.

	The primary config's branch, company, first warehouse, first cost center and
	first MoP become is_default=1; all other managed permissions become is_default=0.
	This prevents defaults being split across different branches.
	"""
	primary = _get_primary_branch_config(user)
	if not primary:
		return

	cfg = frappe.get_doc("Branch Configuration", primary)

	default_pairs = set()
	if cfg.get("branch"):
		default_pairs.add(("Branch", cfg.branch))
		lh = _branch_letter_head(cfg.branch)
		if lh:
			default_pairs.add(("Letter Head", lh))
	if cfg.get("company"):
		default_pairs.add(("Company", cfg.company))
	if cfg.warehouse:
		default_pairs.add(("Warehouse", cfg.warehouse[0].warehouse))
	if cfg.cost_center:
		default_pairs.add(("Cost Center", cfg.cost_center[0].cost_center))
	if cfg.mode_of_payment:
		default_pairs.add(("Mode of Payment", cfg.mode_of_payment[0].mode_of_payment))

	perms = frappe.get_all(
		"User Permission",
		filters={"user": user, "allow": ["in", _MANAGED_ALLOWS]},
		fields=["name", "allow", "for_value", "is_default"],
		ignore_permissions=True,
	)
	for p in perms:
		should = 1 if (p.allow, p.for_value) in default_pairs else 0
		if p.is_default != should:
			frappe.db.set_value("User Permission", p.name, "is_default", should, update_modified=False)

	frappe.clear_cache(user=user)


def delete_permission(user, allow, value):
	if not value:
		return
	for p in frappe.get_all("User Permission", filters={"user": user, "allow": allow, "for_value": value}, pluck="name"):
		frappe.delete_doc("User Permission", p, ignore_permissions=True)


def _safe_delete_permission(user, allow, value, exclude_branch=None):
	"""Delete a User Permission only if no other Branch Configuration still grants it."""
	if not value:
		return

	other_branches = [
		c.parent for c in frappe.get_all(
			"Branch Configuration User",
			filters={"user": user},
			fields=["parent"],
			ignore_permissions=True,
		)
		if c.parent != exclude_branch
	]

	if other_branches:
		still_granted = False
		if allow == "Branch":
			still_granted = frappe.db.exists(
				"Branch Configuration",
				{"name": ["in", other_branches], "branch": value},
			)
		elif allow == "Warehouse":
			still_granted = frappe.db.exists(
				"Branch Configuration Warehouse",
				{"parent": ["in", other_branches], "warehouse": value},
			)
		elif allow == "Cost Center":
			still_granted = frappe.db.exists(
				"Branch Configuration Cost Center",
				{"parent": ["in", other_branches], "cost_center": value},
			)
		elif allow == "Mode of Payment":
			still_granted = frappe.db.exists(
				"Branch Configuration Mode of Payment",
				{"parent": ["in", other_branches], "mode_of_payment": value},
			)
		elif allow == "Company":
			still_granted = frappe.db.exists(
				"Branch Configuration",
				{"name": ["in", other_branches], "company": value},
			)
		elif allow == "Letter Head":
			# Granted if any other config's branch resolves to the same letter head.
			other_branch_values = frappe.get_all(
				"Branch Configuration",
				filters={"name": ["in", other_branches]},
				pluck="branch",
				ignore_permissions=True,
			)
			still_granted = any(
				_branch_letter_head(b) == value for b in other_branch_values if b
			)

		if still_granted:
			return

	delete_permission(user, allow, value)


# ---------------------------------------------------------------------------
# Role helpers — direct DB operations (no user_doc.save) so Frappe's
# User.validate role-profile sync cannot wipe accumulated roles.
# ---------------------------------------------------------------------------

def _ensure_system_user(user):
	current_type = frappe.db.get_value("User", user, "user_type")
	if current_type and current_type != "System User":
		frappe.db.set_value("User", user, "user_type", "System User")


def _roles_in_profile(role_profile):
	return set(frappe.get_all(
		"Has Role",
		filters={"parent": role_profile, "parenttype": "Role Profile"},
		pluck="role",
		ignore_permissions=True,
	))


def _apply_roles_from_profile(user, role_profile):
	"""Insert Has Role rows directly — bypasses user_doc.save() to prevent
	Frappe's User.validate from wiping accumulated roles across multiple Branch Configs."""
	if not role_profile:
		return

	if not frappe.db.exists("Role Profile", role_profile):
		frappe.msgprint(
			f"Role Profile <b>{role_profile}</b> does not exist.",
			indicator="orange",
			alert=True,
		)
		return

	_ensure_system_user(user)

	new_roles = _roles_in_profile(role_profile)
	if not new_roles:
		return

	existing_roles = set(frappe.db.get_all(
		"Has Role",
		filters={"parent": user, "parenttype": "User"},
		pluck="role",
		ignore_permissions=True,
	))

	for role in new_roles - existing_roles:
		try:
			frappe.db.sql(
				"""INSERT IGNORE INTO `tabHas Role`
				(name, creation, modified, modified_by, owner, docstatus, idx,
				 parent, parentfield, parenttype, role)
				VALUES (%s, NOW(), NOW(), %s, %s, 0, 0, %s, 'roles', 'User', %s)""",
				(
					frappe.generate_hash(length=10),
					frappe.session.user,
					frappe.session.user,
					user,
					role,
				),
			)
		except Exception:
			frappe.log_error(
				f"Branch Configuration: could not grant role {role!r} to user {user!r}",
				"BranchConfig role grant",
			)

	frappe.clear_cache(user=user)


def _maybe_remove_roles_from_profile(user, role_profile, exclude_branch=None):
	if not role_profile:
		return

	other_profiles = {
		c.role_profile for c in frappe.get_all(
			"Branch Configuration User",
			filters={"user": user},
			fields=["parent", "role_profile"],
			ignore_permissions=True,
		)
		if c.parent != exclude_branch and c.role_profile
	}

	roles_to_remove = _roles_in_profile(role_profile)
	roles_to_keep = set()
	for profile in other_profiles:
		roles_to_keep |= _roles_in_profile(profile)

	to_delete = roles_to_remove - roles_to_keep
	if not to_delete:
		return

	frappe.db.delete("Has Role", {
		"parent": user,
		"parenttype": "User",
		"role": ["in", list(to_delete)],
	})
	frappe.clear_cache(user=user)
