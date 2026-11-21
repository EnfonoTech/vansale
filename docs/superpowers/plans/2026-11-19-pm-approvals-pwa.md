# PM Approvals in the Van Sale PWA: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Permission Manager (PM) approvals to the Van Sale PWA: inbox, review, approve/reject, forward, my requests, sent back, history, bulk.

**Architecture:** New server module `vansale/steelforce/approvals.py` holds thin whitelisted wrappers over PM's own functions; pure rule and summary logic live in two small modules so they test without a site. The Vue SPA gets an Approvals area (store, views, sheets) that reads those wrappers. PM stays the only authority; vansale never re-implements a PM rule.

**Tech Stack:** Frappe v15 (Python, `unittest` + `mock`, site-free), permission_manager (PM), Vue 3 + Pinia + vue-router + vue-i18n, TypeScript, Vite, vitest (happy-dom), pnpm.

**Spec:** `docs/superpowers/specs/2026-11-19-pm-approvals-pwa-design.md` (mockups beside it in `mockups/`). Read it first; this plan only adds decisions the spec leaves to the builder.

## Global Constraints

- Branch work happens on `feat/pm-approvals`, cut from `develop_2`. Only `develop_2` is ever the integration branch. Push and merge only when the user says so; deploy to sft-uat only when the user says so; production is never touched without an explicit instruction.
- Commits are authored `sivajyothis7 <108478298+sivajyothis7@users.noreply.github.com>` and carry **no** `Co-Authored-By` trailer and no "Generated with" line. Run `git fetch` and pull the target branch before committing. Run `git commit` as its own command (never combined with other commands or a `-n` flag); use `-F <file>` for the message.
- Steel Force code goes under `vansale/steelforce/` ([SF]); this feature is inert when `permission_manager` is not installed.
- PM rules are never copied. If PM can answer, call PM (`get_my_pending_approvals`, `get_transitions`, `apply_workflow`, `get_document_lifecycle`, `forward_workflow_action`, `return_adhoc_to_originator`, `get_sent_back_documents`, `get_my_approval_history`).
- Stock Entry and any workflow with `hide_from_approval_inbox = 1` never appear anywhere in this feature.
- Every new endpoint: `@frappe.whitelist(methods=[...])`, typed arguments coerced with `cint`/`cstr`, a docstring (it becomes the public description), and a permission or `frappe.session.user` scope (`docs/SECURITY.md` §2). No raw SQL; use `frappe.qb` or `frappe.get_all`.
- All user-visible strings go through `_()` (server) and `t()` with keys in both `frontend/src/locales/en.json` and `ar.json` (client). Amounts follow company currency precision (BHD 3 decimals, SAR 2).
- Bulk cap **20** documents per batch. Refresh every **60 seconds** while the Approvals screen is open. "Overdue" means more than **30** days. Priorities: Low, Medium, High, Critical.
- Approvals need a connection and are never put in the offline queue. The cached inbox is cleared on logout and when the user changes.
- Python tests are site-free: `cd ~/frappe-bench/sites && PYTHONPATH=$HOME/dev/vansale ../env/bin/python -m unittest <module> -v` (cwd must be `sites`).

## Review Focus

Failure modes the spec implies that no task body would otherwise test; each has a pinning test in the task named.

1. A document is changed, moved on, or gone between the list load and the tap: the server's message reaches the user, nothing is committed, and the item is refetched (Tasks 4, 7).
2. The cached inbox of one user shows for the next user on the same device (Task 6).
3. A document type with no field map or sparse data: the summary degrades to the generic fallback without an exception (Task 2).
4. Three-decimal BHD versus two-decimal SAR amounts, and English/Arabic string parity (Tasks 2, 8).
5. A bulk batch where one document is refused (sf_trading or PM): the others still commit and the refusal text is kept verbatim (Task 4).

---

## Shared contracts

These shapes are used by several tasks. Python returns plain dicts; TypeScript mirrors them in `frontend/src/api/approvals.ts` (Task 6).

```text
ActionFlag   = { action: str, require_comment: bool, require_attachment: bool,
                 is_return_for_correction: bool }
ApprovalItem = { action_id: str,            # PM Workflow Action name (needed to forward)
                 doctype: str, docname: str,
                 transaction: str,          # PM's label, e.g. "Sales Return"
                 area: "Accounts"|"Purchase"|"Sales"|"Masters"|"Stock"|"Other",
                 party: str, amount: float|null, currency: str,
                 priority: "Low"|"Medium"|"High"|"Critical",
                 state: str, role_id: str, days: int, creator: str,
                 category: "Approval Pending"|"Decision Pending"|"Acknowledgement Pending",
                 is_adhoc: bool, forwarded_by: str, return_to_originator: bool,
                 is_waiting: bool, waiting_with: str,
                 available_actions: ActionFlag[] }     # static per state; for bulk hints only
Inbox        = { total: int, needs_you: int, waiting: int,
                 stats: { high: int, overdue: int },   # counted over needs_you only
                 sections: [ { category: str, items: ApprovalItem[] } ],   # needs_you items
                 waiting_items: ApprovalItem[], fetched_at: str }          # ISO datetime
ActionSpec   = { action: str, next_state: str, tone: "approve"|"reject"|"other",
                 require_comment: bool, require_attachment: bool,
                 is_return_for_correction: bool, priority: str, recommend_only: bool }
Detail       = { doctype, docname, transaction, state, priority, party, amount, currency,
                 creator, facts: [{label,value}],
                 lines: { columns: str[], rows: str[][], total: int },
                 attachments: [{name,url,is_private}], has_attachment: bool,
                 comments: [{by,when,text}],
                 route: { chain: [{state, status: "done"|"current"|"todo"}], who_can_act: str[] },
                 actions: ActionSpec[], action_id: str|null,
                 banner: null | {kind:"recommend", forwarder:str} | {kind:"waiting", holder:str}
                              | {kind:"self_owned"} | {kind:"cannot_read"},
                 can_forward: bool, desk_url: str }
BulkResult   = { results: [ {docname, ok: bool, message: str} ], ok_count: int, failed_count: int }
```

