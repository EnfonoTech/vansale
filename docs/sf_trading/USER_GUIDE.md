# SF Trading — Admin Handbook

A handbook for the person who sets this system up and keeps it running.

Every feature is written the same way: what it is, where to find it, the steps to set it up, and what to do when it goes wrong. Plain English, short sections. Use the search box in the sidebar to jump straight to a word — try `letter head`, `credit limit`, or an error message you are looking at.

**Two places to read this:**

- In the browser: `/user-guide` — no login needed.
- Inside the desk: press `Ctrl+G` (`Cmd+G` on a Mac) and type **SF Trading User Guide**.

Both read the same file, so they can never disagree with each other.

**Looking for how to run the system rather than what it does?** The **Technical Guide** at `/technical-guide` is written for the client's own system administrator: what may be configured in the live system, the steps, the routine checks, and the short list of jobs that need Enfono. This handbook explains the features; that one explains the running of them.

---

## 1. What this app does

SF Trading sits on top of ERPNext and adds branch-based trading controls for Steel Force.

The idea in one line: **every user belongs to a branch, and a Branch Configuration record decides what that branch is allowed to do.**

That one record drives the company a user trades under, the warehouses they can pick, the cost centres they can post to, the payment modes they can take money in, and the letter head their documents print with. Credit control, inter-company invoicing, stock checks and print layouts all read from it.

So set Branch Configuration up first. Everything else depends on it.

### What you get on top of ERPNext

| Area | What is added |
|---|---|
| Branches | One setup record per branch that grants permissions automatically |
| Credit control | Customers with credit limits are restricted to named branches |
| Selling prices | A price floor per item, checked as the user types |
| Stock | Live stock next to every item search, warehouse checks before save, transfer requests from the invoice |
| Buying | A billed-quantity guard, automatic return receipts, last purchase rates |
| Supplier payments | Payment Advice: one approval covering many invoices, with optional scheduled runs |
| Printing | A print format per company, plus two statement layouts |
| Reports | 13 reports, from daily cash to reorder suggestions |
| Dashboards | A Business Dashboard and a Payment Advice Builder |

---

## 2. Set-up order

Follow this order for a new site or a new branch. Each step assumes the one above it is done.

| # | Step | Screen | Why this order |
|---|---|---|---|
| 1 | Company, accounts, warehouses, cost centres | ERPNext setup | Nothing below works without them |
| 2 | Letter Head (with header and footer images) | Letter Head | Branches and print formats point at it |
| 3 | Branch records | Branch | Branch Configuration needs them to exist |
| 4 | **Branch Configuration**, one per branch | Branch Configuration | Grants every user permission |
| 5 | Company Print Format rows | Company | Each company prints its own layout |
| 6 | Item Group margins / price floors | Item Group, Item | Turns on the selling price check |
| 7 | Customer credit limits and Branch Access | Customer | Turns on credit control |
| 8 | Inter Company Branch, if you invoice between companies | Inter Company Branch | Needed before the first internal invoice |
| 9 | Payment Automation Settings, only when you want scheduled payments | Payment Automation Settings | Leave off until Payment Advice is understood |

A good check after step 4: log in as a branch user and open a new Sales Invoice. The warehouse, cost centre and letter head should already be filled in. If they are not, go back to step 4.

---

## 3. Configuration screens

### 3.1 Branch Configuration

**What it is** — the master setup record for one branch. One record per branch, named after the branch.

**Where** — search `Branch Configuration` in the Awesomebar.

**Fields**

| Field | Type | What it is for |
|---|---|---|
| `branch` | Link → Branch (required, unique) | The branch this record sets up. The record takes the branch name. |
| `company` | Link → Company | The company this branch trades under. |
| `warehouse` (table) | Branch Configuration Warehouse | Warehouses this branch may use. |
| `cost_center` (table) | Branch Configuration Cost Center | Cost centres this branch may post to. |
| `mode_of_payment` (table) | Branch Configuration Mode of Payment | Payment modes allowed here. Each row can be flagged `for_return` or `for_pdc`. |
| `user` (table) | Branch Configuration User | Users in this branch, each with an optional Role Profile and an `is_default_branch` tick. |

**Do this**

1. Pick the `branch`, then the `company`.
2. Add the warehouses, cost centres and payment modes this branch is allowed to use. The pickers only offer records belonging to the company you chose.
3. Add each user. Set a Role Profile if the branch should grant roles.
4. Tick `is_default_branch` for the users whose main branch this is — **only one Branch Configuration per user may have this ticked**.
5. Save.

