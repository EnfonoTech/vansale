# PM approvals in the Van Sale PWA: design

Status: draft for approval · 2026-11-19 · app `vansale`, branch `develop_2` · first target: sft-uat

Mockups: `mockups/inbox-layouts.html` (the three inbox layouts compared) and `mockups/recommended-flow.html` (the six chosen screens). Both open in any browser.

## 1. Intent

Steel Force runs its approvals through the `permission_manager` (PM) engine: PM Workflows, PM Workflow Actions, and the desk page "My Approvals". Today an approver has to open the ERPNext desk to act. This design adds the same approvals to the Van Sale PWA, so any user can approve, reject, forward, and follow their own documents from a phone.

The scope is **every approval for every user**, not only sales documents. Two kinds of person use it:

- **Approvers** (managers, accountants, purchase and operations heads): clear their queue wherever they are.
- **Submitters** (salesmen, clerks): see where their document is stuck and why, and correct what was sent back.

The assumed reason (the user did not contradict it): approvers lose time waiting to reach a desktop, and submitters cannot tell why a document is stuck. Success is an approver clearing a queue from a phone using exactly the rules the desk applies, with the same counts the desk shows for the same user.

`STEELFORCE_DEVELOPMENT_PLAN.md` ("Approvals, ready for the other developer") already reserved `vansale.steelforce` for this work and set the rules this design follows: documents are created and acted on as the logged-in user, the app never submits a governed document directly, and the engine decides.

## 2. Goals, non-goals, anti-goals

**Goals**
- A native approvals area inside the PWA: inbox, document review, decide, forward, waiting, sent back, history.
- Behave exactly like PM: same eligibility, same actions, same required comment and attachment, same forwarding rules, same hidden document types.
- Fast for a large queue (a UAT approver can hold 60+ items, mostly Journal Entries).
- Safe: no approving blind, no way to act outside PM's rules.
- Works for users who are not van users (no van configuration).

**Non-goals (version 1)**
- The desk **Colleagues** and **Analytics** tabs (reporting, not decisions).
- Stock Entry approvals (PM keeps them in the Warehouse Dashboard by ops request).
- Approving offline. The server decides, so every action needs a connection.
- True phone push notifications.
- Editing governed documents the PWA has no form for (Journal Entry and others). Those open the full desk form.
- Changing PM workflows or any PM behaviour.

**Anti-goals** (failure even if it technically works)
- Re-implementing a PM or sf_trading rule in vansale. We ask PM; we never copy its logic.
- An inbox whose counts or items disagree with the desk for the same user.
- A one-tap approve that skips a look at the document. Every approve goes through the detail screen or, in bulk, a confirm sheet that lists each document with its party and amount.
- Acting as Administrator on someone's behalf.

## 3. Constraints and facts (read from sft-uat on 2026-11-18/19, permission_manager `4b006f3`, vansale `develop_2` `d23521e`, sf_trading 0.1.168)

The engine already provides what the PWA needs, so the backend is thin wrappers:

| Need | PM function (all `@frappe.whitelist`) |
|---|---|
| Inbox | `api.approvals.get_my_pending_approvals` → `{total, groups:[{label, items}]}`. Item fields: name, doctype, transaction, docname, date, priority, state, role_id, holder, days, creator, category, available_actions, is_adhoc, is_waiting, waiting_with, return_to_originator |
| Real actions for one document | `workflow.get_transitions(doc)`: per-document, per-user, honours conditions and self-approval |
| Apply an action | `workflow.apply_workflow(doc, action, comment, priority)` (wrapped by `api.approvals.quick_apply_workflow_action`) |
| Route and who can act | `api.approvals.get_document_lifecycle(doctype, docname)` |
| Forward / return | `doctype.pm_workflow_action.pm_workflow_action.forward_workflow_action`, `return_adhoc_to_originator` |
| Sent back | `api.approvals.get_sent_back_documents` (includes sent_back_by, reason, days) |
| History | `api.approvals.get_my_approval_history` |
| Bulk | `workflow.bulk_workflow_approval` (see rule 8 below) |

Rules enforced by the engine (these define "exactly like PM"):