Endpoint paths are `vansale.steelforce.approvals.<function>`.

## File Structure

| File | Responsibility |
|---|---|
| `vansale/steelforce/approvals_rules.py` (new) | Pure rules: tone, required inputs, apply check, area, stats. No `frappe` import |
| `vansale/steelforce/approvals_summary.py` (new) | Pure summary building: party/amount field choice, key facts, line tables, value formatting |
| `vansale/steelforce/approvals.py` (new) | Whitelisted endpoints and the PM bridge (`_pm()`); all I/O |
| `vansale/steelforce/approvals_parity.py` (new) | Read-only parity report against PM's own desk functions (a dev check, not whitelisted) |
| `vansale/api/me.py` (modify) | `config_defaults` adds `approvals: {enabled}` |
| `vansale/tests/_site_free.py`, `test_approvals_rules.py`, `test_approvals_summary.py`, `test_approvals_api.py`, `test_approvals_parity.py` (new) | Site-free tests |
| `frontend/src/api/approvals.ts` (new) | Types and calls |
| `frontend/src/features/approvals/{rules,format,filter,cache}.ts` (new) + `__tests__/` | Pure client logic |
| `frontend/src/stores/approvals.ts` (new), `stores/session.ts` (modify) | State, polling, cache, capability flag |
| `frontend/src/views/{ApprovalsView,ApprovalDetailView}.vue`, `frontend/src/components/{ApprovalCard,ApprovalActionSheet,ForwardSheet,BulkConfirmSheet}.vue` (new) | Screens |
| `frontend/src/app/router.ts`, `components/{BottomNav,TopAppBar}.vue`, `views/{DashboardView,MoreView}.vue`, `locales/{en,ar}.json` (modify) | Wiring |

---

### Task 0: Workspace and baseline

**Files:** none changed in the repo apart from copying the spec, mockups and this plan in.

- [ ] **Step 1: Clone outside iCloud and set identity.** `gh repo clone EnfonoTech/vansale ~/dev/vansale -- --branch develop_2`, then in the clone `git config user.name "sivajyothis7"` and `git config user.email "108478298+sivajyothis7@users.noreply.github.com"`.
- [ ] **Step 2: Verify the base.** `git fetch origin && git status -sb` shows `## develop_2...origin/develop_2` with no ahead/behind. Create the branch: `git switch -c feat/pm-approvals`.
- [ ] **Step 3: Bring in the docs.** Copy `~/Documents/Enfono General/vansale/docs/superpowers/{specs,plans}` into the clone's `docs/superpowers/`, then commit as its own command with message `docs: PM approvals design and plan`.
- [ ] **Step 4: Baseline frontend.** In `frontend/`: `pnpm install`, `pnpm type-check`, `pnpm test`. Expected: type-check clean, all existing tests pass (the plan doc recorded 86; note the actual number).
- [ ] **Step 5: Baseline Python harness.** `cd ~/frappe-bench/sites && PYTHONPATH=$HOME/dev/vansale ../env/bin/python -c "import vansale.steelforce; print('ok')"` prints `ok`.

### Task 1: Pure rules module

**Files:**
- Create: `vansale/steelforce/approvals_rules.py`, `vansale/tests/_site_free.py`
- Test: `vansale/tests/test_approvals_rules.py`

