# Van Sale

Van sales PWA for field teams on top of Frappe v15 + ERPNext. Vue 3 SPA ships as a web PWA and a signed Capacitor Android APK from a single source tree. Offline-first queue with strict drain ordering.

**Source of truth for architecture:** `~/.claude/skills/frappe-vue-pwa/SKILL.md`.
**Deploy + infra reference:** `~/.claude/skills/enfono-servers/SKILL.md`.
**Project handoff:** [`docs/AGENT_HANDOFF.md`](docs/AGENT_HANDOFF.md).
**Lessons diary:** [`docs/LESSONS_LEARNED.md`](docs/LESSONS_LEARNED.md).

## Structure

```
vansale/              Frappe app (Python)
frontend/             Vue 3 SPA (shared between web PWA + Capacitor APK)
android-capacitor/    Capacitor wrapper (added in Phase 5)
scripts/              build, version bump, customer asset generation
customers/            per-customer .env files
docs/                 handoff + phase plans
```

## Phased build

1. Foundation — app scaffold, PIN auth, CORS, Vue skeleton, deploy stub.
2. Offline engine — IDB, queue, drain, photo/signature uploader, UTC-ISO.
3. Core sales flow — customer, items, invoice, payment, returns, dashboard.
4. Van-specific — van stock ledger, route plan, GPS, barcode, signature, Bluetooth receipt.
5. Capacitor APK + rollout — native shell, signing, white-label pipeline, first demo ship.

Each phase has a standalone plan in [`docs/superpowers/plans/`](docs/superpowers/plans/).

## Install (once server is nominated)

```bash
bench get-app <this_repo_url> --branch develop
bench --site <site> install-app vansale
/home/<bench-user>/frappe-bench/env/bin/pip install -e /home/<bench-user>/frappe-bench/apps/vansale
sudo supervisorctl signal QUIT frappe-bench-web:frappe-bench-frappe-web
```

Open `/vansale` on the site.

## License

MIT