1. **Self-approval:** the owner of a document cannot act on it unless the transition has `allow_self_approval` (Administrator always can).
2. **Return for correction** (`is_return_for_correction`): a comment is always required (server). A submitted document goes back to draft and the submitter gets a Notification Log.
3. **Attachment:** `require_attachment` is enforced on the server by checking that the document has at least one File.
4. **`require_comment` is NOT enforced on the server.** Only the desk dialog enforces it. Our wrappers must enforce it for the PWA path.
5. **Priority** (Low, Medium, High, Critical) is stamped on the action; each transition has a default.
6. **Forward (ad-hoc):** the forwarder's action becomes `Forwarded`; the target gets an ad-hoc action. If "return to me after their input" is ticked, anything the target chooses goes back to the forwarder and the document does **not** advance (PM shows that message). A forwarded item stays visible to the forwarder and the role, as "waiting", with no buttons.
7. **Hidden:** Stock Entry, and any workflow flagged `hide_from_approval_inbox`, never appear in the inbox or sent-back list.
8. **Bulk:** the engine applies one action to many documents with **no comment or priority**. Under 20 documents it runs in the request; 20 to 500 it is queued and the result is only a desk message; over 500 it refuses. A bulk reject of a return-for-correction action therefore fails per document unless a comment is supplied.
9. **Categories** (Approval / Decision / Acknowledgement pending) are decided by keyword matching on state and action names. The desk groups by these, not by document type.
10. The desk inbox draws its buttons from a **static list per workflow state**, not from the document's real transitions, so it can show an action that then fails with "Invalid Workflow Action".
11. Documents are acted on **as the session user** and the document's own hooks run, so sf_trading and other app checks can refuse an action. Their message must reach the approver unchanged.
12. The desk shows forwarded items inside the pending list. There is no separate "Waiting" tab in the desk.
13. **Ad-hoc (forwarded) recipients.** If the forward was made **without** "return to me", the recipient may perform any transition of that state (role check bypassed), so `get_transitions` returns them all. If it was made **with** "return to me", `get_transitions` returns an empty list, and `apply_workflow` intercepts whatever label is sent (it must still be a real transition label of the state), records it as a recommendation and sends the document back to the forwarder without advancing it.
14. **Read permission.** `get_transitions` calls `check_permission("read")` on the document, and so do `get_document_lifecycle` and the desk preview. An approver or forward recipient who cannot read the document cannot act on it in the desk either. Forwarding does not share the document with the recipient (no `frappe.share` call).
15. **Masters.** `get_transitions`, `apply_workflow` and `get_document_lifecycle` use each workflow's own state field (`workflow_state_field`), so Customer, Supplier and Item (`custom_approval_status`) and SF Master Change Request (`status`) work like the rest. Only the sent-back list needs a `workflow_state` field.

Live on sft-uat: 21 active PM workflows (Customer, Supplier, Item, Journal Entry (two), Payment Advice (two), Payment Request (two), Purchase Invoice (two), Purchase Order (two), Quotation cancellation, Sales Order cancellation, Sales Invoice return (two), SF Master Change Request, Stock Entry (two, hidden), Stock Reconciliation). Open actions today include Journal Entry 60, Stock Entry 23, Sales Invoice 13, Purchase Invoice 13, Payment Entry 9, Purchase Order 8.

Vansale facts that shape the work:
- Login is not role-gated: `vansale.api.auth.login` accepts any enabled user, `is_van_user` is only a flag returned by `config_defaults`, which treats "no van configuration" as empty values rather than failing, and the Home van chip is conditional. So a user with **no Vansale Configuration** should sign in and load. This is from reading code; it has **not been tried live** (it needs a real non-van user), and doing so is the first build task.
- The bottom nav has five fixed slots and the code says there is no room for a sixth.
- Existing patterns to follow: thin domain wrappers in `frontend/src/api/`, `vansale.api.*` and `vansale.steelforce.*` for server code, `docs/SECURITY.md` §2 for every new endpoint, tokens in `frontend/src/styles/tokens.css` and `frontend/DESIGN.md`.

## 4. Approaches considered

| | Approach | Why / why not |
|---|---|---|
| **A (chosen)** | Native approval screens inside the vansale SPA over thin wrappers; the server builds a short summary of each document | Best phone experience, one login and PIN, same look. Costs the most to build; summaries need per-type templates with a generic fallback |
| B | Open the desk form in the PWA | Least work, but the desk is poor on a phone, needs its own login, looks foreign |
| C | A separate approvals PWA | Duplicates login, PIN, offline handling and the build pipeline |