**Interfaces:**
- Produces (all pure, no `frappe` import):
  - `tone_of(action: str, is_return_for_correction: bool) -> str`: `"reject"` if the flag is set or the action starts with "reject" (case-insensitive); `"other"` if it starts with "request"; else `"approve"`.
  - `required_inputs(require_comment: bool, require_attachment: bool, is_return_for_correction: bool, has_attachment: bool) -> dict[str, bool]` returning `{"comment": ..., "attachment": ...}`; comment is required when `require_comment` or `is_return_for_correction`; attachment is required when `require_attachment` and `not has_attachment`.
  - `check_apply(spec: dict | None, comment: str | None, has_attachment: bool) -> str | None` returning `None` when allowed, else `"not_allowed"`, `"comment_required"` or `"attachment_required"` (a whitespace-only comment counts as empty). When `spec["recommend_only"]` is true, comment and attachment are optional.
  - `area_of(doctype: str) -> str`: Accounts = Journal Entry, Payment Entry, Payment Advice, Payment Request; Purchase = Purchase Invoice, Purchase Order, Purchase Receipt; Sales = Sales Invoice, Sales Order, Quotation, Delivery Note; Masters = Customer, Supplier, Item, SF Master Change Request; Stock = Stock Reconciliation, Material Request, Stock Entry; anything else `"Other"`.
  - `inbox_stats(needs_you_items: list[dict]) -> dict` returning `{"high": int, "overdue": int}` (High and Critical; `days > 30`).
- `_site_free.py` exposes `setup_site_free()` / `teardown_site_free()` that set `frappe.local.flags`, `message_log`, `lang`, `session`, and patch `frappe.get_system_settings` to return `None` (see the site-free test recipe in the global constraints).

- [ ] **Step 1: Write the failing tests** in `test_approvals_rules.py`. Assertions, with the real action names found on sft-uat:
  - `tone_of("Approve", False) == "approve"`, `("Send for Approval", False) == "approve"`, `("Accept", False) == "approve"`, `("Approve Cancellation", False) == "approve"`, `("Reject", True) == "reject"`, `("Reject Cancellation", False) == "reject"`, `("Request Cancellation", False) == "other"`, `("Anything", True) == "reject"`.
  - `required_inputs(False, False, True, False) == {"comment": True, "attachment": False}`; `(True, False, False, False)["comment"] is True`; `(False, True, False, False)["attachment"] is True`; `(False, True, False, True)["attachment"] is False`.
  - `check_apply(None, "x", True) == "not_allowed"`; a return-for-correction spec with `comment="  "` gives `"comment_required"`; a `require_attachment` spec with `has_attachment=False` gives `"attachment_required"`; a `recommend_only` spec with no comment gives `None`; a plain approve spec gives `None`.
  - `area_of("Journal Entry") == "Accounts"`, `("Customer") == "Masters"`, `("Quotation") == "Sales"`, `("Something Else") == "Other"`.
  - `inbox_stats` over days `[30, 31, 5]` with priorities `["High", "Critical", "Low"]` gives `{"high": 2, "overdue": 1}`.
- [ ] **Step 2: Run** `cd ~/frappe-bench/sites && PYTHONPATH=$HOME/dev/vansale ../env/bin/python -m unittest vansale.tests.test_approvals_rules -v`. Expected: FAIL (module missing).
- [ ] **Step 3: Implement** the five functions in `approvals_rules.py`; write `_site_free.py`.
- [ ] **Step 4: Run again.** Expected: all pass.
- [ ] **Step 5: Commit** `feat(approvals): pure rules for tone, required inputs and apply check`.

### Task 2: Summary module

**Files:**
- Create: `vansale/steelforce/approvals_summary.py`
- Test: `vansale/tests/test_approvals_summary.py`

**Interfaces:**
- Produces (pure; callers pass a duck-typed meta):
  - `pick_party_amount(has_field: Callable[[str], bool]) -> tuple[str | None, str | None]`: party field is the first present of `customer_name, supplier_name, party_name, party, customer, supplier, title`; amount field the first present of `grand_total, rounded_total, total_debit, paid_amount, amount, total_amount`.
  - `format_value(fieldtype: str, value, precision: int) -> str | None`: Check gives "Yes"/"No"; Currency/Float/Percent use thousands grouping with `precision` decimals; Int plain; Date/Datetime ISO string; dict/list return `None`; everything else `str(value)`.
  - `key_facts(fields: list, doc: dict, precision: int, limit: int = 8) -> list[dict]`: `fields` are objects with `fieldname, label, fieldtype, hidden, print_hide, in_preview, bold, in_list_view`; returns `[{"label", "value"}]` using the desk preview's rule: skip layout/long-text/attachment/table types and the technical names listed in the desk's `SKIP_NAMES` (`exchange_rate, naming_series, amended_from, docstatus, idx, owner, modified, creation, name, workflow_state, base_*`, taxes, discounts, remarks, addresses and similar; copy the set from `permission_manager/public/js/components/approval_inbox.js` `_load_preview`), keep fields with a value, order by `in_preview`, then `bold`, then `in_list_view`, then the rest, cap at `limit`.
  - `LINE_TABLES: dict[str, tuple[str, list[tuple[str, str]]]]` mapping a doctype to `(child_table_fieldname, [(column_fieldname, header)])` for Journal Entry (`accounts`: account, debit_in_account_currency, credit_in_account_currency), Purchase Invoice / Purchase Order / Sales Invoice / Sales Order / Quotation (`items`: item_name, qty, amount), Payment Entry (`references`: reference_doctype, reference_name, allocated_amount), Stock Reconciliation (`items`: item_code, qty, valuation_rate).
  - `first_lines(doctype: str, doc: dict, precision: int, limit: int = 3) -> dict` returning `{"columns", "rows", "total"}`; for a doctype not in `LINE_TABLES` or with no rows returns `{"columns": [], "rows": [], "total": 0}`.

