# Van Sale — Roadmap

## Status legend

- ✅ Shipped
- 🟡 In progress / partial
- 🔵 Next up
- ⚪ Planned

---

## ✅ Shipped (Phase 1–5 + Van User pattern)

| Area | What |
|---|---|
| Auth | Email+PW login, PIN unlock, stable `api_secret`, offline PIN hash |
| Offline | IDB queue, ordered drain, signature/photo uploader, `ApiError`/network split |
| Sales | Invoice create + submit, Payment Entry, dashboard tiles, idempotent `client_id` |
| Scoping | Vansale Configuration → User Permissions (Company / Warehouse / Cost Center defaults) + `Van User` role + list-view filters + before-validate cost-center guard |
| Deploy | PWA pipeline; Capacitor scripts (keystore + build-customer + gradle patch) |
| Admin | Workspace, `admin.set_user_password` helper, testing checklist |

---

## 🟡 In progress / partial

| Area | Status |
|---|---|
| UI polish | Utilitarian baseline; redesign pass scoped below |
| Arabic / RTL | Locale keys present; not smoke-tested |
| Item search | By name/code works; barcode scan not wired into InvoiceForm |

---

## 🔵 Next up (next session)

### 1. Route planning — proper end-to-end

**Backend (mostly done):**
- `Van Route Plan` + child `Van Route Stop` + `Van Visit Log` DocTypes ✅
- `route.today`, `start_visit`, `end_visit`, `create_plan`, `daily_report` endpoints ✅

**Frontend gaps to close:**
- [ ] **Manager: create today's plan for a van user** — desk form works now, but add a simpler mobile/web workspace shortcut with a single-page planner (pick driver, pick warehouse, add customer stops with planned time)
- [ ] **Driver: RouteTodayView shows the list of stops** ✅ (exists) — add:
  - Tap a stop → opens stop detail with "Navigate" button (open Google Maps at customer address)
  - "Start visit" logs `started_at` + captures GPS
  - From a stop, "New Invoice" pre-fills customer; "Collect Payment" pre-fills customer
  - "End visit" → capture signature + GPS + sync invoice/payment IDs back to the stop
  - Stop status transitions: pending → in_progress → done / skipped
- [ ] **Reorder stops** via drag
- [ ] **Route map view** — all stops pinned on a mini-map (OpenLayers or Leaflet, offline tiles cached)
- [ ] **Daily report view** — read-only summary at end of shift (total visits, sales, collections, returns, missed stops)
- [ ] **Notification** when a stop is scheduled ≤15 min ahead (PWA push / native local notification)

### 2. UI redesign (proposal below — awaiting confirmation)

See **"UI redesign scope"** section.

### 3. First signed APK

- [ ] `scripts/generate-keystore.sh demo`
- [ ] `scripts/build-customer.sh demo` → `dist/vansale-demo-1.0.X.apk`
- [ ] Install + run through this doc's testing checklist
- [ ] Upload to GitHub release

---

## ⚪ Planned

### Domain features
- **Sales Return** UI (backend done — need pick-items-from-invoice flow)
- **PDF download** for Sales Invoice (Filesystem-backed on native)
- **Barcode scan** wired into invoice form (helper exists)
- **Receipt print** over Bluetooth ESC/POS on invoice submit (helper exists)
- **Van stock transfer** UI (main warehouse → van)
- **Customer address picker** with GPS-assisted "nearest customer" hint
- **Price list** per customer (currently uses `Item.standard_rate`)
- **Discounts** + free-item promotions

### Compliance
- **ZATCA** (KSA e-invoice) QR + compliance fields on every submitted Sales Invoice (the `zatca_integration` app is already on `trading` — need to verify our custom_client_id field doesn't break their hook chain)
- **Audit log** for offline events (Vansale Outbox is in place; add a simple report)

### Manager / ops
- **Daily report** view (backend done)
- **Van stock reconciliation** — physical count vs ledger
- **Expense claims** (ERPNext HRMS integration for driver expenses: fuel, tolls, meals)
- **Trip sheet** print-out at end of shift
- **Multi-van dashboard** for fleet managers

### Quality + ops
- **Unit tests** for `offline/*.ts` processors
- **Server tests** for idempotency (re-post same `client_id`, verify dedup)
- **Playwright E2E** for offline → drain → verify
- **`~/.claude/skills/vansale/SKILL.md`** — mirror of the fatehhr skill so future agents inherit context

---

## UI redesign scope (proposal)

Current UI is utility-grade. A focused redesign — not a rewrite — can lift it significantly with limited risk.

### What changes (mobile-first, no layout rewrite of individual forms)

1. **Bottom navigation bar** (5 icons): Home / Route / Sales / Stock / More — replaces the grid of buttons on the dashboard
2. **Design tokens** (already exist; needs a theme pass): add a visual accent (brand gradient on primary), shadow scale, richer neutrals
3. **Icon set** (reuse fatehhr's `Icon.vue` pattern — 24×24 stroke 1.75, currentColor)
4. **Card shadows + density** — tighter cards, bigger tap targets (44px min)
5. **Empty states** — every list has a proper empty illustration + CTA
6. **Loading states** — skeleton shimmers instead of "Loading…"
7. **Toasts** — for save / queue / drain feedback (currently inline messages)
8. **Typography** — adopt a system-font stack with a deliberate scale (12/14/16/20/24)
9. **Arabic / RTL pass** — verify flip on every view
10. **Dashboard hero tile** — combine today's sales + collection into one hero with sparkline (skipped for now — needs a chart lib decision)

### What doesn't change
- Data layer (`api/*`, `offline/*`, `stores/*`)
- Router structure
- API surface

### Delivery approach
- One PR per phase (tokens → icons → bottom nav → empty states → toasts → polish)
- Keep existing views behind the scenes; swap components in-place
- Each phase passes `pnpm type-check` + browser smoke before ship

Confirm the approach + I'll start with tokens + icons (one commit, ~30 mins each).

---

## Out of scope (for now)

- Native iOS build (we target Android only)
- Multi-tenant / multi-company per van user (one van = one company)
- Complex tax rules beyond what ERPNext's default tax engine provides
- Real-time chat between driver and manager
- Marketing features (promotions, campaigns, loyalty)