Inbox layout (all drawn in the mockups): **B (chosen)** one list, urgency first, with PM's three categories as section headers and filter chips. Rejected: A (group by document type; PM does not group that way, and it hides urgent items of small types) and C (one card at a time; no overview, no bulk, no easy lookup). C survives as an optional "Review next" step inside the detail screen, not as the inbox.

## 5. The design

### 5.1 Navigation and who sees what

- A new **Approvals** area, available whenever `permission_manager` is installed on the site and the PM tables exist. Every user can open it: approvers for the queue, submitters for Waiting, Sent back and History.
- **Van users** keep the current five-slot bottom nav. Approvals is reached from a **Home card with a pending count** and from **More**; the More icon shows a dot when something is pending. *(My call.)*
- **Users with no van setup** get an approvals-first shell: the nav shows Approvals and More only, with the van tabs hidden, and the app never calls a van endpoint for them (Home included). *(My call.)* If the live sign-in check fails, the fix is made in `config_defaults` / the shell for these users (a small change in existing code); v1 is **not** limited to van users.
- Routes: `/approvals` (inbox), `/approvals/:doctype/:name` (detail). All require auth and PIN like the other screens.

### 5.2 Screens (see `mockups/recommended-flow.html`)

1. **Inbox.** Tabs: **To approve, My requests, Sent back, History.** To approve has two parts: **Needs you** (actionable items) and, below it, **Waiting on others** (items I forwarded, or that another approver holds; no buttons). Together they equal the desk's total, so the counts match. Filter chips by area (Accounts, Purchase, Sales, Masters) built from `transaction`. A stats line: high-priority count and items over 30 days (the desk's two stats). Inside Needs you, items are in PM's sections (Approval, Decision, Acknowledgement pending), urgency first (priority, then days). A card shows document type, document name, party, amount, days waiting, priority colour bar and the role it waits on. Pull to refresh. Long-press starts selection (see Bulk). Returns are labelled as PM labels them (`transaction`).
2. **Detail (review).** Header with amount and state; key facts; the first lines of the document; attachments; the **route** (from `get_document_lifecycle`: where it is, who else can act now); a short timeline of workflow comments. A sticky bar shows the document's **real** actions from `get_transitions`, with Approve as the primary and Reject styled as destructive. An action named for returning shows as Reject. If the user cannot act (waiting, self-owned, no permission) the bar is replaced by a one-line reason. An "Open full document" link goes to the desk form.
3. **Action sheet.** Asks only what PM requires for that action: a comment (required when the transition is return-for-correction or has `require_comment`), an attachment (camera or file, required when `require_attachment` and the document has none), and a priority (default from the transition). Confirm stays disabled until satisfied. A line says it needs a connection.
4. **Forward sheet.** Search enabled system users, optional note, "return to me after their input" switch. After forwarding, the item moves to Waiting showing who holds it.
5. **Ad-hoc recipient.** An item forwarded to me shows a "Forwarded by X" tag in Needs you.
   - Forwarded **without** return-to-me: I get the document's real transitions (rule 13) and act normally.
   - Forwarded **with** return-to-me: `get_transitions` is empty (rule 13), so the detail lists the state's own transition labels as **recommendations** ("Recommend approve", "Recommend reject") with a banner: "Your answer goes back to X; the document will not advance." Tapping one calls `apply`, which PM intercepts. A comment is encouraged but PM does not require one here.