- [ ] **Step 1: Failing tests.**
  - `pick_party_amount` with fields `{total_debit, title}` returns `("title", "total_debit")`; `{supplier_name, grand_total}` returns `("supplier_name", "grand_total")`; `{party_name, paid_amount}` returns `("party_name", "paid_amount")`; an empty set returns `(None, None)` (Review Focus 3).
  - `format_value("Currency", 749.82, 3) == "749.820"`; `("Currency", 1200, 2) == "1,200.00"`; `("Check", 1, 0) == "Yes"`; `("Table", [1], 0) is None` (Review Focus 4).
  - `key_facts` with 12 candidate fields returns exactly 8, preview-marked first; skips `naming_series`, `docstatus` and Table fields; returns `[]` when no field has a value (no exception).
  - `first_lines("Journal Entry", doc_with_5_rows, 3)` returns 3 rows, `total == 5`, `columns == ["Account", "Debit", "Credit"]`; `first_lines("Customer", {}, 3)` returns the empty shape.
- [ ] **Step 2: Run** the module; expected FAIL.
- [ ] **Step 3: Implement** the functions above.
- [ ] **Step 4: Run;** expected pass.
- [ ] **Step 5: Commit** `feat(approvals): pure summary builders`.

### Task 3: Inbox, counts and capability endpoints

**Files:**
- Create: `vansale/steelforce/approvals.py`
- Modify: `vansale/api/me.py` (inside `config_defaults`, add `"approvals": {"enabled": approvals.is_available()}`)
- Test: `vansale/tests/test_approvals_api.py`

**Interfaces:**
- Consumes: Task 1 (`area_of`, `inbox_stats`), Task 2 (`pick_party_amount`).
- Produces in `approvals.py`:
  - `is_available() -> bool`: `permission_manager` is installed and the table `PM Workflow Action` exists.
  - `_pm()`: returns a small namespace of PM callables imported lazily (`get_my_pending_approvals`, `get_transitions`, `apply_workflow`, `has_approval_access`, `get_open_return_adhoc_action`, `get_document_lifecycle`, `forward_workflow_action`, `return_adhoc_to_originator`, `get_sent_back_documents`, `get_my_approval_history`); tests patch this one function.
  - `@whitelist(GET) availability() -> {"enabled": bool}`.
  - `@whitelist(GET) inbox() -> Inbox` and `@whitelist(GET) count() -> {"total","needs_you","waiting","high","overdue"}`. `total` equals PM's `get_my_pending_approvals()["total"]`; `waiting` counts items with `is_waiting`; `needs_you = total - waiting`; `inbox()` builds `ApprovalItem`s from PM's items (`action_id` = PM item `name`) and fills `party`, `amount`, `currency` with one `frappe.get_all` per doctype (never per row), `forwarded_by` from the ad-hoc row's `adhoc_for` action `completed_by` (full name), and `available_actions` as `ActionFlag`s read from the active `PM Workflow Transition` rows for that doctype and state (one query). When not available every function returns the empty shape (`total` 0, `sections` `[]`).

- [ ] **Step 1: Failing tests** (patch `_pm` and the enrichment helper `_party_amounts`): an inbox of 5 PM items with 2 `is_waiting` gives `total == 5`, `waiting == 2`, `needs_you == 3`, `len(waiting_items) == 2`, the three needs-you items in `sections` grouped by `category`; `stats` equals `inbox_stats` over the three; `count()` returns the same numbers; with `is_available` patched False every function returns zeros and no PM call is made; an item with `is_adhoc` and an `adhoc_for` action completed by a user gets `forwarded_by` set to that user's full name.
- [ ] **Step 2: Run;** expected FAIL.
- [ ] **Step 3: Implement** the functions; add the `config_defaults` key.
- [ ] **Step 4: Run;** expected pass; run the existing frontend/Python suites to confirm nothing else moved.
- [ ] **Step 5: Commit** `feat(approvals): availability, inbox and count endpoints`.

### Task 4: Detail, apply and bulk

**Files:**
- Modify: `vansale/steelforce/approvals.py`
- Test: `vansale/tests/test_approvals_api.py`

