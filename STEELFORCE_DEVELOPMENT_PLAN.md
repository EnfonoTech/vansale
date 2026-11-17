# Van Sale — Development Plan (Steel Force, branch `develop_2`)

App: **`apps/vansale`**, branch **`develop_2`**. Dev site: **steelforce.local** (copy of Steel Force data,
sf_trading on branch `new`, 0.1.159). Runs **next to `sf_trading`** (Steel Force's ERPNext app) and
**`permission_manager`** (their approval engine).

## Branches

| Branch | What it is |
|---|---|
| `develop` | The standard app, production-ready, in use by other clients. **No development here for now.** |
| `develop_2` | **All Steel Force development happens here**, including standard fixes found on the way. |

- Every change is tagged **[STD]** (right for every client) or **[SF]** (Steel Force / sf_trading only).
- When the Steel Force work is complete, the **[STD]** changes are moved to `develop` in one go.
  **[SF]** changes stay on `develop_2`. All [SF] code lives in `vansale/steelforce/`, which makes the split easy.
- **No sf_trading code is copied into vansale.** sf_trading stays installed and owns Steel Force's business
  rules. vansale calls its functions and lets its server checks run on every document the app creates.
- History: the first `develop_2` copied a partial, old sf_trading into vansale. That was reverted
  (`4b4fd74`); the branch is `develop` + the Lead → Quotation → Sales Order cycle + this plan's work.

## Ground rules

1. **Business rules stay in sf_trading / permission_manager.** The app never re-implements a rule. It
   (a) fills what the rule needs, (b) asks the server before the salesman submits, using sf_trading's own check
   endpoints, and (c) shows the server's message clearly when a rule refuses.
2. **Settings, not hard-coding**, wherever Steel Force may want it either way. A setting's default keeps the
   old behaviour. The override chain is the same as for Badria: Vansale Settings (global) → Vansale
   Configuration (van, "Follow Global").
3. **Documents are created under the salesman's own login**, never Administrator. sf_trading skips many rules
   for Administrator, and permission_manager treats the owner as the submitter.
4. Each phase ends with a test checklist on steelforce.local. I rebuild and clear the cache; you hard-refresh
   (Ctrl+Shift+R).
5. **Approvals are not ours.** Another developer builds the management approval part on top of this app. Our job
   is to leave everything ready for it (see "Approvals — ready for the other developer").

## Decisions (from you, 17 Nov 2026)

| # | Question | Answer → design |
|---|---|---|
| 1 | Do salesmen carry stock? | Normally **no** → *order taker*: the invoice moves no stock; delivery is from the branch. A setting allows van sales too |
| 2 | Quotation → Invoice or → Sales Order? | **Setting** "Quotation becomes": Sales Order / Sales Invoice / Both |
| 3 | Who collects cash? | Unclear → **setting** "Cash sale collection": Collect now / Collect later / Salesman chooses |
| 4 | Credit customers from the field? | **Both may come** → cash customers now; "Request credit" later, behind a setting |
| 5 | Back-dated entries? | Normally none → no work now; noted under risks |
| 6 | Approvals in the app? | **Not our development** → keep the app ready for it |

## Settings (what exists now)

| Setting | Where | Options (default first) | Steel Force |
|---|---|---|---|
| Invoice updates stock (sale from the van) | Vansale Settings + van "Invoice updates stock" | on / off | **off** (order taker) |
| Quotation becomes | Vansale Settings | Sales Order / Sales Invoice / Both | **Sales Invoice** or Both |
| Cash sale collection | Vansale Settings + van | Collect now / Collect later / Salesman chooses | your call (3) |
| CR number field | Vansale Settings → Customer | blank = `custom_cr_number` | `custom_commercial_registration_number` |
| Cash sale posting (existing) | Vansale Settings + van | POS Invoice / Payment Entry | **Payment Entry** (Steel Force doesn't use POS invoices) |
| Default customer group / territory (existing) | van | — | Commercial / Saudi Arabia (leaf values) |

## How Steel Force sells (dev site + sf_trading `new` 0.1.159)

- **Company** "Steel force" (Saudi Arabia, SAR), so sf_trading's Saudi master rules apply: VAT 15 digits
  3…3, phones ≥ 10 digits, B2B address complete, unique VAT / CR.
- **Branch is the centre.** *Branch Configuration* holds each branch's users, warehouses, cost centers, payment
  modes (Cash / Bank Draft / Cheque-PDC), price lists and letter head, and writes the users' User Permissions.
  **Quotation and Sales Order can't be saved without a branch** (new in 0.1.120).
- **Flow: direct Sales Invoice**, mostly without stock update. Quotations go straight to an invoice
  (sf_trading's mapping).
- **Payment mode on the invoice** (`custom_payment_mode` Cash / Credit / Cheque), not POS. A Cash invoice is due the
  same day, and the money is collected afterwards (Payment Entry), often by the driver.
- **Sales person mandatory** on invoice and order (`custom_sales_person`). Its *type* (Branch / Outdoor) separates
  outdoor sales in targets and bonus.
- **Customers.** sf_trading title-cases the name, and that changes the ID. `custom_company` decides who sees the
  customer, and a contact phone is needed to bill.
  - **B2B** (VAT number): needs a CR number and an attachment. A B2B approval route exists behind the switch
    "B2B Customer Approval".
  - **Credit customers**: need Branch Access, payment terms, 2 phones, email and a document, plus **Customer
    Approval**. A credit customer is moved to the "Credit Customer" group (0.1.159).
  - **Changes to an approved credit / B2B customer are themselves held for approval** (0.1.131). Edits from the
    app (address, contact) can therefore wait for an approver.
- **Prices:** rate priority is offer price, else standard price, else cost + Item Group margin (ENFA-207). Only an
  offer price may go below the standard price. A rate below the minimum is refused, even on a draft quotation.
- **Credit:** a new credit sale is refused while an older credit invoice is overdue. There is a company limit
  and per-branch sub-limits, and a cheque counts as credit.
- **Returns:** the *Sales Return Reason* list is mandatory, plus text for "Other". Only one draft return per
  invoice. Return window and amount approval exist (on in production per the code).
- **Collections** must reference an invoice or order. The salesman sees only his branch's payment modes.
- **Cancelling** a submitted order or quotation: Sales Manager or Sales Support; others send a request.
- **Draft sales can't be printed** (draft returns can).

## Phase 1 — done 17 Nov 2026 (uncommitted on `develop_2`)

| Tag | Change |
|---|---|
| [STD] | **Price list** on every document the app creates (van's, else Selling Settings). Before this, nothing could be saved on a site without a Selling Settings default |
| [STD] | **Branch** on every document from the van (else the user's Branch permission). Steel Force requires it on Quotation / Sales Order |
| [STD] | **Mandatory sales person** field (`custom_sales_person`) filled from the salesman where the site has it |
| [STD] | **Van first:** warehouse, cost center, branch and company come from the van (Vansale Configuration) before the user's default permission. sf_trading's Branch Configuration resets permission defaults, which used to move the van |
| [STD] | Settings: *Invoice updates stock*, *Quotation becomes*, *Cash sale collection*, *CR number field* (table above) |
| [STD] | **Quotation → Invoice** (`quotation.make_invoice`): app button by setting; a lead's quotation converts the lead |
| [STD] | Lead quotation: the lead stays a lead until the quotation becomes an order or invoice; conversion uses the van's customer group / territory |
| [STD] | Bug fix: editing a draft invoice made from an order / quotation dropped the link → the order stayed unbilled, the quotation stayed Open. Links are kept now |
| [STD] | Returns carry the original's branch / cost center |
| [SF] | `custom_payment_mode` Cash / Credit sent on every invoice. It used to default to Cash, so a credit sale was booked as Cash |
| [SF] | `custom_company` on new customers (else branch users can't see them) |
| [SF] | Return reasons from sf_trading's *Sales Return Reason* list → template + text; returns keep the original's sales person and payment mode |
| [SF] | Quotation → Invoice uses sf_trading's own mapping for customer quotations (status, duplicate check); a lead's quotation gets the same row link |
| [SF] | Print hidden on draft sales (sf_trading refuses it) |

**Tested** on steelforce.local over HTTP as the salesman:
- Customer (B2C, and VAT + CR).
- Lead → quotation → invoice (cash, collect later).
- Lead → quotation → order → invoice (credit).
- Customer quotation → invoice: quotation becomes *Ordered*, a second invoice is refused.
- Order → invoice edited in the form: order 100% billed.
- Direct cash and credit invoices.
- Collection.
- Returns ("Damaged", "Other" + text).
- Order-taker mode: no stock moved, full catalog.

Every check passed. Frontend type-check and unit tests pass.

## Phase 2 — next (`develop_2`)

| Tag | Item | Design |
|---|---|---|
| [SF] | **Minimum price** in the app | Catalog and line editor show the floor price from sf_trading `get_min_selling_price` (branch-aware). The app refuses a lower rate before save |
| [SF] | **Pre-check before submit** | One endpoint that runs sf_trading's own checks: `party_alert.get_party_alert`, `get_customer_selling_context` / `check_customer_credit_overdue`, `master_approval.get_approval_state`, min prices. The invoice / order screen lists every problem before *Submit* |
| [SF] | **Credit only for credit customers** | The desk blocks a credit sale to a customer without a credit limit in JS only, so the app must enforce it too. Setting to allow / block |
| [SF] | **Cheque (PDC)** | Payment type Cheque → cheque no + date → sf_trading PDC fields; only where the branch has PDC modes |
| [SF] | **Collection the sf_trading way** | Cash collected now → sf_trading's `create_pos_payments_for_invoice` (one entry per mode, PDC, loyalty write-off), so entries match the desk |
| [SF] | **Payment modes** | List = the branch's modes (`get_payment_modes_with_account`) |
| [SF] | **Driver** | Optional "Delivery person" on cash invoices (drivers serving the branch); setting to show it |
| [SF] | **Cancellation request** | On a submitted order / quotation → `order_cancellation.request_cancellation` with a reason |
| [SF] | **Customer form rules** | B2C = name + mobile; B2B = + VAT, CR, document photo; Saudi formats checked before sending; title-cased ID read back |
| [SF] | **Request credit** (setting "Allow credit request") | Limit, payment terms, email, 2nd phone, documents from the camera, Branch Access = salesman's branch → saved for **Customer Approval** (approval itself = other developer). Until approved: cash only, badge "Credit pending" |
| [SF] | Customer status in the app | Cash only · credit pending · credit approved (limit, used, overdue) · change waiting for approval |

## Approvals — ready for the other developer

We don't build approval screens. We make sure:

- Documents are created as the salesman (owner = submitter).
- The app **never submits a governed document directly**. A document under approval is saved and its state
  shown; submitting is the approval engine's job.
- The app shows a document's approval state and the server's reason when something waits. The state field is
  `custom_approval_status` for customers, `workflow_state` otherwise.
- `vansale.steelforce` is where the approval calls will go: `get_approval_state`, `get_transitions`,
  `quick_apply_workflow_action`, `get_my_pending_approvals`. The other developer can add them there.

## Risks / notes

- **`custom_return_reason` clash:** vansale ships it as a Select field, while Steel Force's site has an older Data
  field with the same name. Today the site's field stays; if vansale's ever overwrites it, sf_trading's "Other +
  text" breaks. Check after each migrate:
  `select fieldtype from tabCustom Field where name='Sales Invoice-custom_return_reason'` → **Data**.
- **Back-dating:** permission_manager can refuse back-dated documents (off today). If production turns it on, an
  invoice saved offline and synced the next day would be refused.
- **Credit and approval rules can't be checked offline**, so credit sales need a connection; cash sales work
  offline.
- **badria.local** runs `develop_2` too while it is checked out. All new settings default to the old behaviour,
  but the Lead / Quotation / Order screens show there.

## Setup checklist per Steel Force salesman

1. **Sales Person** for the salesman: type **Outdoor**, enabled, leaf.
2. **Vansale Configuration:**
   - company and **branch**;
   - user (Van User + sales person);
   - warehouse (order taker: the branch warehouse; van: his own warehouse);
   - cost center and selling price list;
   - default customer group (leaf) and territory;
   - *Invoice updates stock* (Disabled for order takers) and *Cash sale collection*.
3. **Van mode only:** add the van warehouse to the branch's Branch Configuration.
4. Items need an Item Default for the company; sf_trading hides other items from branch users.

## Test site state (steelforce.local)

- Test van **DMM1**: user `van.dmm1@steelforce.local` / `VanTest#2026`, branch Dammam, warehouse *Van DMM1 - SF*,
  *Invoice updates stock* = Disabled.
- Global settings: Quotation becomes = Both; Cash sale collection = Salesman chooses; CR number field =
  `custom_commercial_registration_number`.