**What happens on save** — the app creates User Permission records for that user: the Branch, the Company, every listed warehouse, cost centre and payment mode, and the branch's Letter Head. Where a Role Profile is set, the roles in it are granted. The user's defaults across the desk come from the record ticked as default.

**What happens when you remove a row** — the permissions that row granted are taken away again, unless another Branch Configuration still grants the same thing to that user.

**It refuses to save if** a listed warehouse or cost centre belongs to a different company than the one on the record. The message names both.

> **Example.** Branch **Riyadh**, company SF Trading LLC, warehouse Riyadh Stores, cost centre Riyadh - SFT, payment mode Cash, user `riyadh.manager@sf.com` with Role Profile *Branch Manager* and `is_default_branch` ticked. After saving, that user can only see Riyadh data, and a new Sales Invoice already carries Riyadh Stores and Riyadh - SFT.

### 3.2 Customer Branch Access

**What it is** — the list of branches allowed to sell to a customer **on credit**.

**Where** — the "Branch Access" grid on the Customer form.

**Why it exists** — a customer given credit at one branch should not automatically be invoiced on credit by every other branch.

**Do this** — usually nothing. The moment a customer's credit limit goes from blank or zero to a real amount, the app adds the saving user's own branches. Add rows by hand only for extra branches.

**It refuses to save if** the customer has a credit limit but the Branch Access table is empty. The message is *"At least one Branch must be added in Branch Access when a Credit Limit is set."*

> **Example.** Give ACME Contracting a credit limit of 50,000 while logged in as a Riyadh user, and Riyadh is added for you. To let Jeddah invoice ACME on credit too, add a second row for Jeddah.

### 3.3 Inter Company Branch

**What it is** — a routing table that says, for each company in the group, which cost centre and warehouse to use on the Purchase Invoice created on the buying side of an internal sale.

**Where** — its own list. It also appears as the `inter_company_branch` field on a Sales Invoice billed to an internal company.

**Fields**

| Field | Type | What it is for |
|---|---|---|
| `branch_name` | Data (required, unique) | The name of this routing setup. |
| `company_cost_centers` (table) | Inter Company Branch Cost Center | One row per company: `company`, `cost_center`, `warehouse`. |

**Do this**

1. Give the setup a clear name, for example *Central Warehouse Transfer*.
2. Add one row per company, with the cost centre to post to and the warehouse to receive into.
3. Save, then set `inter_company_branch` on internal Sales Invoices.

**It refuses to save if** the same company appears twice.

**It blocks submission if** the invoice updates stock and the chosen setup has no warehouse for the buying company: *"Configure Warehouse in Inter Company Branch … for company … to create Purchase Invoice with stock update."*

### 3.4 Company Print Format

**What it is** — lets each company print a document type with its own layout, without changing the layout every other company uses.

**Where** — the "Print Formats" grid on the Company form. There is also a single field, `custom_delivery_note_print_format`, on the same form.

**Do this**

1. Open the Company.
2. In the Print Formats grid, add a row per document type: `document_type` = Sales Invoice, `print_format` = the layout for this company. The picker only offers formats built for that doctype.
3. Set `custom_delivery_note_print_format` if you want the **Print DN** button on invoices to work. This field is separate and feeds only that button.
4. Save.

A company with no row simply falls back to the normal doctype default.

**If it goes wrong** — a blank `custom_delivery_note_print_format` makes the Print DN button say *"No Delivery Note print format set on company …"*.

### 3.5 Payment Automation Settings

**What it is** — the schedule that raises supplier payments without anybody clicking. One record per company and party type.

**Where** — search `Payment Automation Settings`.

Full detail is in section 7.5. The short version: a run does as much as you allow, and each step needs the one before it.

1. Create Payment Advice
2. Submit Payment Advice
3. Create Payment Entry
4. Submit Payment Entry

**Start with step 1 only, with Dry Run ticked.** Read what it says it would do, then widen. Step 4 moves real money.

### 3.6 Company defaults this app leans on

These are ordinary ERPNext fields on the Company, but this app and ERPNext both read them, so a wrong value shows up in odd places.