**Interfaces:**
- Consumes: Tasks 1-3.
- Produces:
  - `_actions_for(doc, user: str) -> tuple[list[dict], str | None]`: returns `(ActionSpec list, banner_kind)`. Uses PM `get_transitions(doc)`, then drops any transition for which PM's `has_approval_access(user, doc, transition)` is false (the submitter's own "Send for Approval" has `allow_self_approval`, so it stays); if that leaves nothing but transitions existed, banner is `"self_owned"`. If `get_open_return_adhoc_action(doc, state, user)` is set (a "return to me" recipient), returns every `PM Workflow Transition` of that workflow and state as specs with `recommend_only = True` and banner `"recommend"`. Each spec's `tone` comes from `tone_of`.
  - `@whitelist(GET) detail(doctype: str, name: str) -> Detail`. Without read permission: if the user holds an open PM action on it, return the minimal Detail with `banner = {"kind": "cannot_read"}` and no actions; otherwise raise `frappe.PermissionError`. `route` is derived from PM's `get_document_lifecycle` (read its return value at `permission_manager/api/approvals.py` and map `chain` to `done/current/todo` and `roles` to `who_can_act`). `comments` are the document's `Workflow` comments, HTML stripped. `can_forward` is true when the user holds an open action that is not itself ad-hoc-return.
  - `@whitelist(POST) apply(doctype: str, name: str, action: str, comment: str = "", priority: str = "Medium") -> {"ok": True, "new_state": str, "recommended": bool}`. Finds the spec for `action` in `_actions_for`; `check_apply` code maps to a translated `frappe.throw`; otherwise calls PM `apply_workflow(doc.as_dict(), action, comment or None, priority)`. Any PM or app exception propagates unchanged (sf_trading's message stays verbatim). Returns the new value of the workflow's state field.
  - `@whitelist(POST) apply_bulk(doctype: str, names: str, action: str, comment: str = "", priority: str = "Medium") -> BulkResult`. `names` is a JSON list; more than 20 throws; duplicates are dropped; each document goes through the same internal `_apply_one`, with `frappe.db.commit()` after a success and `frappe.db.rollback()` after a failure; `frappe.clear_messages()` between items; one failure never stops the batch.

- [ ] **Step 1: Failing tests** (patch `_pm`, `frappe.get_doc`, `frappe.has_permission`, `frappe.db`): a self-owned document whose only transition lacks `allow_self_approval` returns `actions == []` and `banner.kind == "self_owned"`; a "return to me" recipient gets `recommend_only` specs and `banner.kind == "recommend"`; `apply` with a return-for-correction action and an empty comment throws before `apply_workflow` is called (assert not called); `apply` with an action not in the document's specs throws; `apply` where `apply_workflow` raises `"Invalid Workflow Action"` re-raises that text and does not commit (Review Focus 1); `apply_bulk` with 3 names where the second raises a refusal returns `ok_count == 2`, `failed_count == 1`, the second result's `message` equals the refusal text verbatim, and rollback ran once and commit twice (Review Focus 5); `apply_bulk` with 21 names throws.
- [ ] **Step 2: Run;** expected FAIL.
- [ ] **Step 3: Implement.** Approach note: build `Detail.facts` and `lines` from `approvals_summary` using `frappe.get_meta(doctype).fields` and `get_cached_value("Company", company, "default_currency")` plus `get_currency_precision()` for precision; attachments from `File` rows attached to the document (`is_private` kept).
- [ ] **Step 4: Run;** expected pass.
- [ ] **Step 5: Commit** `feat(approvals): detail, apply and bulk endpoints`.

### Task 5: Forward, attach, my requests, sent back and history

**Files:**
- Modify: `vansale/steelforce/approvals.py`
- Test: `vansale/tests/test_approvals_api.py`

**Interfaces:**
- Produces:
  - `@whitelist(GET) forward_targets(doctype: str, name: str, query: str = "") -> list[{"user","full_name","role"}]`: enabled System Users whose name or full name matches `query` (max 20), kept only if `frappe.has_permission(doctype, "read", doc=name, user=candidate)`; excludes the caller.
  - `@whitelist(POST) forward(action_id: str, to_user: str, comment: str = "", return_to_originator: int = 0) -> {"adhoc_action": str, "return_to_originator": int}`: wraps PM `forward_workflow_action`.
  - `@whitelist(POST) return_to_originator(action_id: str, comment: str = "") -> dict`: wraps PM `return_adhoc_to_originator`.
  - `@whitelist(POST) attach(doctype: str, name: str, filename: str, content_base64: str) -> {"name","url"}`: first confirms the caller may act on the document (PM `_can_act_on` for an open action on it, or the caller is the document's owner with an open action); otherwise raises `frappe.PermissionError`. Only then stores a private File attached to the document, reusing the decoding and sanitising in `vansale/api/file_upload.py` (call into it; do not copy it).
  - `@whitelist(GET) my_requests() -> {"items": [{"doctype","docname","transaction","state","holder","role_id","days","priority"}]}`: open or forwarded `PM Workflow Action` rows with `for_submitter` = the session user, one row per document, Stock Entry and hidden workflow types excluded, newest wait first.
  - `@whitelist(GET) sent_back() -> {"items": [...]}` and `@whitelist(GET) history(limit: int = 100, from_date: str = "", to_date: str = "", transaction: str = "") -> {"items": [...]}`: thin wrappers returning PM's rows unchanged (`limit` coerced with `cint`, capped at 200).

- [ ] **Step 1: Failing tests:** `forward_targets` drops a candidate whose `has_permission` returns False and never returns more than 20; `attach` raises `PermissionError` for a caller with no open action and creates a file (mocked) for one with an action; `my_requests` over rows for one `Stock Entry` and two `Sales Invoice` actions on the same document returns one row (the invoice), excludes the Stock Entry; `forward` passes `return_to_originator` as an int to PM.
- [ ] **Step 2: Run;** expected FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run;** expected pass.
- [ ] **Step 5: Commit** `feat(approvals): forward, attach, my requests, sent back and history`.

### Task 6: Client API, pure logic and cache

**Files:**
- Create: `frontend/src/api/approvals.ts`, `frontend/src/features/approvals/{rules,format,filter,cache}.ts`
- Test: `frontend/src/features/approvals/__tests__/{rules,format,filter,cache}.test.ts`

**Interfaces:**
- Produces:
  - `api/approvals.ts`: the types from "Shared contracts" and one function per endpoint using `apiCall` (`availability, inbox, count, detail, apply, applyBulk, forwardTargets, forward, returnToOriginator, attach, myRequests, sentBack, history`).
  - `rules.ts`: `canConfirm(spec: ActionSpec, input: {comment: string; hasAttachment: boolean; addedAttachment: boolean}): {ok: boolean; missing: ("comment"|"attachment")[]}` (mirror of Task 1's rules) and `bulkShared(items: ApprovalItem[]): {actions: ActionFlag[]; reason: string | null}`: all items must share one `doctype`, otherwise `reason` is set; actions are those present in every item's `available_actions`, excluding any with `require_attachment`.
  - `format.ts`: `ageLabel(days: number): string` ("Today" for 0, "1 day", "N days"), `priorityTone(p: string): "critical"|"high"|"medium"|"low"`.
  - `filter.ts`: `filterItems(items: ApprovalItem[], q: {area: string; query: string}): ApprovalItem[]` (area `"All"` keeps everything; the query matches docname, party, transaction, creator, case-insensitive).
  - `cache.ts`: `saveInbox(user: string, inbox: Inbox): void`, `loadInbox(user: string): {inbox: Inbox; savedAt: string} | null`, `clearApprovalsCache(): void`, stored under `vansale.approvals.cache.v1`; every read and write wrapped in try/catch.

- [ ] **Step 1: Failing tests:** `canConfirm` for a reject spec with an empty comment returns `{ok:false, missing:["comment"]}`; with a `require_attachment` spec and neither `hasAttachment` nor `addedAttachment` returns `missing:["attachment"]`; `recommend_only` always `ok`. `bulkShared` over two items of different doctypes returns a `reason`; over two Journal Entries sharing `Approve` and `Reject` returns both; an action with `require_attachment` is dropped. `ageLabel(0) == "Today"`, `(1) == "1 day"`, `(7) == "7 days"`. `filterItems` by area and by a lower-case party fragment. Cache: `saveInbox("a@x", inbox)` then `loadInbox("b@x")` returns `null` (Review Focus 2); `loadInbox("a@x")` returns the inbox; after `clearApprovalsCache()` both return `null`; a corrupt stored string returns `null` without throwing.
- [ ] **Step 2: Run** `pnpm test -- approvals`; expected FAIL.
- [ ] **Step 3: Implement** the files.
- [ ] **Step 4: Run** `pnpm test -- approvals` and `pnpm type-check`; expected pass.
- [ ] **Step 5: Commit** `feat(approvals): client api, rules and cache`.

### Task 7: Store, session wiring and polling

**Files:**
- Create: `frontend/src/stores/approvals.ts`
- Modify: `frontend/src/stores/session.ts` (add `approvalsEnabled` getter from `defaults.approvals.enabled`; call `clearApprovalsCache()` inside `logout()`), `frontend/src/api/me.ts` (add `approvals?: {enabled: boolean}` to `ConfigDefaults`)
- Test: `frontend/src/stores/__tests__/approvals.test.ts`

**Interfaces:**
- Consumes: Task 6.
- Produces `useApprovalsStore()` with state `inbox: Inbox | null`, `mine: MyRequestRow[]`, `sentBack: SentBackRow[]`, `history: HistoryRow[]`, `loading: boolean`, `error: string | null`, `stale: boolean` (true when showing cache); getters `needsYou: number`, `badge: number`; actions `refresh(): Promise<void>`, `refreshCount(): Promise<void>`, `apply(doctype, name, action, comment, priority): Promise<void>`, `startPolling(): void` (every 60 000 ms plus on `visibilitychange` to visible and on `online`), `stopPolling(): void`, `reset(): void`. `refresh` loads the cache first for the current user, then the server; offline it keeps the cache and sets `stale`. `apply` on a rejected call refetches the inbox before rethrowing (Review Focus 1).

- [ ] **Step 1: Failing tests** (mock `@/api/approvals`): `refresh` online stores the inbox and writes the cache; `refresh` offline with a cache for the same user shows it with `stale === true` and makes no call; `apply` whose API rejects calls `inbox` once more and rethrows; `startPolling` twice creates one timer (fake timers, advance 60 s, expect one extra `inbox` call per interval); `reset` clears state and cache.
- [ ] **Step 2: Run;** expected FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `pnpm test` and `pnpm type-check`; expected pass.
- [ ] **Step 5: Commit** `feat(approvals): store with cache, polling and session wiring`.

### Task 8: Inbox screen, navigation and Home entry

**Files:**
- Create: `frontend/src/views/ApprovalsView.vue`, `frontend/src/components/ApprovalCard.vue`
- Modify: `frontend/src/app/router.ts` (routes `approvals` at `/approvals` and `approval-detail` at `/approvals/:doctype/:name`, both `requiresAuth` and `requiresPin`), `components/BottomNav.vue`, `components/TopAppBar.vue` (titles "Approvals", "Approval"), `views/DashboardView.vue` (a card with the `needsYou` count, shown when `approvalsEnabled`), `views/MoreView.vue` (an "Approvals" row), `locales/en.json` and `ar.json` (`approvals.*` keys)
- Test: `frontend/src/locales/__tests__/approvals-keys.test.ts`

**Interfaces:**
- Consumes: Tasks 6-7.
- Produces: `/approvals` renders the four tabs To approve, My requests, Sent back, History (the last three are placeholders until Task 10); To approve shows the stats line, area chips (All, Accounts, Purchase, Sales, Masters), the search box, **Needs you** sections by category in server order, then **Waiting on others**; cards show doctype label, docname, party, amount, age, priority bar, role chip, a "Forwarded by X" tag when `forwarded_by` is set. Navigation: for a user with `isVanUser`, the bottom nav is unchanged and the More icon shows a dot when `badge > 0`; for a user without a van setup the nav shows Approvals and More only, and no van endpoint is called for them (Home redirects to `/approvals`). Follow `frontend/DESIGN.md` and the existing tokens; priority colours as in `mockups/recommended-flow.html`.

- [ ] **Step 1: Failing test:** the set of keys under `approvals` in `en.json` equals the set in `ar.json` (Review Focus 4).
- [ ] **Step 2: Run;** expected FAIL.
- [ ] **Step 3: Implement** the view, card, routes, nav changes, Home card, More row and both locale files (Arabic strings written by hand, RTL-safe layout using logical CSS properties).
- [ ] **Step 4: Run** `pnpm test`, `pnpm type-check`, `pnpm build`; expected all green.
- [ ] **Step 5: Commit** `feat(approvals): inbox screen and navigation`.
- [ ] **Step 6: Checkpoint.** Ask the user for permission to deploy to sft-uat (Task 12 steps) so the inbox can be viewed on a real phone-width session before continuing. Do not deploy without an explicit yes.

### Task 9: Detail screen and action sheet

**Files:**
- Create: `frontend/src/views/ApprovalDetailView.vue`, `frontend/src/components/ApprovalActionSheet.vue`
- Modify: `locales/{en,ar}.json`

**Interfaces:**
- Consumes: Tasks 6-7 (`detail`, `apply`, `attach`, `canConfirm`).
- Produces: the detail screen with header, facts, first lines (with "N more" count), attachments, route chain with who can act, comment timeline, a sticky bar built from `Detail.actions` (Approve primary, Reject destructive, others secondary), a Forward button when `can_forward`, an "Open full document" link (`desk_url`), and the banners (`recommend`, `waiting`, `self_owned`, `cannot_read`) replacing the bar. The action sheet asks only for what `canConfirm` says is missing: a comment field (required marker and hint when needed), an attachment picker (camera or file; calls `attach`, base64 as `offline/photos.ts` does) and a priority selector defaulting to the spec's `priority`; Confirm is disabled until `ok`; a "needs a connection" line; while offline the bar is disabled with a message. After success the store refetches and the view returns to the inbox with a toast; on error the server message is shown as given and the detail reloads.

- [ ] **Step 1: Implement** both components and strings (en + ar); reuse `ConfirmModal`, `PhotoSlot`, `Toasts` where they fit.
- [ ] **Step 2: Run** `pnpm test`, `pnpm type-check`, `pnpm build`; expected green (the sheet's rule logic is already covered by Task 6's `canConfirm` tests).
- [ ] **Step 3: Commit** `feat(approvals): detail screen and action sheet`.

### Task 10: Forward, bulk selection, My requests, Sent back, History

**Files:**
- Create: `frontend/src/components/{ForwardSheet,BulkConfirmSheet}.vue`
- Modify: `ApprovalsView.vue` (selection mode and the three tabs), `ApprovalCard.vue`, `locales/{en,ar}.json`

**Interfaces:**
- Consumes: Tasks 6-7 (`forwardTargets`, `forward`, `returnToOriginator`, `applyBulk`, `bulkShared`, `myRequests`, `sentBack`, `history`).
- Produces: `ForwardSheet` (debounced user search via `forwardTargets`, note, the "return to me after their input" switch, Forward button; empty result explains that nobody who can read the document was found). Long-press (or a Select button) starts selection mode; only items whose `bulkShared` is non-empty may stay selected, others are greyed with the reason; the bottom bar offers the shared actions; tapping one opens `BulkConfirmSheet`, listing every selected document with party and amount and their total, asking for one shared comment when the action requires it, then calls `applyBulk` and shows per-document results (green/red) with a Retry for failures. My requests lists the rows (state, holder, days) and opens the read-only detail. Sent back shows the reason, who, and days; "Open and correct" routes to the app's own edit screen for Quotation, Sales Order and Sales Invoice and opens `desk_url` otherwise. History shows date-range and transaction filters.

- [ ] **Step 1: Implement** the components and tabs with strings in both locales.
- [ ] **Step 2: Run** `pnpm test`, `pnpm type-check`, `pnpm build`; expected green.
- [ ] **Step 3: Commit** `feat(approvals): forward, bulk, my requests, sent back and history`.

### Task 11: Parity report and docs

**Files:**
- Create: `vansale/steelforce/approvals_parity.py`
- Test: `vansale/tests/test_approvals_parity.py`
- Modify: `docs/reference/API.md` and related generated files (via the generator), `docs/SECURITY.md` only if the generator or the endpoint count text needs it

**Interfaces:**
- Produces `parity_report(user: str) -> dict` (not whitelisted; run with `bench --site <site> execute vansale.steelforce.approvals_parity.parity_report --kwargs "{'user': '<user>'}"`). It calls `frappe.set_user(user)`, then compares PM's `get_my_pending_approvals`, `get_sent_back_documents` and an independent query of open actions with `for_submitter = user` against `inbox()`, `sent_back()` and `my_requests()`, and returns `{"user", "desk_total", "pwa_total", "desk_waiting", "pwa_waiting", "needs_you", "sent_back_equal": bool, "my_requests_equal": bool, "ok": bool}`. Read-only.

- [ ] **Step 1: Failing test** with patched sources: equal inputs give `ok True`; a PWA total one lower gives `ok False` and the differing field is reported.
- [ ] **Step 2: Run;** expected FAIL. **Step 3: Implement.** **Step 4: Run;** expected pass.
- [ ] **Step 5: Regenerate docs:** `python3 scripts/gen-docs.py`; check the diff lists only the new endpoints.
- [ ] **Step 6: Commit** `feat(approvals): parity report and regenerated reference`.

### Task 12: UAT deploy and verification (needs the user's go-ahead for each write)

**Files:** none.

- [ ] **Step 1: Ask first.** Before anything that changes sft-uat (push the branch, pull on UAT, ship the SPA, restart), get an explicit yes from the user for that action. Reading is always fine.
- [ ] **Step 2: Deploy per `docs/OPERATIONS.md` §1-2.** The server code needs a web restart (see the memory notes on restarting; check the PID changed); no migrate is needed (no schema change); the SPA is not in git, so build it (`pnpm build`) and ship it as the operations doc describes.
- [ ] **Step 3: Non-van sign-in (the spec's first risk).** Ask the user to sign in on the browser pane as a real user with no Vansale Configuration. Expected: login succeeds, the shell shows Approvals and More only, no van error toast. If anything fails, fix the shell for such users (do not restrict v1 to van users).
- [ ] **Step 4: Parity.** `bench --site sft-uat.enfonoerp.com execute vansale.steelforce.approvals_parity.parity_report --kwargs "{'user': '<approver>'}"` for at least one approver and one submitter. Expected: `ok: true`.
- [ ] **Step 5: Walk the spec's verification list (section 8)** on the phone-width browser pane with clearly named test documents (ask before creating any): self-owned (no buttons), reject without comment (blocked), attachment-required (blocked until added), forward with and without return-to-me, ad-hoc recipient, a Customer approval, bulk of 3 with one refusal, offline read of the cached inbox, cache cleared on logout, English and Arabic.
- [ ] **Step 6: Report** the results to the user, then wait for their instruction on merging to `develop_2` and on any production step.

---

## Self-review (against the spec)

- **Coverage:** inbox with sections, stats, chips, search (T3, T8); detail, route, facts, lines, attachments, comments, real actions (T4, T9); action sheet with comment/attachment/priority (T1, T6, T9); forward, ad-hoc and "return to me" (T4, T5, T10); Waiting on others inside To approve and `total` parity (T3, T8, T11); My requests (T5, T10); Sent back and History (T5, T10); bulk with confirm sheet, cap 20, per-document results (T4, T6, T10); read-permission rule and forward target filter (T4, T5); masters (T4 uses the workflow's own state field via PM); hidden types (T5 and PM); offline read and no offline actions (T7, T9); cache hygiene (T6, T7); polling (T7); non-van shell and fallback (T8, T12); en/ar parity (T8); security and docs (global constraints, T11); parity verification (T11, T12). Colleagues, Analytics, Stock Entry and push are non-goals and have no task.
- **Type consistency:** `ActionFlag`, `ApprovalItem`, `ActionSpec`, `Detail`, `BulkResult` are defined once in "Shared contracts" and used under the same names in Tasks 3-10; `check_apply` codes (`not_allowed`, `comment_required`, `attachment_required`) are used identically in Tasks 1 and 4; `canConfirm` mirrors them in Task 6.
- **Risks carried to execution:** the `get_document_lifecycle` return shape must be read before mapping `route` (Task 4); attaching as an approver is limited to people who can act on the document (Task 5); the live non-van sign-in is untried until Task 12.