6. **My requests.** For submitters: the documents I raised that are still in approval, with the current state, who holds it (a person, or the role), and days waiting. Source: open or forwarded PM Workflow Actions whose `for_submitter` is me, one row per document, excluding Stock Entry and hidden workflow types. Tapping a row opens the detail in read-only form (route, comments, no action bar). This is how a salesman sees that his invoice is with the Finance Head.
7. **Sent back.** For submitters: the approver's reason, who, and how long ago, from `get_sent_back_documents`. "Open and correct" opens the app's own edit form for Quotation, Sales Order and Sales Invoice; every other type opens the full desk form.
8. **History.** My completed approvals and outcomes on documents I submitted, with a date range and transaction filter, from `get_my_approval_history`.
9. **Bulk.** Long-press selects. Only items of the same document type with the same action can join; others are greyed with the reason. The bar offers the shared actions. Tapping one never applies it directly: a **confirm sheet** lists every selected document with its party and amount (and the total), and applying needs a second tap. Reject needs one shared comment; an attachment-required action is not offered in bulk. Each document is applied one by one and the result of each is shown, so one refusal does not hide the rest. Maximum 20 per batch (below the engine's queued threshold, so results are always visible).

### 5.3 Server: new module `vansale/steelforce/approvals.py` (Steel Force code lives in `vansale/steelforce/`, per the plan)

Everything degrades to "nothing here" when `permission_manager` is not installed. No new DocTypes, patches or hooks. All endpoints are whitelisted with explicit methods, typed arguments, and listed under `docs/SECURITY.md` §2 and `docs/reference/API.md` (regenerate with `scripts/gen-docs.py`).

| Endpoint | Does |
|---|---|
| `availability()` | `{enabled}`; also returned inside `config_defaults` so the nav can decide without a call |
| `inbox()` | Wraps `get_my_pending_approvals`; returns the Needs you items and the `is_waiting` items (Waiting on others) together; adds party and amount to each item by one bulk query per document type |
| `count()` | Cheap `{total, needs_you, waiting, high, overdue}`. `total` equals the desk's `get_my_pending_approvals` total; `needs_you = total - waiting` is what badges and the Home card show |
| `my_requests()` | Open or forwarded PM Workflow Actions with `for_submitter` = me, one row per document (state, who holds it, days); Stock Entry and hidden types excluded |
| `detail(doctype, name)` | Checks read permission (the same rule PM applies, fact 14); returns header, key facts, first lines, attachments, workflow comments, route, and the actions: the **real transitions** from `get_transitions` with their flags (`require_comment`, `require_attachment`, `is_return_for_correction`, `priority`, `next_state`) and a tone (approve, reject, other). For a "return to me" recipient (fact 13) it returns the state's transition labels instead, flagged `recommend_only`. A user who holds an action but cannot read the document gets a clear "you hold this approval but cannot open the document" state and no actions |
| `apply(doctype, name, action, comment, priority)` | The action must be in the document's own `get_transitions`, or, for a "return to me" recipient, a real transition label of the state. Enforces `require_comment` (fact 4) and the return-for-correction comment before calling PM; then calls `apply_workflow`. Returns the new state or the server's message verbatim |
| `apply_bulk(doctype, names, action, comment, priority)` | Up to 20, one by one, per-document results; commits each |
| `forward_targets(doctype, name, query)` | Enabled system users matching the search, **only those who can read that document** (fact 14: forwarding does not share it, and a recipient who cannot read it is stuck). Capped at 20 results. This is stricter than the desk, which lists everyone |
| `forward(action_name, to_user, comment, return_to_originator)` | Wraps `forward_workflow_action` |
| `return_to_originator(action_name, comment)` | Wraps `return_adhoc_to_originator` |
| `attach(doctype, name)` | Attaches an uploaded file to the document **only if the caller holds an open action or allowed transition on it** (see §7) |
| `sent_back()`, `history(...)` | Thin wrappers over PM |

Key facts and lines are built by a **field map per document type**, with a generic fallback that mirrors the desk preview (preview-marked, bold, then list-view fields; skip technical fields; first 8). Templates for the types with real volume or real risk: Journal Entry (accounts, debit, credit), Purchase Invoice and Purchase Order (supplier, items, taxes), Payment Entry / Payment Request / Payment Advice (party, amount, mode, reference), Customer and Supplier (credit limit, VAT, CR, approval state), Sales Invoice return (original invoice, reason), SF Master Change Request (changed fields, before and after), Quotation / Sales Order cancellation (reason). Amounts use the company currency and its precision (BHD 3 decimals).

### 5.4 Client

- `frontend/src/api/approvals.ts`, `frontend/src/stores/approvals.ts`, views `ApprovalsView.vue` and `ApprovalDetailView.vue`, components `ApprovalActionSheet.vue` and `ForwardSheet.vue`, route entries, English and Arabic strings (the app is bilingual and RTL).
- **Refresh:** on app resume, on pull-to-refresh, and every 60 seconds while the Approvals screen is open; a badge refresh via `count()` elsewhere. No socket client in v1 (the desk's live event `pm_new_approval_action` is a later improvement).
- **Offline:** the last inbox is cached read-only with a "last updated" stamp; all actions are disabled with a clear message. Approvals never enter the offline queue. The cache is cleared on logout and on a change of user.
- **Errors:** a server refusal (sf_trading, PM, "Invalid Workflow Action", state changed) is shown as given, then the item is refetched so the screen shows the new truth.
- Follow `frontend/DESIGN.md` and existing tokens; priority colours: Critical dark red, High red, Medium amber, Low green, as in the mockup.

## 6. Calls I made (not decided by the user; please check)

1. Approvals reached by a Home card and More for van users; approvals-first nav for non-van users.
2. **Waiting on others** is a section inside To approve, as in the desk, so the totals match. The fourth tab is **My requests** (what I raised and where it is stuck), which the reviewer showed was missing. This changes the tabs in the mockup you saw (it showed a Waiting tab).
3. Bulk capped at 20 per batch, run in the request, per-document results. Bulk approve goes through a confirm sheet that lists each document, party and amount.
4. Our `apply` enforces `require_comment` even though PM does not. (A PM-side fix is a sensible follow-up, outside this work.)
5. Polling every 60 s on screen instead of live sockets in v1.
6. New module `vansale/steelforce/approvals.py` (as the plan reserved) rather than a generic `vansale/api` module.
7. The first build task is trying a real non-van user on UAT. The code says it works; if it does not, the shell for those users is fixed (not "van users only").
8. Sent-back correction opens the desk form for every type except Quotation, Sales Order and Sales Invoice.
9. The forward picker lists only users who can read the document (stricter than the desk).
10. "Needs you" is the badge number: `total - waiting`. The parity test compares both the total and that number with the desk.
11. For a "return to me" forward, the recipient sees recommendation buttons built from the state's transition labels.

## 7. Left to the builder

- **Attaching a file as an approver.** The approver may lack write permission on the document. `attach` must attach on their behalf after confirming they hold an open action or an allowed transition, and must not become a general "attach to anything" endpoint. Check how Frappe's upload handler treats permission before choosing between reusing `vansale/api/file_upload.py` and a new path.
- **Sent back for masters.** `get_sent_back_documents` only covers documents with a `workflow_state` field; Customer, Supplier and Item use `custom_approval_status`, so they will not appear under Sent back. Decide whether to fill that gap or accept it in v1.
- Exact summary field maps, the filter-chip groupings, card density, empty and error states, and pull-to-refresh behaviour.
- Whether `availability` rides inside `config_defaults` or is a separate call.
- Test seeding: use UAT only, mark every test document clearly, and ask before writing anything. Real approver accounts must be signed in by the user; Administrator holds every role and would see everything.

## 8. Verification

- **Parity:** for the same user, the PWA To approve total (Needs you plus Waiting on others) and its item list equal the desk "My Approvals" (`get_my_pending_approvals`), and Needs you equals total minus waiting; Sent back equals `get_sent_back_documents`; My requests equals the open or forwarded actions with `for_submitter` = that user.
- **Action parity:** acting from the PWA leaves the same PM Workflow Action state, workflow comment and notifications as acting from the desk.
- **Rules:** self-owned document (no buttons), return-for-correction without a comment (refused), attachment-required without a file (refused), `require_comment` (refused by our wrapper), forward with and without return-to-me, ad-hoc recipient response (real actions without return-to-me, recommendations with it), a forward target who cannot read the document (not offered), a user who holds an action but cannot read the document (clear dead end), waiting row, a master (Customer) approval, hidden Stock Entry, an sf_trading refusal shown verbatim, state changed under the approver.
- **Bulk:** mixed outcomes show per-document results; the 20 cap holds.
- **Frappe tests** for the wrappers (`FrappeTestCase`); **vitest** for the store and helpers; the plan's style of live test checklist on sft-uat.
- **Phone:** 360 px width, English and Arabic (RTL), offline read of the cached inbox, action disabled offline, cache cleared on logout.
- Rollout: `develop_2` only, sft-uat first, production only when asked. The whole feature is inert on sites without `permission_manager`.