| Field on Company | Used for | Watch out for |
|---|---|---|
| Default Payable Account | Payment Advice, supplier payments | A supplier with no payable account and no company default is skipped by automation |
| Default Expense Account | Where stock rounding differences land | On this site it is the **Cost of Goods Sold** account, so Purchase Receipts post fils-level rounding to COGS. See 9.4 |
| Default Cost Center | Fallback when a branch has none | Keep it set; several flows fall back to it |
| Stock Adjustment Account | Stock Reconciliation write-offs | Should not be a COGS account |
| Default Letter Head | Statements and print formats | Statements fall back to this when no letter head is chosen |

### 3.7 Letter Head and print formats

**What it is** — the artwork at the top and bottom of printed documents, and the two statement layouts this app ships.

**The rule to remember:** for report print formats, **the live copy is the record in the database, not the file in the app folder.** The file is the source that gets committed; the record is what prints. Pulling a new version of the app changes nothing on its own — somebody has to load the file into the record.

| Print format | Used from | File in the app |
|---|---|---|
| Statement of Account | Accounts Receivable report → Print or PDF | `vansale/sf_trading/print_formats/statement_of_account_accounts_receivable.html` |
| Statement of Account (Ledger) | General Ledger report → Print or PDF | `vansale/sf_trading/print_formats/statement_of_account_general_ledger.html` |

**Do this to print a customer statement**

1. Open the **Accounts Receivable** report.
2. Put **one** customer in the Party filter. A statement is addressed to one customer.
3. Print, or export as PDF, and pick **Statement of Account**.

The statement draws the letter head artwork itself when you have not picked a letter head in the print dialog, so the header and footer look the same either way. If you do tick "With Letter head", the print wrapper draws it and the statement stands back, so it is never drawn twice.

**If it goes wrong** — see 9.2.

### 3.8 Selling price floor

**What it is** — a check that stops an item being sold below cost.

**How the floor is worked out** — `max(last purchase rate, warehouse valuation) × (1 + Item Group margin %)`. If `custom_enforce_min_price` is set on the item, a fixed price-list floor is used instead.

**Do this**

1. Set the margin percentage on the Item Group.
2. For items that must never go below a set price, tick `custom_enforce_min_price` on the Item and set the price in the price list.

**What the user sees** — a **Selling Price Warning** as they type, and a hard **Invalid Selling Price** block on save. It applies to Quotation, Sales Order, Delivery Note and Sales Invoice.

### 3.9 Roles and who can do what

| Role | Prepares payments | Approves payments | Configures automation |
|---|---|---|---|
| Purchase User | Yes | No | No |
| Accounts User | Yes | No | No |
| Accountant | Yes | Yes | No |
| Finance Manager | Yes | Yes | Yes |
| Accounts Manager | Yes | No | Yes |

Other roles worth knowing:

- **B2B Creator** — may create B2B company customers through the quick-create dialog. Shipped by this app.
- **Driver** — permissions shipped by this app for delivery staff.
- **System Manager** — sees the Gross Margin column on the DCR Report, and can release a stuck Payment Advice.
- **Stock Manager** — the only role that can act on Stock Entries waiting in *Pending Acceptance*.

Approvals themselves are not run by this app. They come from **Permission Manager** — see 9.3.

---

## 4. Everyday features, by document

### 4.1 Sales Invoice

**Stock check.** Change an item's quantity, warehouse or item code and the row is checked against real warehouse stock. If there is not enough, an **Insufficient Stock** message appears, the quantity is reset to zero, and saving is blocked until the row is fixed or removed.

**Credit control.** Setting `custom_payment_mode = Credit` narrows the customer list to customers with Branch Access for this branch. Pick a customer with no credit limit for this company and you get **No Credit Limit** and the mode returns to Cash. A customer with an older unsettled overdue credit invoice raises an **Overdue Credit Invoice** warning and the save is blocked on the server until it is settled.

**Cheque.** Setting `custom_payment_mode = Cheque` needs at least one payment mode on the branch flagged `for_pdc`. Without one you get **Cheque Not Available** and the mode returns to Cash.

**Barcode.** Scan into the header `scan_barcode` box or a row's `barcode` column. A new row is added with quantity 1, or an existing row's quantity goes up. Unknown codes say *"Cannot find Item with this Barcode."* Empty scan rows are cleared before save.

**What happens on submit** — depends on the payment mode.

| Mode | On submit |
|---|---|
| Cheque | A Cheque Payment dialog: cheque date, number, amounts |
| Cash or Bank, no driver | "Enter Payment Amounts", pre-filled with the branch's modes. The total must match the outstanding amount |
| Cash or Bank with a driver | No payment dialog. Confirms, submits, and leaves collection to the driver |
| Credit | A plain confirmation |

