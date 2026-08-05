# Van Sale documentation

Van sales for Frappe v15 + ERPNext: a Vue 3 SPA that ships as both a web PWA and
a signed Android APK from one source tree, backed by a Frappe app that owns its
own DocTypes and API.

## Start here

| You are | Read |
| --- | --- |
| A driver, or training one | [**User guide, Part A**](userguide/index.html) — the app, screen by screen |
| Setting up a van in ERPNext | [**User guide, Part B**](userguide/index.html) — every setting explained |
| Changing the code | [**ARCHITECTURE**](ARCHITECTURE.md) — how it fits together and why |
| Deploying or releasing | [**OPERATIONS**](OPERATIONS.md) — install, upgrade, APK, rollback |
| Adding an endpoint | [**SECURITY**](SECURITY.md) — §2 before you merge |
| Looking up a field or endpoint | [**reference/**](reference/) — generated from source |

## Contents

```
docs/
  README.md              this index
  ARCHITECTURE.md        design and the reasoning behind it
  OPERATIONS.md          install, upgrade, release, deploy, roll back
  SECURITY.md            roles, public surface, secrets, data scoping
  userguide/index.html   end-user guide, drivers + office
  reference/             GENERATED — do not hand-edit
    API.md               every whitelisted endpoint
    DOCTYPES.md          every DocType and field
    HOOKS.md             hooks.py registrations
```

## Generated vs written

`reference/` is produced from source by `scripts/gen-docs.py`. A hand-maintained
endpoint list is wrong within a sprint, and for a Frappe app the whitelist list
*is* the public HTTP surface — the one thing that must not drift.

```bash
python3 scripts/gen-docs.py
```

Run it in the same commit as any change to a whitelisted endpoint, a DocType or
`hooks.py`. Everything else in `docs/` is written by hand and explains *why*,
which no generator can do.

## Current state

- 67 whitelisted endpoints, 5 guest-reachable (all structurally pre-login)
- 10 DocTypes
- 4 reports, 4 number cards, 3 charts, 1 dashboard
- App v1.0.30

## Conventions worth knowing before reading code

- Every mutation is **idempotent** by a client-generated `client_id`, checked
  against `Vansale Outbox`.
- The **online path is not queued**; the offline queue is for offline only.
- `android-capacitor/src` is a **symlink** to `frontend/src`. One tree, two build
  targets. Never a second copy of a view.
- Settings resolve **user → van → global**, through one shared helper.
- Reports attribute a document to a van by **who created it**, except
  `Van Stock Position`, which attributes by warehouse.

## Related

- `~/.claude/skills/frappe-vue-pwa/` — the architecture pattern this app
  implements, including the runtime site-switching reference
- `~/.claude/skills/enfono-servers/` — server inventory, access, maintenance
  window
