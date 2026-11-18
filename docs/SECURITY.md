# Security model

What is exposed, who can reach it, and where the sharp edges are. Re-read §2
after adding any endpoint.

Counts here are from `scripts/gen-docs.py`; the authoritative lists are in
[`reference/API.md`](reference/API.md).

---

## 1. Roles

| Role | Granted by | Can |
| --- | --- | --- |
| `Van User` | Adding the user to a Vansale Configuration's Assigned Users | Create and submit their own invoices, payments, returns, stock entries; read reference data. No cancel, no delete. |
| `Van Manager` | Same table, role column | Everything above plus read all vans' documents, run reports, reset driver PINs, edit customers. |
| `System Manager` | ERPNext | Everything, including hand-picking a document series. |

Both roles and their DocPerms are created by `setup.after_migrate`, not by a
fixture, so they re-apply on every migrate. Edit `VAN_USER_PERMISSIONS` /
`VAN_MANAGER_PERMISSIONS` in `vansale/setup.py` — never by hand in the UI, which
the next migrate would overwrite.

Note what a Van User deliberately does **not** get: `cancel` and `delete` on
Sales Invoice and Payment Entry. A driver who mis-sells issues a return; they
cannot make a document disappear.

---

## 2. The public HTTP surface

**Every `@frappe.whitelist()` is a public HTTP endpoint** at
`/api/method/<dotted.path>`. There are currently **120**.

Adding an endpoint adds attack surface. Before merging one, confirm:

1. It scopes every query to `frappe.session.user`, **or** it calls
   `frappe.has_permission(doctype, ptype, doc=name)`.
2. It coerces every argument — `cint`, `flt`, `cstr` from `frappe.utils`. Never
   bare `int()` / `float()` on request data.
3. Any raw SQL is parameterised: `frappe.db.sql("… WHERE name = %s", (value,))`.
   A string-formatted query is a blocker, not a style note.
4. Its docstring says what it does. `gen-docs.py` publishes that docstring as the
   endpoint's public description.

### Guest-reachable endpoints — 5

These answer before any login, so they are the ones worth auditing by hand. All
five are structurally pre-login and none returns tenant data:

| Endpoint | Why it must be guest |
| --- | --- |
| `auth.login` | Authenticates. Cannot require a session. |
| `auth.login_with_pin` | Exchanges a PIN for a token on app launch. |
| `auth.site_info` | The APK probes a user-typed address before storing it. Returns only `{ok, app, app_version}` — no site, user or tenant data. |
| `util.get_csrf_token` | The web PWA needs the token to make its first write. |
| `util.version_compat` | Answers "is this SPA still compatible" before the client can authenticate. |

`allow_guest=True` requires a justification in the docstring. A new one needs a
second pair of eyes — it is the only category of change here that can expose data
to the open internet.

### Endpoints with no explicit permission call — 97

`gen-docs.py` flags these. **Absence is not proof of a hole.** Most are safe
because every query is scoped to `frappe.session.user`, or because they only read
reference data (Item, UOM, Price List) a Van User already holds DocType read
permission on.

It is a review list. What genuinely needs an explicit check, and should be
audited if it appears there:

- anything that **writes** a document belonging to someone else;
- anything that **reads by name** a document the caller may not own — the caller
  controls that name;
- anything an admin-only screen calls (`api/admin.py`), which must verify the role
  rather than assume the UI hid the button.

### Approvals endpoints — 13

`steelforce.approvals` (6) and `steelforce.approvals_extra` (7) front
`permission_manager` (PM). PM owns who may approve what, so these call PM
(`approvals._pm()`) for every decision and never copy its rules. None is guest
reachable. Stock Entry and any type whose workflow PM flags
`hide_from_approval_inbox` are refused (or left out of a list) in every one.
Ten of the thirteen are on the generated "no explicit permission call" list
because their check is in a helper or in PM, which the generator cannot see; the
last column says what each is scoped by.