A driver with an unsettled invoice older than their `custom_payment_days` (1 day by default) blocks a new Cash invoice for that driver.

After submit a print preview opens with **Print Invoice** and **Print DN**.

**Other conveniences** — the customer's sales team is copied in automatically; focusing an item row shows stock per warehouse with a **Request Items** button that raises and submits a Material Transfer Request; the selling price floor from 3.8 applies here.

### 4.2 Stock and Material Request

- **Stock Entry** — a brand-new entry clears the header warehouses once, so a stale default cannot leak into a different transfer.
- **Material Request** — a red, yellow or green pill shows `custom_priority`. A submitted transfer request shows a **Transfer Status** table of requested, transferred and pending quantities, read from the linked Stock Entries. If something still needs buying, the **Purchase Request** button raises a linked purchase request, filling the warehouse from the transfer's source and tagging items with `custom_source_mr`.
- **Stock Availability** — a button on Sales Order, Quotation, Delivery Note, Purchase Invoice, Purchase Order, Purchase Receipt, Supplier Quotation and Stock Entry grids shows stock per warehouse for the selected item.
- **Returns** — on any return document, type the quantity as a positive number and it is turned negative for you. Submitting a Purchase Invoice return also creates and submits the matching Purchase Receipt Return, capped at what is still returnable.
- **Purchase Invoice guard** — a Purchase Invoice cannot be saved if the billed quantity against a Purchase Order line would go past what that line ordered, counting every other invoice that is not cancelled.

### 4.3 Quotation

- A **Sales Invoice** button on a submitted quotation that is not yet ordered creates the invoice. A quotation that already has a live invoice shows **Duplicate Invoice** instead.
- The status (Open, Partially Ordered, Ordered) is recalculated whenever a linked invoice is submitted or cancelled.
- Setting the header `set_warehouse` pushes that warehouse onto every item row.

### 4.4 Customer, Supplier and pricing

**Quick-create dialogs** from draft sales and purchase documents.

- **B2C Individual** — name and mobile only.
- **B2B Company** — offered to B2B Creator, B2B Manager and System Manager. Needs a VAT number, and for Saudi companies a full address.

Format rules: VAT exactly 15 digits starting and ending with `3`; mobile at least 10 digits; postal code exactly 5 digits.

Duplicate VAT numbers are blocked unless the user has an override role, ticks **Allow Duplicate VAT** and gives a reason. A customer with a VAT number cannot be saved without an attachment — the VAT document.

**Last Purchase / Selling Rate** — buttons on item grids show the last 20 transactions for the item, limited to the document's cost centre.

**Quick Entry** — set `set_warehouse` first, then open the dialog to see every sales item with live stock and rate for that warehouse. Tick items, set quantities, add them all at once. Asking for more than there is in stock is flagged before you can add it.

### 4.5 Everywhere in the desk

- **Accounting dimension sync** — changing branch, cost centre or project pulls that branch's defaults and pushes the values down onto every item row.
- **Item search** — every item field shows **Stock: qty (warehouse)** and **Rate:** next to each result, and sorts numerically, so "2MM" comes before "2.6MM". This replaces ERPNext's own item search.
- **Overdue alert** — a quiet banner for users who should know about overdue invoices, fed by the daily job in section 8.
- **Workflow Approval badge** — the workspace shortcut carries a live count of pending documents, refreshed every 60 seconds.
- **Impersonation logging** — when an administrator uses Frappe's impersonate feature, the reason is written into the Activity Log, not just to the target user's notifications.

---

## 5. Reports

All reports are in the Awesomebar by name. Every one of them has a Company filter; set it first.

### 5.1 Money and cash

| Report | What it answers | Notes |
|---|---|---|
| **Cash Flow Money In vs Money Out** | How much money came in and went out, period by period, with a running balance | Money In is every debit to a Cash or Bank account, Money Out every credit. The closing balance ties to the Trial Balance. Tick "Exclude internal transfers" to hide money moved between your own accounts |
| **Cash Flow Detail** | The vouchers behind any figure on the summary | Opened by clicking a period on the summary. Group by transaction, party, voucher type, account or mode of payment |
| **Mode of Payment Invoice Wise** | How each invoice was actually settled — Cash, Card, Credit or a mix | Stitches together counter sales, Payment Entries and journals |

### 5.2 Receivables and payables

