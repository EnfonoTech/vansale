# Van Sale — Phase 2: Offline Engine — Implementation Plan

> REQUIRED SUB-SKILL: superpowers:subagent-driven-development / superpowers:executing-plans.
>
> **Source of truth:** `~/.claude/skills/frappe-vue-pwa/SKILL.md` §4 + §5. Do not invent — follow.

**Goal:** Wire the offline-first sync spine — IndexedDB stores, queue, drain engine, photo/signature uploader with the ONE-uploader rule, `online.ts`, UTC-ISO datetime round-trip — so that any domain added in Phase 3 inherits offline behaviour automatically.

**Architecture:** `src/offline/db.ts` (idb schema) + `src/offline/queue.ts` (put/del/getAll) + `src/offline/drain.ts` (drainPhotos → drainInvoices → drainPayments → drainReturns, extensible) + `src/offline/photos.ts` (capturePhoto, resolveToRealUrl — exactly §4.3–§4.4) + `src/app/online.ts` (reactive).

**Tech:** idb, dateutil (server), `@capacitor/network` lazy-loaded when native (real wiring in P5; web-only listener in P2).

**Hard rules (do not violate):**
1. ONE uploader per file (§5 commandment 1).
2. Online path = synchronous, queue only on offline or network failure (#2).
3. Never silently delete user work — `flagOrphans` marks (#3, §4.6).
4. Drain never sends `client_modified` (#6).
5. `ApiError` ≠ network error — re-throw (#5, lesson #2 of fatehhr).
6. Datetimes UTC-ISO with `Z` — both sides use `dateutil.isoparse` server-side, `new Date(iso).toLocaleTimeString()` client-side (fatehhr lessons #7, #9).

---

## Files created

```
frontend/src/
├── offline/
│   ├── db.ts              # openDB schema (photos, signatures, invoice_queue, payment_queue, return_queue, customer_cache, item_cache, price_cache)
│   ├── queue.ts           # generic add/get/update/del wrappers
│   ├── drain.ts           # ordered drain of each queue type; orphan flagging
│   ├── photos.ts          # capturePhoto, resolveToRealUrl (§4.3–§4.4)
│   ├── signatures.ts      # captureSignature (canvas → blob → IDB → upload via resolveToRealUrl)
│   └── processors/
│       ├── invoice.ts     # saveInvoice online path + queue path
│       ├── payment.ts
│       └── return.ts      # (stubs in P2, full in P3)
├── app/
│   └── online.ts          # ref<boolean> with Network.addListener when native
└── components/
    └── PhotoSlot.vue      # force-retake on dead refs (§4.7)

vansale/api/
├── datetime_util.py       # _parse_client_ts (dateutil.isoparse), _naive_site_to_utc_iso
└── file_upload.py         # whitelisted upload endpoint returning /files/... URL

vansale/vansale/doctype/
└── vansale_outbox/        # server-side audit log of drained offline events
```

---

## Tasks

### Task 1 — Datetime helpers (server)

- [ ] **Step 1:** Write `vansale/api/datetime_util.py` — two helpers, direct copy from fatehhr `checkin.py` pattern (§fatehhr lesson §9):

```python
from datetime import datetime, timezone
from dateutil.parser import isoparse
from zoneinfo import ZoneInfo
from frappe.utils import get_system_timezone

def parse_client_ts(ts_str: str) -> datetime:
    dt = isoparse(ts_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(ZoneInfo(get_system_timezone())).replace(tzinfo=None)

def naive_site_to_utc_iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo(get_system_timezone()))
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
```

- [ ] **Step 2:** Unit test `tests/test_datetime_util.py` with fixed tz + DST edge case.
- [ ] **Step 3: Commit** `feat(backend): UTC-ISO datetime helpers (isoparse + naive-to-UTC)`.

### Task 2 — File upload endpoint

- [ ] **Step 1:** Write `vansale/api/file_upload.py` — whitelisted `upload(file, attach_to=None)` returning the saved `/files/...` URL. Use `frappe.get_doc({"doctype": "File", ...}).insert()`. Sanitise filename (`frappe.scrub(...)` or regex `[^A-Za-z0-9._-]+` → `_`).
- [ ] **Step 2: Commit** `feat(backend): file upload endpoint for mobile blobs`.

### Task 3 — `Vansale Outbox` doctype (audit trail)

- [ ] **Step 1:** Write `vansale/doctype/vansale_outbox/vansale_outbox.json` — fields: `event_type (Select: invoice/payment/return/sigcapture)`, `ref_doctype`, `ref_name`, `client_id (data unique)`, `client_ts (datetime)`, `payload_json (long text)`, `drained_at`, `user`, `status (Select: queued/processed/failed)`, `error`.
- [ ] **Step 2: Commit** `feat(backend): Vansale Outbox doctype for drain audit`.

### Task 4 — IndexedDB schema (client)

- [ ] **Step 1:** Write `src/offline/db.ts`:

```ts
import { openDB, type IDBPDatabase } from "idb";

const DB_NAME = "vansale";
const VERSION = 1;

export interface Schema {
  photos: { key: string; value: { id: string; blob: Blob; filename: string; thumb?: string; createdAt: number } };
  signatures: { key: string; value: { id: string; blob: Blob; createdAt: number } };
  invoice_queue: { key: number; value: QueuedInvoice; indexes: { by_customer: string } };
  payment_queue: { key: number; value: QueuedPayment };
  return_queue: { key: number; value: QueuedReturn };
  customer_cache: { key: string; value: CachedCustomer };
  item_cache: { key: string; value: CachedItem };
  price_cache: { key: string; value: CachedPrice };
  kv: { key: string; value: unknown };
}

export async function db(): Promise<IDBPDatabase<Schema>> { /* ... openDB with upgrade */ }
```

- [ ] **Step 2:** Implement `openDB` with `upgrade` creating object stores + indexes.
- [ ] **Step 3:** Unit test round-trip with fake-indexeddb.
- [ ] **Step 4: Commit** `feat(frontend): IndexedDB schema v1`.

### Task 5 — Queue helpers

- [ ] **Step 1:** Write `src/offline/queue.ts` — generic `addEntry(store, payload)`, `getAll(store)`, `updateEntry`, `deleteEntry`, `countPending(store)`.
- [ ] **Step 2:** Unit tests for each.
- [ ] **Step 3: Commit** `feat(frontend): generic offline queue helpers`.

### Task 6 — Online state

- [ ] **Step 1:** Write `src/app/online.ts` per `frappe-vue-pwa` §3.8. `Network.addListener` is wrapped in `try { await import("@capacitor/network") }` — in P2 the Capacitor plugin isn't installed, so the catch drops to `window.addEventListener("online"/"offline")`. Full native wiring in P5.
- [ ] **Step 2:** Unit test with mocked `navigator.onLine` transitions.
- [ ] **Step 3: Commit** `feat(frontend): reactive online state (web listeners in P2, Network plugin in P5)`.

### Task 7 — Photo + signature capture (ONE uploader rule)

- [ ] **Step 1:** Write `src/offline/photos.ts` — `capturePhoto(file)` + `resolveToRealUrl` exactly as §4.3–§4.4. **No background upload inside capturePhoto.**
- [ ] **Step 2:** Write `src/offline/signatures.ts` — same shape for canvas-produced signature blobs.
- [ ] **Step 3:** Write `src/components/PhotoSlot.vue` per §4.7 (auto-clear on missing blob).
- [ ] **Step 4:** Write `src/components/SignaturePad.vue` — canvas, touch-draw, emits blob. Reuses PhotoSlot's orphan-handling idiom.
- [ ] **Step 5:** Unit tests: create blob → resolveToRealUrl uploads → queue entry rewritten → blob deleted.
- [ ] **Step 6: Commit** `feat(frontend): photo + signature capture with ONE-uploader rule`.

### Task 8 — Drain engine

- [ ] **Step 1:** Write `src/offline/drain.ts`:
  - `drainPhotos()` uploads all pending photos, rewrites queue `photo:<id>` → real URL, deletes the IDB row.
  - `drainQueue(storeName, processor)` — for each entry where no `photo:*` placeholder remains, call `processor(entry)`. On `ApiError` classed as unrecoverable (narrow regex: `row .* not found | locked by | already submitted`), mark `attempts ≥ 1, lastError = message`. On network error, increment attempts, schedule retry.
  - `drainAll()` — order: photos → invoices → payments → returns.
  - `flagOrphans()` (§4.6) — never delete user work; tag and surface.
- [ ] **Step 2:** Unit tests with a fake processor covering: happy path, unrecoverable, network retry, orphan tagging.
- [ ] **Step 3: Commit** `feat(frontend): ordered drain engine + orphan flagging`.

### Task 9 — Sync store + background drain

- [ ] **Step 1:** Write `src/stores/sync.ts` (Pinia) — holds `pendingCount`, `lastDrainAt`, `lastError`. Methods: `refreshCounts()`, `requestBackgroundSync()` (calls `drainAll()` if online and not already draining; debounced 1s).
- [ ] **Step 2:** Wire into `App.vue`: on `online.ts` → true edge, call `requestBackgroundSync()`.
- [ ] **Step 3:** Small `SyncBadge.vue` for the top-bar (shows pending count + tap → SyncErrorsView).
- [ ] **Step 4:** Write `src/views/SyncErrorsView.vue` — list entries with `lastError`, show RETRY and DISMISS buttons (§4.6: DISMISS sets `attempts = 99`; never silently wipes).
- [ ] **Step 5: Commit** `feat(frontend): sync store + badge + errors view`.

### Task 10 — Processor template (golden saveInvoice)

- [ ] **Step 1:** Write `src/offline/processors/invoice.ts` implementing the §4.2 template (online synchronous path, effectiveImages threading, queue dedup on `(customerName, clientId)`, re-throw `ApiError`). Processor function exported to `drain.ts`. In P2 the API call is a placeholder (`vansale.api.invoice.save_draft`); real endpoint in P3.
- [ ] **Step 2:** Write stubs `payment.ts`, `return.ts` — same shape.
- [ ] **Step 3:** Integration test: offline → saveInvoice queues → come online → drain succeeds → queue empty → sync store pendingCount = 0.
- [ ] **Step 4: Commit** `feat(frontend): processor template + drain integration`.

### Task 11 — UTC-ISO round-trip verification

- [ ] **Step 1:** Add `datetime_test_device_utc.py` server test that submits a UTC-ISO timestamp for a queued invoice, verifies it stores in site tz, round-trips to `_naive_site_to_utc_iso` identical.
- [ ] **Step 2:** Add frontend test: `new Date(utcIso).toLocaleTimeString()` produces device-local when given a UTC-ISO string.
- [ ] **Step 3: Commit** `test: UTC-ISO round-trip across device/site timezones`.

### Task 12 — Docs

- [ ] **Step 1:** Update `docs/LESSONS_LEARNED.md` with "Phase 2 — offline engine installed; see `frappe-vue-pwa` §4 for all rules."
- [ ] **Step 2:** Update `docs/AGENT_HANDOFF.md` with the drain-order invariants.
- [ ] **Step 3: Commit** `docs: phase 2 lessons + handoff update`.

---

## Exit criteria

- `pnpm test` passes with ≥80% coverage on `offline/`.
- Manual smoke: kill network → create invoice → restore network → drain runs → queue empty, outbox row created on server.
- `src/offline/` is generic (no domain-specific logic leaks into drain.ts; processors are the only place with domain knowledge).
