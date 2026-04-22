# Van Sale — Roadmap

## Status legend

- ✅ Shipped
- 🟡 In progress / partial
- 🔵 Next up (committed)
- ⚪ Planned (later)

---

## ✅ Shipped

| Area | What |
|---|---|
| Auth | Email+PW login, PIN unlock, stable `api_secret`, offline PIN hash |
| Offline | IDB queue, ordered drain, signature/photo uploader, `ApiError`/network split |
| Sales | Invoice create + submit, Payment Entry, dashboard tiles, idempotent `client_id` |
| Scoping | Vansale Configuration → User Permissions (Company / Warehouse / Cost Center) + `Van User` role + list-view filters + before-validate cost-center guard |
| Routing | Van Customer Assignment page (day-wise table, driver dropdown, reassign flow, auto-assign `before_insert` hook w/ cached module-active check + site_config opt-out) |
| Routing | Van Driver Roster page (day-wise grouped read-only viewer, in workspace) |
| Deploy | PWA pipeline; Capacitor scripts (keystore + build-customer + gradle patch) |
| Admin | Workspace, `admin.set_user_password` helper, testing checklist |

---

## 🔵 Committed roadmap (current focus)

### 1. Offline hardening

- [ ] Extend IDB queue coverage — every mutation path (Customer create, Payment Entry, Sales Return, Stock Entry, visit logs) must queue cleanly when offline
- [ ] Conflict resolution — server rejects replay → surface reason to user, let them retry/edit/discard
- [ ] Drain observability — "N pending" badge on dashboard + drawer listing each queued op w/ age + last error
- [ ] Long-offline resilience — auto-drain retries with exponential backoff, cap on queue size, purge-with-confirm for orphaned rows
- [ ] Unit tests for `offline/*.ts` processors (happy path + server-rejection path + network-loss mid-drain)
- [ ] Server idempotency tests (`client_id` dedup guarantees across Sales Invoice, Payment Entry, Visit Log)

### 2. ZATCA offline sync

- [ ] Stamp every queued Sales Invoice w/ ZATCA-required fields at CREATE time (not submit) — UUID, invoice_hash precursors, cryptographic stamp inputs staged client-side
- [ ] Offline QR generation — TLV fields computable locally, embed in print without waiting for server
- [ ] On drain, server re-signs + replaces the preliminary QR with ZATCA-authorized one; printer gets updated copy for re-print if invoice pulled up later
- [ ] Reconcile `zatca_integration` app hook chain with our `custom_client_id` field — verify no hook override breaks signing order
- [ ] Failure mode: ZATCA reporting endpoint rejects a batched invoice → mark invoice w/ `zatca_status=rejected` + error + retry UI

### 3. Reports (driver + manager)

- [ ] **Daily Closing Sheet** — per-driver EOD — collections (cash + card breakdown), sales (invoice count + total), returns (count + value), cash-on-hand reconciled vs expected, signature capture, print
- [ ] **Stock Reconciliation EOD** — van start stock (from van start snapshot) vs van end stock (from stock ledger - sold - returned) → variance report per item, flag shrinkage > threshold
- [ ] **Commission Report per Sales Person** — filter by date range, group by sales person, columns: invoices, gross sales, returns, net sales, commission rate, commission amount. Source of truth = Sales Invoice `Sales Team` child (already populated by auto-assign hook)

### 4. Bluetooth thermal printer direct print

- [ ] Replace Android print-dialog path with direct ESC/POS over `@capacitor-community/bluetooth-le` (already installed)
- [ ] Printer discovery + pairing UI in Settings (list discovered devices, save last-used MAC to localStorage)
- [ ] ESC/POS command builder (header, item lines w/ qty × rate × amount, totals, tax breakdown, QR for ZATCA, signature image, footer)
- [ ] Auto-print on invoice submit + payment entry (configurable toggle)
- [ ] Retry + fallback — if print fails, keep invoice submitted, surface "Reprint" action on invoice detail
- [ ] Paper width variants — 58mm + 80mm

### 5. Sales Return UI

- [ ] Return flow entry point — from Invoice detail view → "Return items" button
- [ ] Pick-items-from-invoice screen — list original invoice lines w/ original qty + return qty input (default 0, max = original)
- [ ] Reason dropdown per line (damaged / expired / wrong item / customer refusal / other) + free-text note
- [ ] Auto-post Sales Invoice w/ `is_return=1`, negative amounts, linked `return_against` — server already supports; UI wires it up
- [ ] Offline-safe — queue return via same `client_id` idempotency as regular invoice
- [ ] Return receipt print (BT thermal once item 4 lands)
- [ ] List view — "Returns" tab in dashboard showing recent returns w/ status

### 6. PDF invoice download

- [ ] Server endpoint `vansale.api.invoice.pdf(invoice_name)` — renders ERPNext standard Sales Invoice print format → PDF bytes
- [ ] Client: Filesystem plugin (Capacitor) writes PDF to Documents/Vansale/ + opens share sheet
- [ ] Web fallback — browser triggers download via blob URL
- [ ] Cache last 20 PDFs locally for offline re-view
- [ ] "Download PDF" button on invoice detail view

### 7. Price list in Vansale Configuration

- [ ] Add `price_list` Link field to Vansale Configuration (default blank → fallback to `Item.standard_rate` current behavior)
- [ ] Boot payload exposes `price_list` + bundled `Item Price` rows for items in van's warehouse (cached per config)
- [ ] InvoiceForm item-rate lookup priority:  `Vansale Configuration.price_list` Item Price → else `Item.standard_rate`
- [ ] UI shows price source subtle pill ("Configured" vs "Default") on item line
- [ ] Price list respects validity dates (`valid_from` / `valid_upto`)
- [ ] Offline — item prices pre-downloaded during boot/sync; no network needed on invoice create

### 8. UI redesign (proposal — awaiting approval)

One PR per phase, keep data layer untouched (`api/*`, `offline/*`, `stores/*`).

- [ ] **Design tokens + brand accent** — color scale, shadows, radii, motion tokens
- [ ] **Icon set** — 24×24 stroke 1.75 currentColor, `Icon.vue` pattern mirrored from fatehhr
- [ ] **Bottom nav bar** — 5 icons: Home / Route / Sales / Stock / More (replaces dashboard grid)
- [ ] **Skeleton loaders + proper empty states + toast notifications** — replace "Loading…" text + inline messages
- [ ] **Typography scale** — 12 / 14 / 16 / 20 / 24, system-font stack

---

## ⚪ Out of scope for this roadmap

(Previously planned — parked for later review once the 8 items above ship.)

- Route planning frontend end-to-end (stop detail, navigate, map view, drag reorder, notifications)
- Barcode scan wire-up, Van stock transfer UI, Customer address picker w/ GPS
- Discounts + free-item promos
- Arabic/RTL smoke pass (tokens landing first)
- Playwright E2E offline → drain
- Multi-van dashboard, trip sheet, expense claims (HRMS)
- `~/.claude/skills/vansale/SKILL.md` agent-context mirror

---

## Out of scope (permanent)

- Native iOS build (Android-only target)
- Multi-tenant / multi-company per van user
- Complex tax rules beyond ERPNext default engine
- Real-time chat driver ↔ manager
- Marketing / promotions / loyalty