| Report | What it answers | Notes |
|---|---|---|
| **Customer Statement of Account** | A customer's account, ready to send | Prints with the Steel Force letter head. One customer at a time |
| **Invoice Due and Overdue Report** | Sales and purchase outstanding side by side | Overdue only by default, with ageing buckets and the Payment Advice each invoice sits on |
| **Supplier Due Payment Report** | What is owed to suppliers, by due date | Overdue days, ageing buckets, and the advice each invoice is already on |
| **PDC Report** | Cheques on hand | Cheque date, posting date and a reminder date three days before |

### 5.3 Stock and buying

| Report | What it answers | Notes |
|---|---|---|
| **Reorder Recommendation** | What to order, how much, and when to reorder each item | Works out a reorder level and quantity per item and warehouse from what actually sold. See below |

**Reorder Recommendation in short.** Suggested level = average daily sales × lead days + safety stock. Suggested quantity tops the item back up to that level plus the coverage days you choose, less what is already on order.

Three things to know before you trust the numbers:

- Transfers between your own warehouses are left out of both demand and supply. On this site they move more quantity than sales do, so counting them would order stock that is already in the building.
- Lead time comes from purchase history where receipts name their purchase order, then the item master, then the filter default. Most rows fall back to the filter default, and the **Lead From** column tells you which was used.
- Nothing has a reorder level configured on this site, so every suggestion is new. The report proposes; it does not change the Item.

### 5.4 Daily cash — the DCR family

| Report | What it answers |
|---|---|
| **DCR Report** | The daily cash summary: opening balance, cash and credit sales, VAT, petty cash, closing balance. The Gross Margin column is System Manager only |
| **DCR Detail** | The transactions behind one line of the summary |
| **DCR Detailed** | One day's full cash ledger — every invoice and payment that day, split into Cash and Bank or Card |

### 5.5 Approvals and loyalty

| Report | What it answers |
|---|---|
| **Work Flow Approval** | Every document sitting in a pending state, with a bulk **Apply Workflow Action** to approve or reject the ticked rows |
| **Loyalty Rewards Report** | Loyalty reward journals with their invoice, customer and reward as a percentage of the invoice, plus a customer summary |

---

## 6. Dashboards and pages

| Page | Path | What it is for |
|---|---|---|
| **Business Dashboard** | `/app/business-dashboard` | Sales, expenses and profit, cash and bank balances, sales trends, expense breakdown, money in against money out, outstanding money, and plain-language insights. Filters for dates, cost centre and payment mode |
| **Payment Advice Builder** | `/app/payment-advice-builder` | Sweep everything payable and raise one advice per supplier in a single action. See 7.2 |
| **SF Trading User Guide** | Awesomebar → SF Trading User Guide | This handbook, inside the desk |

The Business Dashboard reports data problems it finds — payments with no mode of payment, possible duplicate invoices — but never edits anything. Treat those counts as a to-do list, not an error.

---

## 7. Supplier payments — Payment Advice

ERPNext's Payment Request covers one document per request. It cannot say *"pay these 21 invoices for one supplier"*. A Payment Advice can: one party, many references, one authorised amount, one approval.

```
Outstanding invoices → Payment Advice → Approval → Payment Entry → Invoice paid
```

References are not limited to Purchase Invoices. They may be Purchase Invoices, Sales Invoices, **Journal Entries**, Expense Claims, Purchase Orders or Sales Orders. Real supplier balances often contain journals, and they are pulled in for you.

Outstanding figures are not recalculated by this app. They come from the same ERPNext engine the Payment Entry form uses, so part-payments, credit notes and returns are already netted before you see them.

### 7.1 Raise one advice

1. **New Payment Advice.** Set Company, Party Type and Party. Every other picker is then limited to that company and party.
2. **Get Outstanding Documents**, with whatever filters you need.
3. **Enter the Payment Amount.** It is allocated oldest first. Rows beyond the amount stay listed with zero allocated so you keep the full picture. The headline reads, for example, *"2,464.713 of 2,464.713 allocated across 3 of 3 references"*.
4. **Submit**, or use the workflow actions where approval is switched on.

An invoice can sit on only **one** live advice, drafts included. If it is already on another one you are told which, so nothing is paid twice.

### 7.1.1 Get Outstanding Documents

The same filters the Payment Entry form offers, because it is the same code underneath.

| Filter | Use |
|---|---|
| Posting Date — From / To | Restrict by document date |
| Due Date — From / To | "Pay everything due by month end" |
| Outstanding — Greater / Less | An amount window |
| Cost Center | One cost centre only |
| Outstanding Invoices | On by default |
| Orders To Be Billed | Include unbilled orders |

