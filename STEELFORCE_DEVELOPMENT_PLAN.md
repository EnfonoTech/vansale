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
  The list to move is kept in `STANDARD_FIXES_FOR_DEVELOP.md` (`develop` has no Lead / Quotation /
  Sales Order, so that selling flow stays here).
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
| 3 | Who collects cash? | **A cash sale is paid on the spot.** Only a sale handed to a delivery person asks "collect on delivery / paid now" (on delivery by default), as sf_trading's desk form. The earlier "Cash sale collection" setting was removed (17 Nov) |
| 4 | Credit customers from the field? | **Both may come** → cash customers now; "Request credit" later, behind a setting |
| 5 | Back-dated entries? | Normally none → no work now; noted under risks |
| 6 | Approvals in the app? | **Not our development** → keep the app ready for it |

## Settings (what exists now)

| Setting | Where | Options (default first) | Steel Force |
|---|---|---|---|
| Invoice updates stock (sale from the van) | Vansale Settings + van "Invoice updates stock" | on / off | **off** (order taker) |
| Quotation becomes | Vansale Settings | Sales Order / Sales Invoice / Both | **Sales Invoice** or Both |
| CR number field | Vansale Settings → Customer | blank = `custom_cr_number` | `custom_commercial_registration_number` |
| Cash sale posting (existing) | Vansale Settings + van | POS Invoice / Payment Entry | **Payment Entry** (Steel Force doesn't use POS invoices) |
| Credit sale only for customers with a credit limit | Vansale Settings | off / on | **on** |
| Ask for the delivery person on cash sales | Vansale Settings | off / on | your call |
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

## Phase 2 — done 17 Nov 2026 (uncommitted on `develop_2`)

| Tag | Change |
|---|---|
| [SF] | **Minimum price in the app:** each line shows sf_trading's minimum for its UOM (`get_min_selling_price`, branch-aware). A lower rate shows red, and the app won't save it (invoice, quotation, order) |
| [STD]+[SF] | **Pre-check before submit** (`vansale.api.precheck.check`), online only. Lists every problem in one dialog before *Submit*: sf_trading's customer gates (phone, credit documents, approval), an overdue credit invoice, rates below the minimum, and the credit-limit setting. Runs on new invoices, drafts submitted from the detail screen, and orders |
| [STD] | Setting **Credit sale only for customers with a credit limit** (ERPNext treats no limit as unlimited; the Steel Force desk blocks it in JS only). Checked in the pre-check and again on save |
| [SF] | **Cheque (PDC) sales:** payment type *Cheque*, shown where the branch has cheque modes, with number and date. The invoice is booked as Cheque and the cheque is collected through sf_trading's own function (PDC fields) |
| [SF] | **Collection the desk way:** a cash sale collected now (posting = Payment Entry, status Submit) goes through sf_trading's `create_pos_payments_for_invoice`. The response now returns the paid status |
| [SF] | **Payment modes = the branch's** (sf_trading's Branch Configuration); cheque modes are listed apart |
| [SF] | **Delivery person** on cash sales (setting *Ask for the delivery person on cash sales*); the list is the drivers serving the branch. sf_trading's driver rules apply (tested: a driver with an overdue collection is refused) |
| [SF] | **Request cancellation** on a submitted quotation / order, with sf_trading's reasons. Shown only when sf_trading allows it: the request workflow is active and the salesman holds a requester role (Sales User / Counter Sale / Branch Head) |
| [STD]+[SF] | **Customer form:** optional photo of the CR / VAT certificate, attached to the customer. On Steel Force: mobile required (≥ 10 digits), and a VAT number needs the CR number and the photo |
| [STD]+[SF] | **New customers as on the desk** (sf_trading's Create Customer dialog, 19 Nov). Steel Force: the B2B choice is shown only to a **B2B Creator** (or System Manager); others see no customer type at all and make B2C only, and the server refuses a B2B one from them. A second customer of the same name is refused ("Customer 'X' already exists.", case ignored). Mobile and, with a VAT number, the certificate photo are required on the server too. The photo is filed on the customer's *VAT Certificate* document row. Sending a held customer for approval is left to the approvals work (see "Approvals" below). The "at least 10 digits" mobile rule follows sf_trading: only for a Saudi company's customer (Steel Force also has a Bahrain company, whose 8-digit mobiles sf_trading accepts). Standard: VAT / CR number only on a B2B customer (a VAT buyer gets a standard tax invoice, which needs the address); the address title is the name as saved; a new customer or address starts in the **company's country** (it was always Saudi Arabia, so a Bahrain van got the KSA rules unless the salesman changed it); the address form applies the B2B address rules to any customer with a VAT number, as sf_trading does |
| [STD]+[SF] | **Credit panel** (replaces the Phase 2 "customer status" card), on the customer screen and inside *Payment* on the invoice and order forms. It uses `vansale.api.customer.credit_status` and is cached per customer for offline use. It shows: limit, used (ERPNext's own figure: unpaid invoices + open orders), available, a bar, overdue invoices, and what this sale does ("after this sale: X available" / "X over the limit, will be refused"). On Steel Force it also shows: cash doesn't use the limit, the credit-days overdue that blocks credit, the approval state and what it misses, and the branch sub-limit |
| [STD]+[SF] | **Credit / Cheque refused on tap** (with the reason as a toast) when the customer can't have it: no credit limit under the setting, or (Credit only) sf_trading's overdue rule. The buttons look greyed with a warning icon |
| [STD]+[SF] | **Pre-check: credit limit.** ERPNext's limit check is run ahead with the sale's unpaid part (an invoice made from an order is skipped, as ERPNext does; the order-level bypass is respected; a Credit Controller gets a warning, not a stop). Also on Steel Force: the branch sub-limit. Fix: the overdue rule now applies only to Credit, not Cheque, matching sf_trading |
| [STD]+[SF] | **Cash = paid now; the delivery person decides "later".** The "Cash sale collection" setting (Vansale Settings + van) is gone. A cash sale without a delivery person must be paid. Picking one shows *Collect on delivery* (default) / *Paid now*; on delivery leaves the invoice unpaid with the driver on it (server checks it: no driver → no "later"). The picker shows only when the branch has drivers; each driver shows the cash they still hold, and one sf_trading would refuse (overdue collection / at the cash limit) is greyed with the reason and stopped before save. The invoice screen shows the delivery person. **Post-dated cheque** note with the days until it can be banked |
| [STD]+[SF] | **Last price and stock on every line** (invoice, quotation, order), as the desk's Last Selling Rate / Stock Availability: "Last to this customer: 53.000 / PCS · 18 Nov"; a red "Only 22 PCS in stock" when the lines of an item need more than the salesman's warehouse holds (several lines of one item add up; service items never warn); *History & stock* opens the item's last sales to this customer, its sales to other customers in the last 12 months, and its stock in every warehouse (own first). Tap the last price, or any price in the history, to use it as the line's rate (converted to the line's unit; line discount reset). Prices come from submitted sales (no returns) of the user's company within their permitted companies / cost centres; on Steel Force, as the desk's Last Selling Rate dialogs, the salesman's branch cost centre only (the panel says which). The warehouse list is sf_trading's Stock Availability there. Order and quotation catalogs now show stock too. Hints only: online, and the server still decides (`vansale.api.item.last_sales` / `stock_levels` / `insight`) (18 Nov) |
| [STD] | **Quotation as in the desk:** *Lost* asks why — the site's Quotation Lost Reasons (at least one when the site keeps a list, as the desk's "Set as Lost") plus details, shown on the quotation afterwards. A quotation past its Valid Till shows **Expired** at once (ERPNext flips it overnight), with a note; *Make order* only where Selling Settings allows orders from expired quotations, no *Make invoice*, *Lost* still possible (18 Nov) |
| [STD] | **Site root (/) no longer opens the van app for desk users.** The "Van Users land on the app" home-page rule matched Administrator too (it holds every role), so `/` showed the van app's login. Now `/` sends Administrator / System Managers to the desk (`/app`) and van users to `/vansale`; guests get the normal ERPNext login (18 Nov) |
| [STD] | **Fixes found in the frontend review (17 Nov):** queued offline sales now sync by themselves on start, on reconnect and on resume (nothing did; the sync badge that did it was never placed on a screen). Settings now load right after a login without PIN (they stayed empty until the next resume). Collections now use the customer's own receivable account (a customer with its own account was refused: "SI is associated with torbo - SF, but Party Account is Debtors - SF"). Submit is locked from the first tap (a double tap made two documents). Order-taker catalog search reaches the whole catalog. A draft's customer is locked on edit (the server never changed it). A lead's draft quotation can be saved again |
| [SF] | **Cash / Credit on sales orders** (shown where the site keeps it on the order): sent as `custom_payment_mode`, so sf_trading's overdue-credit check runs on a credit order and the cash limits only on a cash one. Carried into the invoice made from the order. An order made from a quotation starts on the "Default payment" setting. A credit order gets the credit-limit rule and the pre-check too |

**Tested** on steelforce.local over HTTP as the salesman:
- min price per UOM;
- pre-check, for a low rate and for credit without a limit;
- the credit-limit setting on save;
- cash collected through sf_trading;
- cheque sale (Payment Entry with cheque no / date, invoice paid);
- missing cheque number refused;
- branch modes;
- drivers list, and the driver rule refusing an overdue driver;
- customer with document photo;
- delivery person: no driver → paid now; driver + on delivery → submitted Unpaid with the driver; driver +
  paid now → Paid by Payment Entry with the driver; overdue driver greyed and refused; credit clears the driver;
- an offline sale queued, then synced by itself once back online; a collection from torbo (own account);
- credit panel and pre-check credit limit (TEASTA, limit 800, used 514.75: 460 on credit is refused with
  "174.75 over", 57.50 shows "227.75 available after"; cash shows "doesn't use the limit"; Field Shop with
  no limit: Credit / Cheque refused on tap, "Cash only").

The Phase 1 flows were run again and all pass. Frontend type-check and the 86 unit tests pass.

**Not tested live:** *Request cancellation*. The dev site has no active cancellation workflow, and the test salesman has no requester role, so the button stays hidden, as designed.

## Review of 20 Nov 2026 — batch 1 (21 Nov, branch `fix/sf-review-batch1`)

The "Vansale Steel Force Review" (H1–H7, M1–M8, L1–L4) was checked against the code on 21 Nov; this batch fixes the small items. Medium items (collections through sf_trading's payment function, branch-aware prices, which customers a salesman sees, letting him complete a credit customer) and the settings checklist come next.

| Tag | Change |
|---|---|
| [STD] | **H1 Document date from the server.** Online saves send no time; work queued offline keeps its time only within 24 h and never in the future (`vansale_offline_grace_hours`) |
| [STD] | **H2 Collections:** the van's company, that company's invoices only, and the cheque / transfer date sent with the reference |
| [SF] | **M1 Refunds** offer and accept only the branch's modes marked for returns |
| [SF] | **H4 Returns pre-checked** for sf_trading's customer gates that refuse them (phone, credit-customer documents), before the return is sent |
| [STD]+[SF] | **H7 Minimum price after the invoice discount** in the pre-check (ERPNext `net_rate`, tax left out), as sf_trading checks it on save |
| [SF] | **M2 Return window** shown on the invoice: Return hidden when it has passed (a user who may override sees a note) |
| [SF] | **M3 Items** limited to the company's items (Item Default), as sf_trading shows branch users; selling another is refused |
| [SF] | **M4 Orders pre-checked** against the customer's and salesman's cash limit, payment days and branch cash limit |
| [SF] | **M5 Lead → customer** follows the new-customer rules (mobile, no duplicate name) |
| [STD] | **L1** A Lost, Ordered or Expired quotation is refused by the server when invoiced |
| [STD] | **L2** A return keeps the original invoice's sales team |
| [STD] | Customer hook no longer adds a second 100% sales-team row to a desk customer; CR field falls back to `custom_commercial_registration_number` |

## Review of 20 Nov 2026 — batch 2 (21 Nov, same branch)

The medium items, and the answers of 21 Nov: returns stay as sf_trading has them (not exempt from the credit-documents check; the app pre-checks them); customers — a setting, see below; print format — the company's desk format unless the van / settings choose one; no delivery-note step for now.

| Tag | Change |
|---|---|
| [SF] | **H2 Collections through sf_trading's payment function** (`create_pos_payments_for_invoice`), one entry per invoice, oldest first: a cheque mode becomes a post-dated cheque (number and date required; sf_trading may keep it in Draft and dates it as the invoice), **Loyalty** (write-off up to the company's Max Payment Write Off) on the last invoice paid, more than the open invoices refused. Used when collections are submitted at once; a Draft setting keeps the app's own draft entry |
| [SF] | **Part cheque on a sale:** laid out like a split cash sale — the cheque row (amount blank = the rest), then "Add payment mode" rows in cash / bank modes (one always, more with "Split payment"), as the desk's cheque dialog (cheque entry first, the others after, loyalty on the last). The older single "rest mode" is still accepted from queued sales |
| [SF] | **Loyalty at the sale** (cash paid now posted by Payment Entry, or cheque) and at collection; checked before saving against sf_trading's own rules (company maximum, loyalty already given on the order, an unapplied order advance that carried loyalty) |
| [SF] | **H7 Branch prices:** the price list is one of the branch's lists (else its default), as sf_trading requires on save; Item Prices limited to other branches are skipped and the branch's own price comes first (sf_trading's `visible`) |
| [STD] | **H3 "Customers a salesman finds"** (Vansale Settings, default *Own customers*): *Own list, search all* keeps the list to his own customers but lets a search find any customer the desk lets him see (company / branch access); such a customer is marked "Not your customer" |
| [STD] | **H4 Complete a credit customer from the van:** second phone number and document photos on the contact screen (the customer is not re-saved, so an approved customer is not sent back for approval); Payment Terms stay with the office |
| [STD] | **M7 Order advance:** an invoice made from an order with an advance shows it and asks the customer only for the rest |
| [SF] | **M6 Print format:** van → Vansale Settings → the company's desk print format (Company > Print Formats) → the app's own |
| [SF] | **M4 Own cash:** the collections screen shows the salesman's uncollected cash sales against his cash limit / payment days |
| [SF] | **Check Steel Force setup** button on Vansale Settings: site settings and every van (cash posting, branch, Branch Configuration, branch price list, customer group, roles, loyalty) with what to fix |

## Batch 3 (21 Nov, same branch) — the rest of the frontend review

Steel Force:

| Tag | Change |
|---|---|
| [SF] | **#1 Returns under sf_trading's return approval** are saved as drafts with the refund planned on them (sf_trading's plan, paid when the approval submits the return) and open on the approvals screen to be sent; before, the app submitted them and sf_trading refused, so nothing was saved |
| [SF] | **#2 Receive payment on an order** (an advance) through sf_trading's `create_payments_for_sales_order`: branch modes, a cheque mode as a post-dated cheque, loyalty only when it closes the order |
| [SF] | **#26 Orders** take Cheque (where the branch has cheque modes) and a delivery person on a cash order |
| [SF] | **#27** No sale, cash included, to a customer waiting for approval (checked before saving, offline too); credit and cheque refused offline (sf_trading's credit rules are checked online) |
| [SF] | **#8** Cash held by the branch's delivery persons on the collections screen |

Standard:

| Tag | Change |
|---|---|
| [STD] | **#3** A return on a partly paid invoice settles what the invoice still owes (ERPNext's own credit-note reconciliation) and refunds only the rest; the refund box shows the limit |
| [STD] | **#4** A refund with no payment mode is refused instead of silently kept as credit |
| [STD] | **#5** Route "Today's summary" counts the day's sales / returns / collections for the customers on the route; the visit card's Invoice / Payment open with the customer |
| [STD] | **#6** Van stock reads the van's warehouse first, lists sold-out items (the "Out" count), no 500-item cut |
| [STD] | **#9** Paying more than the invoices is refused unless advances are allowed (then the confirm says how much stays as advance) |
| [STD] | **#10** Queued work belongs to the user who did it and is sent only for them; logout counts the real queue; "Sign in with password" on the PIN screen warns about unsent work |
| [STD] | **#11** A 502 / 503 / 504 (restart, deploy) is a network failure: the sale is queued, not refused |
| [STD] | **#12** An ended web session is recognised: the app says so and goes to sign-in (unsent work stays) |
| [STD] | **#13** *Retry* sends at once (the backoff wait is cleared) |
| [STD] | **#14** "already exists" is a refusal, not success (the unposted sale stayed deleted from the queue); failures are classified by the server's exception type, so Arabic messages are handled |
| [STD] | **#15** Web app offline start: the service worker keeps the build's files and the last page, so the app and every screen open without a connection (built files are hashed, each build kept apart, older ones dropped) |
| [STD] | **#16** Dismiss asks first; an unclassified failure reads "Not sent" |
| [STD] | **#19** Editing a draft made in the desk / with a pricing rule no longer applies its line discount twice |
| [STD] | **#20** Delete draft works (own drafts, server-checked); "Make invoice" on an order opens the waiting draft instead of making another |
| [STD] | **#21** A lead whose status ERPNext set (Quotation, Opportunity) can be edited |
| [STD] | **#22** One client id per new customer / quotation / order / conversion, kept across retries (a timeout + retry returns the first document) |
| [STD] | **#23** Contact / address Save stays off until the record has loaded |
| [STD] | **#25** The discounted rate is rounded to rate precision before the amount, as ERPNext does |
| [STD] | **#28** A salesman deletes only his own drafts (new sites: no delete right on Quotation / Sales Order) |
| [STD] | **#29** Offline-saved sales show at the top of the invoice list; "New customer" mid-sale keeps the cart |

| [STD] | **#16 Fix a refused queued entry with a form:** lines (qty, rate, remove), Cash / Credit (Cheque when it was one) with the cash mode or cheque no. / date, loyalty, discount, payment amount / reference, notes. A split payment is dropped when the lines change (paid whole in the main mode, said on screen). The raw JSON stays under "Advanced" for support. The queue list refreshes when a send finishes |
| [SF] | **Per-line price list (offer lists):** when the van's branch has more than one selling list, each line of an invoice / order / quotation can be priced from one of them (sf_trading's per-row `custom_price_list`). The rate and minimum come from that list (an enforcing offer list may go below the usual minimum), the pre-check uses it, it is checked against the branch's lists on save, and it carries from order to invoice |
| [STD] | Split cash sale "tap for rest" fills what the customer pays (less advance / loyalty), not the invoice total |

Still open: a delivery-note step (not wanted for now).

## Frontend review (17 Nov 2026) — open items

From a read-through of the whole frontend. The three marked *fixed* were confirmed live and fixed in Phase 2;
the rest are from code reading, not yet reproduced. [SF] = matters for Steel Force; others are [STD].

**Money, returns, route, stock**

| # | Item | Tag |
|---|---|---|
| 1 | Returns are always submitted (`invoice.py` return_against). With sf_trading's return approval on, the submit is refused and nothing is saved. The return window (`sales_return.window_state`) is not checked in the picker | [SF] |
| 2 | A collection with no invoice (Advance, or a customer with nothing open) makes a Payment Entry with no reference; sf_trading's voucher gate refuses it. No way to collect against a Sales Order | [SF] |
| 3 | Refund on a partly paid invoice: invoice 100, 70 paid, return 50 → the screen refunds 50 cash while the invoice still shows 30 due (should clear the 30, refund 20) | [STD] |
| 4 | Refund silently dropped when the payment-mode list is empty: the confirm says "Refund in full", the return is kept as credit | [STD] |
| 5 | Route "Today's summary" is always 0 (no visit ever sends its invoice / payment); the visit card's Invoice / Payment buttons open blank forms without the customer | [STD] |
| 6 | Van stock reads the User Permission warehouse, sales use the van's; list cut at 500 items; "Out" count always 0 | [STD] |
| 7 | Branch payment modes are filtered in the list only (not on save); cheque (PDC) modes appear on collection and refund; refunds should use the branch's return modes. No cheque date on collections | [SF] |
| 8 | Nothing shows the cash delivery persons still hold (sf_trading's "Delivery Person Payment Pending") | [SF] |
| 9 | Overpaying picked invoices silently becomes an advance; the confirm says "For N invoices" | [STD] |
| — | *Fixed:* collections used the company Debtors account, refused for a customer with its own receivable | [STD] |

**App shell and offline**

| # | Item | Tag |
|---|---|---|
| 10 | Logout can leave queued sales that then post under the next user (pending count is 0 after a cold start; PIN screen's "Sign in with password" skips the guard) | [STD] |
| 11 | A 502 / 503 / 504 (bench restart, deploy) is treated as a validation error: an online save shows an error instead of queuing | [STD] |
| 12 | An expired web session leaves the app stuck (every call 403, silently) | [STD] |
| 13 | *Retry* doesn't skip the backoff (up to 30 min of nothing) | [STD] |
| 14 | "already exists" is treated as success, so a sale refused for a duplicate name is deleted from the queue unposted | [STD] |
| 15 | Web PWA: the service worker caches nothing; an offline cold start or a not-yet-opened screen fails (seen: after an offline save the invoice list could not open). The APK is not affected | [STD] |
| 16 | Sync errors: Steel Force messages show as a generic "Error"; Arabic messages break the classification; Dismiss has no confirmation; fixing means editing JSON | [STD]+[SF] |
| — | *Fixed:* the queue never synced by itself (the badge that did it was never placed on a screen) | [STD] |
| — | *Fixed:* settings stayed empty after a login without PIN | [STD] |

**Selling screens (invoice, quotation, order, customer, lead)**

| # | Item | Tag |
|---|---|---|
| 17 | Minimum price ignores the additional discount: sf_trading compares the rate after the document discount, so any additional discount passes the app and is refused by the server (even on a draft save) | [SF] |
| 18 | Branch pricing ignored: the app's price lookup skips Branch Configuration price lists and branch-limited Item Prices (no branch price lists on dev; check production) | [SF] |
| 19 | Editing a draft made in the desk (or with a Pricing Rule) applies its line discount twice: under-bills, or a false "below minimum" on Steel Force | [STD] |
| 20 | Delete on a draft invoice always fails (Van User has no delete on Sales Invoice); each "Make invoice" on an order makes another draft with no duplicate check | [STD] |
| 21 | Editing a lead that has a quotation always fails (the form sends status "Quotation", the server refuses it) | [STD] |
| 22 | Customer create isn't idempotent (no client_id): with a large CR photo a timeout + retry makes "Name - 1" or a duplicate-VAT error. Quotation / order saves and conversions also make a new client_id per retry | [STD] |
| 23 | Contact / Address can be wiped: Save works while the record is still loading or failed to load, and blanks mean "remove" on the server | [STD] |
| 24 | B2B: the app decides by customer type, sf_trading by "has a VAT number" — a B2C customer with VAT and a short address is refused late | [SF] |
| 25 | Rounding: a discounted rate isn't rounded to rate precision before the amount, so the preview can differ from ERPNext by halalas, and a "rest" split payment can be refused | [STD] |
| 26 | Steel Force orders also allow Cheque and a delivery person; the app offers Cash / Credit only. Quotation → order gets the default payment type with no choice | [SF] |
| 27 | Credit / Cheque sales queue offline on a possibly stale credit status; a customer awaiting approval can still be picked and sold to (the panel says "no sale until approved", the buttons stay on) | [SF] |
| 28 | Van User may delete other salesmen's draft quotations / orders (no owner restriction) | [STD] |
| 29 | Queued invoices don't appear in the invoice list; tapping "New customer" mid-sale loses the cart | [STD] |
| — | *Fixed:* a double tap on Submit made two invoices / orders (buttons locked only after the pre-check and confirm) | [STD] |
| — | *Fixed:* order-taker mode: after the first search only items stocked in the branch could be found | [STD] |
| — | *Fixed:* changing the customer on a draft invoice / quotation was silently ignored — the customer is now locked on edit | [STD] |
| — | *Fixed:* a lead's draft quotation could not be saved ("Pick a lead") | [STD] |

**Ideas, by value to the salesman:** visit-centred flow (visit card opens the sale / collection for that
customer and the day summary is real) · end-of-day cash sheet matching sf_trading's Accounting Clearance ·
plain-language sync screen with a "waiting for office" state · cheque (PDC) collections through sf_trading ·
delivery-person pending list · autosave the half-filled invoice (Android back and the PIN screen drop it).

## Not needed for now (your decision, 17 Nov)

- **Request credit from the app.** In sf_trading, a credit limit on an existing customer sends it back for
  approval, and until it is approved every sale to that customer is refused, cash included. If it's wanted later,
  the safe form is a request to the office (a task with the details and photos) that doesn't touch the customer.

## Approvals — ready for the other developer

We don't build approval screens. We make sure:

- Documents are created as the salesman (owner = submitter).
- The app **never submits a governed document directly**. A document under approval is saved and its state
  shown; submitting is the approval engine's job.
- The app shows a document's approval state and the server's reason when something waits. The state field is
  `custom_approval_status` for customers, `workflow_state` otherwise.
- `vansale.steelforce` is where the approval calls will go: `get_approval_state`, `get_transitions`,
  `quick_apply_workflow_action`, `get_my_pending_approvals`. The other developer can add them there.
- **Open for the approvals work: sending a new customer for approval.** A customer the approval holds (a
  credit customer, or one with a VAT number while sf_trading's B2B approval is on) stays in Draft when the app
  creates it, and nothing sends it; the app only shows "waiting for approval". sf_trading's desk dialog sends it
  at once with `sf_trading.master_approval.send_new_master("Customer", name)`. The app already files the VAT
  certificate on the customer's VAT Certificate row, which that approval checks.

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
   - *Invoice updates stock* (Disabled for order takers).
   - *Cash sale posting* = Payment Entry.
3. **B2B customers:** only a salesman with the **B2B Creator** role sees the B2B choice in the app.
4. **Van mode only:** add the van warehouse to the branch's Branch Configuration.
5. Items need an Item Default for the company; sf_trading hides other items from branch users.
6. Cancellation requests: the salesman needs a requester role (Sales User / Counter Sale / Branch Head) and the
   cancellation workflow must be active.

## Test site state (steelforce.local)

- Test van **DMM1**: user `van.dmm1@steelforce.local` / `VanTest#2026`, branch Dammam, warehouse *Van DMM1 - SF*,
  *Invoice updates stock* = Disabled.
- Van DMM1: Cash sale posting = Payment Entry.
- Global settings:
  - Quotation becomes = Both
  - Cash sale collection = Salesman chooses
  - CR number field = `custom_commercial_registration_number`
  - Credit only with a limit = on
  - Ask for delivery person = on
- Item Prices (Standard Selling): TEST 60, TETST3 25.
