# Van Sale

Van sales PWA for field teams on top of Frappe v15 + ERPNext. Vue 3 SPA ships as a web PWA and a signed Capacitor Android APK from a single source tree. Offline-first queue with strict drain ordering.

## Documentation

| | |
|---|---|
| [`docs/`](docs/README.md) | Documentation index |
| [`docs/userguide/`](docs/userguide/index.html) | End-user guide — drivers and office |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | How it fits together, and why |
| [`docs/OPERATIONS.md`](docs/OPERATIONS.md) | Install, upgrade, release, roll back |
| [`docs/SECURITY.md`](docs/SECURITY.md) | Roles, public surface, secrets |
| [`docs/reference/`](docs/reference/) | Generated: endpoints, DocTypes, hooks |

Regenerate the reference section after touching an endpoint, a DocType or `hooks.py`:

```bash
python3 scripts/gen-docs.py
```

**Architecture pattern:** `~/.claude/skills/frappe-vue-pwa/SKILL.md`.
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

## Release an APK for a new client

Four steps. Everything else is scripted.

```bash
# 1. Config — copy the template, fill in app id, title, colours, site URL
cp customers/.env.example customers/.env.<client>

# 2. Artwork — drop a 1024x1024 icon.png (and optional logo.png) in place
mkdir -p customers/assets/<client>

# 3. Signing key — ONCE per client. Back the keystore up twice.
bash scripts/generate-keystore.sh <client>

# 4. Build. Bumps the version, builds web + native, signs the APK.
bash scripts/build-customer.sh <client>
```

Output lands in `dist/`: `vansale-<client>-<version>.apk` plus a
`vansale-<client>-pwa.tar.gz` for serving the same build from Frappe.

Rules that are load-bearing:

- **`VITE_API_BASE` must be the client's real site.** The native build aborts
  without it; a wrong value ships an APK where every call fails.
- **`CUSTOMER_APP_ID` must be unique per client** (`com.enfono.vansale.<client>`).
  Reusing an id makes the new APK overwrite the other client's app — and
  a different signing key on the same id makes Android refuse to install.
- **Never lose the keystore.** Re-signing with a new key forces every user to
  uninstall, which discards their offline queue.
- **Commit before building.** The script refuses a dirty tree, because the
  version bump it writes has to be reproducible from a tag
  (`VANSALE_ALLOW_DIRTY=1` overrides for local experiments).
- **Never hand-edit versions.** `scripts/bump-version.mjs` keeps
  `NATIVE_VERSION` and `versionCode` in lockstep; if they desync, Android
  silently skips the reinstall and the tester keeps running the old build.

See [`customers/assets/README.md`](customers/assets/README.md) for icon specs.

## License

MIT