Use **Outstanding — Greater** to keep rounding scraps out. Live data holds invoices with 0.005 outstanding; a floor of 1.000 removes them.

### 7.2 Batch by supplier — the Builder

`/app/payment-advice-builder`

1. **Filters** — company, party type, party, due on or before, ageing over N days, minimum advice total, cost centre, branch, include on-hold parties.
2. **Fetch Outstanding** — suppliers come back grouped, biggest first, with invoice count, oldest ageing, currency and total. Parties that cannot be paid are listed separately **with the reason**.
3. **Tick** a whole supplier or single invoices inside it. The footer totals your selection as you go.
4. **Advice Options** (optional) — mode of payment, bank account, approver, cost centre, remarks, submit or not. Applied to the whole batch.
5. **Create Advices** — you confirm a count and a total first. Drafts by default. Over 15 suppliers the work moves to the background and chimes when finished. The result panel links every advice and lists anything skipped.

### 7.2.1 From the Purchase Invoice list

Tick invoices, then **Actions → Create Payment Advice (by supplier)**. They are grouped by supplier and one draft advice is raised for each. Anything already on a live advice is skipped and named. All ticked invoices must belong to one company.

### 7.3 Approval

```
Draft --Send for Approval--> Pending Approval --Approve--> Approved (submitted)
                                    \--Reject--> Rejected --> Pending Approval
```

| Action | From → To | Who | Needs |
|---|---|---|---|
| Send for Approval | Draft → Pending Approval | Accounts User | — |
| Approve | Pending Approval → Approved | Finance Manager | An attachment |
| Reject | Pending Approval → Rejected | Finance Manager | A comment |
| Send for Approval | Rejected → Pending Approval | Accounts User | — |

A reminder goes out after 3 days and escalates after 7. Whoever prepares an advice cannot approve it. While the workflow is active it — not the Approver field — decides who may submit, and scheduled runs stop at drafts so approvers stay in control.

**Without a workflow**, only the user linked to the Approver Employee may submit. A System Manager can release a stuck advice.

### 7.4 Creating the Payment Entry

On a submitted advice press **Create Payment Entry**. The allocations become the entry's references and ERPNext works out base amounts, party balance and anything unallocated.

| Event | Effect on the advice |
|---|---|
| Payment Entry submitted | Stamped with the entry and date; status becomes **Paid** or **Partly Paid**; every reference row refreshes |
| Payment Entry cancelled | Stamp cleared, advice back to **Approved**, rows refreshed, so a corrected entry can be raised |
| Advice cancelled | Blocked while its Payment Entry is still submitted. Cancel the entry first |

Two submitted Payment Entries can never claim the same advice, and each invoice shows its advice under **Connections**.

### 7.5 Scheduled runs

One Payment Automation Settings record per company and party type. The form states the plan in words, for example *"Will create advices → submit advices on Mon, Tue at 07:00"*. Set the weekdays and the time; the run fires on the first scheduler tick at or after that time, once a day.

- **Dry Run** works out exactly what would happen and reports it without creating anything.
- **Run Now** ignores the schedule and runs immediately.

Every run reports through the chime, the desk bell, and email where an outgoing Email Account exists.

### 7.5.1 Guards and thresholds

| Setting | What it does |
|---|---|
| Due date offset | Include invoices due within N days. 0 means due today or earlier |
| Minimum amount | Skip a supplier below this total — keeps rounding scraps out |
| Ageing over | Only invoices more than N days past due |
| Max parties per run | A hard cap, so a wrong filter cannot raise hundreds of advices |
| Advice threshold | Skip a supplier whose total would go above this |
| Submit threshold | Above this, advices stay drafts even with auto-submit on |
| Payment Entry threshold | Above this, Payment Entries stay drafts |
| Exclude foreign currency | Skip suppliers with invoices outside the company currency |
| Ignore hold / blocked | Off (recommended) means on-hold suppliers are skipped |

A single supplier can be kept out of every run by ticking **Disable Automatic Payment** on the Supplier.

### 7.5.2 Statuses

| Status | Meaning |
|---|---|
| Draft | Being prepared |
| Pending Approval | Approver chosen, not yet submitted |
| Approved | Submitted, no Payment Entry yet |
| Partly Paid | A Payment Entry covers part of it |
| Paid | Fully covered |
| Cancelled | Withdrawn |