| Endpoint | Verb | Scoped by |
| --- | --- | --- |
| `approvals.availability` | GET | Nothing to scope: it answers only whether PM is installed. |
| `approvals.inbox` | GET | **Session user, through PM**: only what PM's `get_my_pending_approvals` returns for them, the desk's own list. Party, amount and currency are read with `frappe.get_list` as the user, so a document they may not read shows without them. |
| `approvals.count` | GET | **Session user, through PM**: the same list as `inbox`, numbers only. |
| `approvals.detail` | GET | **Read permission** on the document. A user who cannot read it but holds an open PM action on it (PM's `_can_act_on`) gets a bare record (state, priority, creator) and nothing of the document; anyone else is refused. Fields are cut to what the user may read. |
| `approvals.apply` | POST | **PM action ownership**, after read permission: the action must be one PM's `get_transitions` offers the session user for the document's state, less PM's self-approval rule (a person asked for advice by a "return to me" forward may only recommend: the document does not move). The comment or attachment the transition requires is enforced here (PM does not enforce `require_comment`); PM's `apply_workflow` then checks again and runs the document's own hooks. |
| `approvals.apply_bulk` | POST | As `apply`, document by document: at most 20, each committed or rolled back on its own, a hidden type refuses the whole batch. |
| `approvals_extra.forward_targets` | GET | **Read permission** on the document for the caller. Offers up to 20 enabled system users who can read it (user id, full name and the workflow role they hold, nothing else), never the caller; the users are listed with `get_all` on purpose, since a desk user may pick a colleague but not read the User list. |
| `approvals_extra.forward` | POST | **PM action ownership**: PM's `forward_workflow_action` checks the caller may act on the open action. The recipient must also be an enabled system user other than the caller who can read the document (a forward does not share it). |
| `approvals_extra.return_to_originator` | POST | **PM action ownership**: PM's `return_adhoc_to_originator` checks the caller may act on the open ad-hoc action. |
| `approvals_extra.attach` | POST | **PM action ownership and read permission**: the caller must hold an open action they may act on for that document and be able to read it. Write permission on the document is not needed, and it is not a general "attach to anything": the file is private and made by the app's own upload. |
| `approvals_extra.my_requests` | GET | **Session user**: only PM Workflow Actions with `for_submitter` = the caller (`get_all` is safe for that reason). The documents are not read, only whether each still exists and is not cancelled. |
| `approvals_extra.sent_back` | GET | **Session user, through PM**: PM's `get_sent_back_documents` for the caller's own list (`all_users` is never passed). |
| `approvals_extra.history` | GET | **Session user, through PM**: PM's `get_my_approval_history` for the caller (`all_users` is never passed, so never anybody else's). |

All thirteen are inert when `permission_manager` is not installed: the reads
(`availability`, `inbox`, `count`, `forward_targets`, `my_requests`, `sent_back`,
`history`) answer "disabled", empty or zero without calling PM, and the writes
and `detail` refuse with "Approvals are not available on this site" before
reading or changing anything.

`steelforce/approvals_parity.py` is not an endpoint: it is a developer check run
from `bench execute` that compares these lists with PM's own for one user.

---

## 3. Secrets

| Secret | Where it lives | Rule |
| --- | --- | --- |
| Driver PIN | `Vansale Pin.pin_hash`, `Password` fieldtype, bcrypt | Read with `doc.get_password("pin_hash")`. `doc.pin_hash` returns a 60-asterisk mask and sends `bcrypt.checkpw` into `Invalid salt`. |
| `api_key` / `api_secret` | `User`, issued by `utils/secrets.py` | **Stable** — issued once, reused. Regenerating on login invalidates every other device that user has. |
| Android keystore | `android-capacitor/keystore/`, gitignored | Never committed. Losing it forces every user to uninstall and lose their offline queue. |
| Keystore password | `~/.vansale-<customer>-keystore-pw`, mode 600 | Never committed. |

Nothing sensitive belongs in a Client Script, a plain `Data` field, or the SPA
bundle — the bundle ships to the device and is readable.

---

## 4. Data scoping

Three layers, each doing a different job. A Van User stays in their lane even
when a document is created from the desk, not the app:

1. **User Permissions** — Company, Branch, Warehouse, Cost Center rows, created
   from the Vansale Configuration on save.
2. **`permission_query_conditions`** (`van_filters.py`) — filters list views so a
   driver's Sales Invoice list shows only their own.
3. **Explicit query scoping** in the endpoints — the customer list is the union of
   customers the user created and customers tagged with their Sales Person.

Reports enforce the same rule *inside the report*, not in the filter panel:
`vansale_report_utils.van_scope` restricts a non-manager to their own van
whatever the filters say. A report is a whitelisted endpoint like any other, so a
UI-only restriction is not a restriction.

---

## 5. Idempotency as a safety property

Every mutation carries a client-generated `client_id`. The endpoint looks it up
in `Vansale Outbox` and returns the existing document rather than creating a
second one.

This is a correctness *and* a safety property: without it, a retried request on a
flaky connection double-bills a customer. When adding a mutating endpoint, wire
`client_id` and `_record_outbox` the same way the existing ones do, and validate
inputs **before** the idempotency check — otherwise a replay can smuggle an
invalid payload through on its second attempt.

---

## 6. Known sharp edges

| Edge | Why it matters |
| --- | --- |
| `frappe.client.submit` | Rebuilds the doc from the client payload — raises `TimestampMismatchError`, and would blank omitted fields if it did not. Banned; use `invoice.submit_draft`. |
| Tax template resolution | Getting inclusive/exclusive wrong overcharges by the full tax on every line. Preview and posting share one resolver so they cannot diverge. |
| Series abbreviations | Frappe keys `tabSeries` on the resolved prefix; two doctypes sharing a template share a counter. The series table is read-only for this reason. |
| Changing the APK's server | Queued documents belong to the site that created them. Blocked while the queue is non-empty — draining them into another company's ledger would post real documents in the wrong books. |
| `allow_cors` | Must include the Capacitor origins or every native request fails with no server-side log. Applied by `install.py`, not by hand. |

---

## 7. Reporting a problem

Production sites serve clients in KSA, UAE and India, so a data-exposure bug is a
compliance matter, not just a defect. Do not open a public issue: contact the
Enfono maintainer directly, and include the endpoint path, the role you held, and
what you could reach that you should not have.
