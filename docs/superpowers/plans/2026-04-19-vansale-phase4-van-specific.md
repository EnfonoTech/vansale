# Van Sale — Phase 4: Van-Specific Features — Implementation Plan

> REQUIRED SUB-SKILL: superpowers:subagent-driven-development / superpowers:executing-plans.
>
> **Inherits:** Phase 1–3 infrastructure. Adds the pieces that make this a *van sales* app, not a generic sales PWA.

**Goal:** Van/truck stock ledger, visit-route planning + check-in, barcode scanning, signature on delivery, GPS breadcrumb, ESC/POS Bluetooth receipt printing. Each feature is offline-capable by reusing the Phase 2 sync spine.

**Architecture:** Two new doctypes (`Van Stock Ledger`, `Van Route Plan`) + a `Van Visit` log. Frontend adds `src/features/van/*` modules: route, van-stock, visit, printing, gps. Capacitor plugins lazy-loaded only on native (§3.4 static-imports rule — declare in `frontend/package.json`, gate at runtime).

**Tech additions:** `@capacitor-mlkit/barcode-scanning` (native), `@capacitor-community/bluetooth-le` (native), ESC/POS command generator (pure JS), `@capacitor/geolocation`. Canvas-based signature reused from Phase 2.

---

## Doctypes introduced

| Doctype | Key fields | Purpose |
|---|---|---|
| `Van Stock Ledger` | van (Link → Warehouse), item, qty_on_van, last_sync, client_id | Truck-local inventory, separate from main warehouse |
| `Van Route Plan` | user, date, stops[] (Table: customer, planned_time, status, actual_in_iso, actual_out_iso, sig_file) | Daily plan for a salesperson |
| `Van Visit Log` | route (Link → Van Route Plan), customer, started_at, ended_at, lat, lng, invoice_created (Link → Sales Invoice), signature_file, notes | Per-stop audit row |
| `Van Stock Transfer` | from_warehouse, to_van, items[], transferred_at | Replenishment from main warehouse to van |

All datetime fields returned UTC-ISO (§Phase 2 rule).

---

## Tasks

### Task 1 — Van Stock Ledger

- [ ] DocType + child table `Van Stock Ledger Item`.
- [ ] API `vansale/api/van_stock.py` — `list_mine(van?)`, `detail(van)`, `transfer_in(from_warehouse, items[])`, `adjust(item, delta, reason)`.
- [ ] Server triggers on Sales Invoice submit: if `update_stock=1` AND invoice's `set_warehouse` points at a van warehouse, decrement Van Stock Ledger Item atomically.
- [ ] Frontend: `VanStockView.vue` (quick list), `VanStockTransferView.vue`.
- [ ] **Commit** `feat(van-stock): ledger + transfer flow`.

### Task 2 — Route plan + visits

- [ ] DocType `Van Route Plan` + child `Van Route Stop`. Index by `(user, date)` for quick list.
- [ ] API `vansale/api/route.py` — `today()` (list stops for today for logged-in user), `start_visit(stop)`, `end_visit(stop, invoice?, payment?, signature?, notes?)`, `create_plan(date, stops[])` (manager flow, optional in P4).
- [ ] Frontend: `RouteTodayView.vue`, `RouteVisitView.vue` (check-in, capture signature, link the just-created invoice from Phase 3, tap End → writes visit log).
- [ ] Offline: visit_queue processor.
- [ ] **Commit** `feat(route): today's plan + visit lifecycle`.

### Task 3 — GPS breadcrumb

- [ ] `@capacitor/geolocation` added to `frontend/package.json` AND `android-capacitor/package.json` (§3.9 pitfall — easy to forget the android-capacitor side).
- [ ] `src/features/van/gps.ts` — polls every 60s while a visit is active; stores breadcrumbs in `gps_queue`; drains with visit batch.
- [ ] Server-side: optional `Van GPS Breadcrumb` doctype (or stash raw list on the visit log as JSON) — choose based on demo customer preference, default to JSON blob to keep DB tidy.
- [ ] **Commit** `feat(gps): breadcrumb trail per visit`.

### Task 4 — Barcode scanning

- [ ] Install `@capacitor-mlkit/barcode-scanning` in BOTH frontend and android-capacitor, then `npx cap sync android` (§3.9 — the sync step is mandatory).
- [ ] `src/features/van/scanner.ts` — wrapper with `async scan(): Promise<string>` that falls back on web to a manual-entry modal.
- [ ] Wire into InvoiceFormView (scan to add item), SalesReturnFormView (scan to find item on original invoice), VanStockView (scan adjust).
- [ ] Android manifest: `<uses-permission android:name="android.permission.CAMERA" />` already present from P5 setup.
- [ ] **Commit** `feat(scan): barcode entry for items`.

### Task 5 — Signature on delivery

- [ ] Reuse `SignaturePad.vue` from Phase 2. Wire into RouteVisitView "End visit" flow; signature blob queued + uploaded via the same ONE-uploader path as photos.
- [ ] Stored on `Van Visit Log.signature_file` via file-upload endpoint (§Phase 2 Task 2).
- [ ] **Commit** `feat(signature): delivery signature capture`.

### Task 6 — Bluetooth receipt printing

- [ ] Install `@capacitor-community/bluetooth-le` (both frontend + android-capacitor, + `npx cap sync android`).
- [ ] `src/features/van/printer.ts` — discover paired printer (stored preference), build ESC/POS payload (company header, invoice table, totals, QR of invoice PDF URL, customer name, TRN, date), send as raw chunks.
- [ ] `ReceiptPrintView.vue` — launched from invoice detail and payment detail. Web fallback = browser print.
- [ ] Permissions: `BLUETOOTH_CONNECT`, `BLUETOOTH_SCAN` in AndroidManifest.
- [ ] **Commit** `feat(print): Bluetooth ESC/POS receipt printer`.

### Task 7 — Offline pricing + tax drift for van stock

- [ ] Extend Phase 3 price snapshot: if a sold item is currently on the van (`Van Stock Ledger.qty_on_van > 0`), use the van ledger's price snapshot instead of the live price list, so customers get the quote-at-load rate.
- [ ] **Commit** `feat(pricing): van-stock price snapshot overrides live price list`.

### Task 8 — Manager / ops views (lightweight)

- [ ] `VanDailyReportView.vue` — end-of-day report: total visits, sales, collections, returns, route map (static image or OpenLayers). Manager-only role check on server.
- [ ] **Commit** `feat(ops): daily van report`.

### Task 9 — Tests + QA

- [ ] Full flow: plan 5 stops → run route offline with WiFi on the van → 1 return + 4 sales + 4 signatures + 4 receipts printed → reopen next morning → drain to server → daily report matches.
- [ ] **Commit** `test: van route e2e coverage`.

### Task 10 — Handoff

- [ ] Update `docs/AGENT_HANDOFF.md` with van-specific doctypes + permissions matrix.
- [ ] Update `docs/LESSONS_LEARNED.md` with any new gotchas (Bluetooth pairing quirks, GPS accuracy tuning, MLKit scanner permission dialog timing).
- [ ] **Commit** `docs: phase 4 handoff`.

---

## Exit criteria

- A salesperson can run an entire day's route fully offline and sync clean at end of day.
- All van-specific features degrade gracefully on web (barcode → manual entry, printer → browser print, GPS → silent no-op) — same source tree.
- No Capacitor plugin is added without the android-capacitor pnpm-add + cap-sync ritual (§3.9).