The list is colour-coded, marks scheduler-raised advices with an *auto* pill, and has an **Awaiting Payment Entry** button for the approved-but-unpaid queue.

### 7.6 Why a party was skipped

| Message | Meaning and fix |
|---|---|
| No default payable account | Set a payable account on the Supplier or the Company |
| Already allocated on a live Payment Advice | Open that advice, or cancel it to free the invoices |
| Below the minimum advice total | Rounding scraps — lower the minimum to include it |
| Party is on hold | Release the supplier, or tick "Include on-hold parties" |
| Party is disabled | Re-enable the supplier |
| Automation disabled on the party | **Disable Automatic Payment** is ticked on the Supplier |
| Over the per-run cap | It comes next run, or raise Max Parties Per Run |
| Advices left as drafts — a workflow governs approval | This is intended: approvers submit, not the scheduler |

---

## 8. Scheduled jobs

Two jobs run on their own. Both live in this app.

| Job | When | What it does |
|---|---|---|
| `overdue_notifications.notify_overdue_invoices` | Daily | Sends the overdue digest — desk bell, banner, and email where an outgoing Email Account exists |
| `payment_automation.run_due_automations` | Every scheduler tick | Looks at each Payment Automation Settings record and runs the ones whose weekday and time have arrived. It fences itself with the last execution time so one run cannot happen twice |

**How to check the scheduler is alive**

1. Search `Scheduled Job Type` and find the job by name.
2. Look at **Last Execution**. If it is old, the scheduler itself is paused.
3. Search `Scheduled Job Log` for failures.

**If nothing fires** — see 9.7.

---

## 9. Troubleshooting

Grouped by what you are looking at. Search the exact message if you have one.

### 9.1 Permissions and visibility

**A branch's users cannot see the warehouses, cost centres or payment modes they should.**
Open that branch's Branch Configuration. Check the row exists, and that `is_default_branch` is ticked on the user row if it should be their default. Save again to re-apply permissions.

**A user sees data from another branch.**
The same user is listed on more than one Branch Configuration, or has `is_default_branch` ticked in two places. Only one may be default.

**Removing a warehouse from a branch did not take the permission away.**
Another Branch Configuration still grants it to that user. Permissions are only revoked when no other record grants them.

**"At least one Branch must be added in Branch Access when a Credit Limit is set."**
Add a row to the customer's Branch Access grid, or save the credit limit as a user who belongs to the intended branch and let it fill itself.

**"No Credit Limit" when picking a customer for a credit invoice.**
The customer has no Customer Credit Limit row for this invoice's company. Add one on the Customer.

**A customer is in the wrong customer group.**
Groups here follow two rules: a credit-limit company set means **Credit Customer**; a VAT registration number with no credit-limit company means **Company**. Customers with neither are left alone.

### 9.2 Printing and PDF

**A statement prints with no header or footer.**
The print wrapper only draws the letter head when "With Letter head" is ticked, and only draws the footer band when "Repeat Header and Footer" is ticked as well. The statement layouts draw their own artwork when you have not picked a letter head, so both routes match. If you still get nothing, check the site has a Letter Head marked default with images in its header and footer.

**A change to a print format file did nothing.**
The live copy is the **record in the database**, not the file. Somebody has to load the file into the Print Format record. Check by comparing the two.

**A company's invoices print with the wrong layout.**
Add or fix the row for that document type on the Company's Print Formats grid.

**The Print DN button says no format is set.**
Set `custom_delivery_note_print_format` on the Company. It is a separate field from the grid.

**The statement shows the wrong customer, or several.**
Put exactly one customer in the report's Party filter.

### 9.3 Approvals and workflow

Approvals are run by **Permission Manager**, not this app. Look there first.

**A document cannot be submitted and the message mentions approval.**
It is sitting in a state that does not submit. Use the workflow action instead of the Submit button.

**Journal Entries cannot be submitted at all.**
The submit guard covers Journal Entry. It needs an active workflow for that doctype on the site. If the site has none, the guard has nothing to check against — this is a Permission Manager matter, not a data problem.

**Stock Entries pile up in Pending Acceptance.**
Only Stock Manager can act on that state. This is deliberate. Give the role, or have a Stock Manager clear the queue.

**A document is stuck with no available action.**
Check the workflow's transitions for that state. A state with no outgoing action strands whatever is in it.

**Approval reminders never arrive.**
The workflows carry an escalation period but no escalation email address. Set one on the workflow.

