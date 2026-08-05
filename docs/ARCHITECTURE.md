# Architecture

How Van Sale is put together, and why it is put together that way. Read this
before changing anything in `vansale/api/` or `frontend/src/offline/`.

For the field-by-field settings reference see [`userguide/`](userguide/index.html).
For endpoints, DocTypes and hooks see [`reference/`](reference/) — those are
generated from source by `scripts/gen-docs.py`.

---

## 1. Shape of the thing

One Frappe app containing both halves:

```
vansale/            Frappe app (Python) — DocTypes, whitelisted API, hooks
frontend/           Vue 3 SPA — the single source for web PWA and Android APK
android-capacitor/  Capacitor shell; src/ is a SYMLINK to ../frontend/src
scripts/            build, version bump, per-customer assets, docs generator
customers/          per-customer .env + artwork
docs/               this
```

`android-capacitor/src → ../frontend/src` is a symlink, not a copy. One edit
reaches both targets; there is no "port it to the app" step, and there must
never be a second copy of a view.

Two build targets from that one tree:

| Target | Base path | Served by | API base |
| --- | --- | --- | --- |
| Web PWA | `/assets/vansale/spa/` | Frappe, via `website_redirects` on `/vansale` | relative — same host |
| Android APK | `./` | Capacitor WebView (local files) | absolute, chosen at runtime |

The consequence that trips people: on native there is no same-origin host, so
**every** request needs an absolute base and a token — see §3.

---

## 2. Why the app owns endpoints instead of using `frappe.client.*`

The SPA never talks to generic Frappe CRUD. Every write goes through a
purpose-built whitelisted endpoint in `vansale/api/`. Three reasons, all learned
the hard way:

1. **Idempotency.** Every mutation carries a client-generated `client_id` UUID.
   The endpoint checks `Vansale Outbox` for that key first and returns the
   existing document instead of creating a second one. A phone that retries a
   half-sent invoice must not double-bill the customer.
2. **Scoping.** A Van User may only see their own customers and their own van's
   stock. Generic CRUD would need that enforced by permission rules alone; the
   endpoints scope every query explicitly and are far easier to reason about.
3. **`frappe.client.submit` is unsafe for this.** It rebuilds the document from
   whatever dict the client posts, so a `{doctype, name}` payload raises
   `TimestampMismatchError` — and if that check ever passed it would blank every
   field the payload omitted. `vansale.api.invoice.submit_draft` loads by name
   instead. Do not reintroduce `frappe.client.submit`.

`frappe.client.delete` is still used for draft deletion, which is safe: it takes
`doctype` + `name` and does not reconstruct the document.

---

## 3. Auth

Two mechanisms, one code path.

| Client | Mechanism | Why |
| --- | --- | --- |
| Web PWA | Frappe session cookie + CSRF header | Served from the site; cookies work |
| Android APK | `Authorization: token <api_key>:<api_secret>` | No shared cookie jar with the site |

`vansale.api.auth.login` authenticates and returns a **stable** `api_key` /
`api_secret` pair (`vansale/utils/secrets.py`). Stable is the operative word:
regenerating the secret on every login invalidates the token on every other
device that user has. Issue once, reuse forever.

`login_with_pin` exchanges a 4-digit PIN for the same pair, so the APK can
re-authenticate after an idle window without asking for the password. The PIN is
bcrypt-hashed in `Vansale Pin.pin_hash`, a `Password` field — read it with
`doc.get_password("pin_hash")`, never `doc.pin_hash`, which returns the 60-asterisk
mask and sends `bcrypt.checkpw` into `Invalid salt`.

Password login happens **once per install**. After that the token persists until
uninstall, and PIN unlock is a local gate, not a new login.

### Runtime server address

The APK asks for its server on first run rather than baking one in at build
time. Stored in **both** localStorage and Capacitor Preferences, with the module
cache seeded synchronously at import — because `loadSiteUrl()` runs before
`app.mount()`, and the Capacitor bridge has not necessarily injected
`window.Capacitor` that early. Gate a pre-mount storage read on `isNative()` and
a configured app bounces to the setup screen on every cold start.

Full pattern: `~/.claude/skills/frappe-vue-pwa/references/runtime-site-switching.md`.

---

## 4. Offline queue

The cardinal rule: **the online happy path is not queued.** The queue exists for
offline only. Every mutation tries the network first; only a `NetworkError`
falls through to the queue. An `ApiError` — the server said no — is re-thrown so
the driver sees the validation message immediately.

```
frontend/src/offline/
  db.ts            IndexedDB stores, one per entity
  queue.ts         enqueue / dequeue, capacity caps
  drain.ts         drain engine, ordering, backoff
  classify.ts      failure -> actionable category
  processors/      one per entity: invoice, payment, return, customer,
                   stock_entry, visit
  capacity.ts      per-store caps so a stuck queue cannot fill the device
  observability.ts what the Sync Errors screen renders
```

`classify.ts` turns a server error into one of six kinds, and the kind decides
the UI affordance:

| Kind | Auto-retry | User action offered |
| --- | --- | --- |
| `network` | yes, silent | none |
| `idempotent-replay` | n/a | entry deleted — the server already has it |
| `validation` | no | **Edit** the payload |
| `not-found` | no | **Edit** |
| `blocked` | no | **Retry** only — an admin must fix ERPNext data first |
| `permission` | no | hard stop |
| `unknown` | yes | retry |

`blocked` exists because of a real 102-day-old stuck entry: a missing valuation
rate produces "…is required to do accounting entries", which matches the
`validation` regex and offered the driver an **Edit** button that could never fix
it. Order matters — `blocked` patterns are tested before `validation`.

Never silently delete a queued entry. Mark it, surface it, let a human decide.

---

## 5. Server-side enforcement

Endpoints are not the only guard. Three hook layers keep a Van User inside their
own lane even when a document is created from the desk:

| Module | Hook | Job |
| --- | --- | --- |
| `van_defaults.py` | `before_validate` | Force cost centre and warehouse onto the user's van values |
| `van_filters.py` | `permission_query_conditions` | Filter list views to the user's own records |
| `van_series.py` | `before_insert` | Stamp the van's document series |
| `customer_hooks.py` | `before_insert` | Auto-assign the sales person to new customers |
| `boot.py` | `boot_session` | Inject van defaults and trim the desk sidebar |

`setup.py:after_migrate` is the idempotent provisioner: it creates the `Van User`
and `Van Manager` roles, applies their DocPerms, re-applies User Permissions from
every Vansale Configuration, ensures custom fields, imports the dashboard, and
syncs per-van series. Everything in it must be safe to run on every migrate.

---

## 6. Settings resolution

Three levels, most specific first. One helper — `me._resolve_mode` — collapses
the chain so no two call sites can disagree:

```
Vansale Configuration User.pin_mode      (per driver, PIN only)
        ↓ Follow Global
Vansale Configuration.route_mode / pin_mode / uom_change_mode   (per van)
        ↓ Follow Global
Vansale Settings.enable_route / require_pin / allow_uom_change   (global)
```

Global flags are cached in redis and invalidated in `VansaleSettings.on_update`.
Every per-van read is guarded with `meta.has_field()` so a site that has not
migrated yet keeps working rather than raising.

The client caches the resolved answer in the session store and refreshes it on
app start, on Android `appStateChange → active`, on web `visibilitychange`, and
on the offline→online transition. That refresh is load-bearing: once login stops
expiring, there is no other moment the app would re-read its configuration, and
an admin toggle would never arrive.

---

## 7. Van attribution in reports

Reports resolve the van from **who created the document**, joined to
`Vansale Configuration User`. Not from warehouse, not from sales person.

The reason is `Payment Entry`: as the app creates it, it carries no warehouse, no
cost centre and no sales-team row. The creating user is the only field common to
invoices, payments and visits. The trade-off is explicit — a document the office
creates on a driver's behalf shows a blank van, and the reports display those
rows rather than hiding them.

`Van Stock Position` is the deliberate exception. Stock belongs to the van's
warehouse regardless of who moved it, so that report joins
`Vansale Configuration Warehouse` and stays correct when the office loads a van.

---

## 8. Money paths

Two places decide what a customer is charged. Both are documented here because
both have already been wrong in production.

**Tax.** `invoice._resolve_tax_template` runs the ERPNext chain —
`erpnext.accounts.party.set_taxes`, i.e. Customer Tax Category → Tax Rule →
template — falling back to the company default. `tax_info` (preview) and `save`
(posting) call the *same* resolver so they cannot disagree. Under a template with
`included_in_print_rate` the typed rate is **gross** and tax is backed out
(`gross × r/(1+r)`); adding on top overcharges by the full tax on every line. The
arithmetic lives in `frontend/src/features/van/tax.ts` with unit tests, not inside
a component.

**Numbering.** `van_series.py` generates one series template per doctype, each
with its own abbreviation (`INV`, `CN`, `PE`, `SE`). Frappe keys the `tabSeries`
counter on the resolved prefix, so a template shared between two doctypes gives
them one shared counter — invoice 41 followed by receipt 42. The test suite
asserts the keys stay distinct.

---

## 9. Datetime discipline

Every outbound datetime goes through `naive_site_to_utc_iso`; every inbound
client timestamp through `parse_client_ts`. Frappe stores naive site-local
datetimes, and a phone in a different timezone from the site otherwise displays
the wrong wall clock. `frappe.utils.get_datetime` drops `tzinfo` on strings
ending in `Z`, which is why `parse_client_ts` uses `dateutil.isoparse`.

---

## 10. Where to look when something is wrong

| Symptom | First place to look |
| --- | --- |
| A driver's queued work will not send | `Vansale Outbox` for their `client_id`, then Frappe **Error Log** |
| Wrong figures in a report | §7 — is the document attributed to a van at all? |
| Wrong tax | Customer's Tax Category, then the template's `included_in_print_rate` |
| Numbers colliding across doctypes | §8 — a series template lost its abbreviation |
| Setting change not reaching the app | §6 — the client refresh, and the driver's app version |
| Native request fails, no server log | CORS — `install.py:ensure_capacitor_cors` |