### 9.4 Stock and valuation

**Cost of Goods Sold keeps getting small postings from Purchase Receipts.**
This is ERPNext, not a mistake in the data. When quantity times rate does not divide exactly into the valuation, the difference — usually a few fils — is posted to the company's **Default Expense Account**, which on this site is the COGS account. It will keep happening on every receipt.

Two ways to stop it: point Default Expense Account at a rounding or stock adjustment account, or accept it. Before changing it, check what else uses that company default.

**"Cannot save: insufficient warehouse stock for …"**
The quantity is more than the warehouse holds. Reduce it, change warehouse, or remove the row.

**Items show a value but no quantity.**
Stranded valuation, usually left over from a migration. A Stock Reconciliation with the quantity and rate set to zero clears it, and the write-off should go to the Stock Adjustment account — not COGS.

**A reorder suggestion looks far too high.**
Check the **Busiest Day** and **Variability** columns. One large sale in the window raises safety stock for the whole item. Drop the service level to 85%, or shorten the window.

### 9.5 Supplier payments

| Symptom | Cause and fix |
|---|---|
| Bank, IBAN or SWIFT blank on the advice | The supplier has no Bank Account record. Create one and the details fetch themselves |
| "Payment Amount exceeds the total payable" | You authorised more than the references total. Fetch more invoices or lower the amount |
| Reference picker empty | Set Company first — the picker is scoped to it, and to submitted documents |
| "Cancel Payment Entry … before cancelling this advice" | Cancel the Payment Entry first |
| No chime after a run | Click once anywhere in the page per session; browsers block sound until you interact |
| No email summary | No outgoing Email Account is set up. The chime and bell still work |
| A scheduled run never fires | Check Enabled, the weekday ticks, the time, and that step 1 is on |

### 9.6 Reports

**A report is empty.**
Company is almost always the reason. Set it, then widen the dates.

**A report is enormous or slow.**
Narrow the warehouse, item group or date range. Reports that cap their rows say so on the report itself, and the totals above still count everything.

**Two reports disagree on a total.**
Check whether one of them excludes internal transfers and the other does not. On this site transfers between warehouses and between own bank accounts are large enough to swing a total on their own.

**A figure does not match the Trial Balance.**
The cash flow summary is built to tie: its closing balance equals the Cash and Bank account balances on the To Date. If it does not, the date range or the account filter is different from the one you are comparing against.

### 9.7 Scheduled jobs

**Nothing automatic is happening at all.**
Check the scheduler is not paused, then look at Last Execution on the Scheduled Job Type.

**One job fails every time.**
Open Scheduled Job Log and read the failure. Errors also land in Error Log.

**A job ran twice.**
The payment automation fences itself with the last execution time, so this should not happen. If it did, note the times and treat it as a defect worth reporting.

---

## 10. Admin quick reference

### Screens

| Screen | Path or name |
|---|---|
| Branch Configuration | Awesomebar → Branch Configuration |
| Inter Company Branch | Awesomebar → Inter Company Branch |
| Payment Automation Settings | Awesomebar → Payment Automation Settings |
| Payment Advice | Awesomebar → Payment Advice |
| Payment Advice Builder | `/app/payment-advice-builder` |
| Business Dashboard | `/app/business-dashboard` |
| This handbook, in the desk | Awesomebar → SF Trading User Guide |
| This handbook, in the browser | `/user-guide` |

### Doctypes this app adds

`Branch Configuration` (with Warehouse, Cost Center, Mode of Payment and User child tables) · `Customer Branch Access` · `Inter Company Branch` (with Cost Center child table) · `Company Print Format` · `Payment Advice` (with Reference child table) · `Payment Automation Settings` (with Notify Role child table)

### Things this app replaces or extends

| What | Effect |
|---|---|
| ERPNext item search | Replaced, to show stock and rate next to each result |
| Sales Invoice controller | Extended by this app |
| Activity Log | Gains the impersonation reason |
| Company, Customer, Supplier, Item and several transactions | Gain custom fields, shipped as fixtures |

### After changing configuration

| You changed | Then do this |
|---|---|
| Branch Configuration | Save again; permissions re-apply on save |
| A print format file | Load the file into the Print Format record |
| Company Print Format grid | Nothing; it takes effect on the next print |
| Payment Automation Settings | Run a Dry Run and read the summary |
| A custom field or fixture in the app | Ask for a migrate in the maintenance window |
| Anything in the app's Python code | Ask for a worker restart |
