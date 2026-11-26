# Operations

Install, upgrade, release, deploy, roll back. Commands assume bench user `v15`
and bench path `/home/v15/frappe-bench`; substitute for your server.

> **Maintenance window.** Enfono servers are changed 02:00–05:00 IST only.
> `bench migrate`, `bench build` and `supervisorctl restart` are all inside that
> rule. Reading logs and checking status is fine any time. See the
> `enfono-servers` skill for the per-server inventory before touching anything.

---

## 1. Install on a new site

```bash
cd $PATH_TO_BENCH
bench get-app https://github.com/EnfonoTech/vansale --branch develop
bench --site <site> install-app vansale
```

Then, **always** — `bench get-app` runs pip internally, but if it was
interrupted or the app was placed by hand the Python package is not in the
virtualenv and gunicorn throws `ModuleNotFoundError` on every request:

```bash
/home/v15/frappe-bench/env/bin/pip install -e /home/v15/frappe-bench/apps/vansale
sudo supervisorctl signal QUIT frappe-bench-web:frappe-bench-frappe-web
```

Open `/vansale` on the site. `install.py:ensure_capacitor_cors` has already
added the Capacitor origins to `site_config.json.allow_cors`; without them every
APK request fails with "Failed to fetch" and **no server-side log at all**.

---

## 2. Upgrade an existing site

```bash
cd /home/v15/frappe-bench/apps/vansale
git fetch <remote> develop && git reset --hard <remote>/develop
/home/v15/frappe-bench/env/bin/pip install -e /home/v15/frappe-bench/apps/vansale
cd /home/v15/frappe-bench
bench --site <site> migrate
sudo supervisorctl signal QUIT frappe-bench-web:frappe-bench-frappe-web
```

Check the remote name first — on at least one server the vansale checkout's
remote is called `upstream`, not `origin`, so `git pull origin develop` fails
there.

> **Steel Force sites ship from `develop_2`.** This app's Steel Force work is on
> branch `develop_2`, not `develop`. On sft-uat and the other Steel Force sites
> read `develop_2` wherever this file says `develop` (`git fetch upstream
> develop_2`, `upstream/develop_2`, `--branch develop_2` in §1); on sft-uat the
> remote is `upstream`.

`bench migrate` runs `setup.after_migrate`, which is idempotent: roles, DocPerms,
User Permissions, custom fields, the dashboard, and per-van series all
re-provision. `patches.txt` runs in sequence — append, never reorder.

### The frontend is not in git

`vansale/public/spa/` is gitignored, so `git reset` does **not** update the SPA.
Deploying the frontend means shipping the tarball built locally:

```bash
# locally
bash scripts/build-customer.sh <customer>      # produces dist/vansale-<customer>-pwa.tar.gz

# on the server
SPA=/home/v15/frappe-bench/apps/vansale/vansale/public/spa
rm -rf $SPA && mkdir -p $SPA
tar xzf /tmp/vansale-<customer>-pwa.tar.gz -C $SPA
chown -R v15:v15 $SPA
```

`sites/assets/vansale` is a symlink to `apps/vansale/vansale/public`, so no
`bench build` is needed for this app's assets.

### Enabling approval notifications (needs one migrate)

Web Push for approvals (`steelforce/approvals_push.py`) adds the "Vansale Push
Subscription" DocType, so this release, unlike the approvals feature below,
needs `bench migrate` once. Push stays off until the key pair exists, so a pull
without the steps below changes nothing for users.

```bash
bench --site <site> backup                       # restore point first
cd apps/vansale && git merge --ff-only upstream/develop_2
bench --site <site> migrate                      # creates the subscription table
bench --site <site> execute vansale.steelforce.approvals_push.setup_keys
#   prints the public key; the private key is written to site_config.json only.
#   Idempotent. `force=1` makes a NEW pair and deletes every subscription.
bench --site <site> clear-cache
# swap the SPA as below, then restart the web process (the new doc_events hook)
```

`pywebpush` is a dependency (`pyproject.toml`); install it in the bench env
(`./env/bin/pip install "pywebpush>=1.14"`) on a bench that lacks it. Each user
turns it on from More > Approval notifications; it works in the web app and an
installed iPhone web app, not in the native Android app. To test, enable it on a
device, then run `send_for_action` for an open action name with `bench execute`.

### Deploying the approvals feature (no migrate)

The approvals feature (the Permission Manager approvals screens and endpoints)
changed no DocType, patch, hook, fixture or setup code and added no dependency,
so it deploys without `bench migrate`: new Python files, a changed upload
endpoint and a new SPA. This is the sequence used on sft-uat on 2026-11-19
(branch `develop_2`, remote `upstream`, bench user `frappe`), inside the
02:00–05:00 IST window. Step 1 checks that the range you are deploying holds the
same before it skips the migrate.

```bash
# 1. On the server, as the bench user: note where you are, then take the code.
cd /home/v15/frappe-bench/apps/vansale
git rev-parse HEAD > ~/vansale-rollback-head-$(date +%Y%m%d%H%M).txt
git fetch upstream develop_2
git diff --stat HEAD..upstream/develop_2 -- vansale/hooks.py vansale/patches.txt \
  vansale/setup.py vansale/install.py vansale/fixtures vansale/patches vansale/vansale
#   no output = no schema, patch, hook or fixture change: no migrate needed
git merge --ff-only upstream/develop_2     # refuses if the checkout has diverged: stop and look

# 2. Locally: build the SPA with the default environment (the same build the
#    old one was). Output goes to vansale/public/spa, which is gitignored.
cd frontend && pnpm build
tar czf /tmp/vansale-spa.tgz -C ../vansale/public/spa .
shasum -a 256 /tmp/vansale-spa.tgz         # compare after copying

# 3. Copy the tarball to the server, then, as the bench user, keep the old SPA
#    as a tarball OUTSIDE the served directory, extract the new one beside the
#    old, and swap.
PUB=/home/v15/frappe-bench/apps/vansale/vansale/public
STAMP=$(date +%Y%m%d%H%M)
curl -s https://<site>/vansale | grep -o 'index-[A-Za-z0-9_-]*\.js'   # note the old entry file
tar czf ~/vansale-spa-before-$STAMP.tgz -C $PUB/spa .
mkdir $PUB/spa.new && tar xzf /tmp/vansale-spa.tgz -C $PUB/spa.new
mv $PUB/spa $PUB/spa.old-$STAMP && mv $PUB/spa.new $PUB/spa

# 4. Restart ONLY the web process of the bench group that serves the site.
sudo supervisorctl restart frappe-bench-web:frappe-bench-frappe-web
```

Do **not** run `bench migrate` (nothing to migrate) and leave the workers alone:
nothing in this change is a hook, a scheduler entry or a background job. On
sft-uat the web process is shared with other dev and demo sites on the same box,
which see a short blip; do not restart web and workers in one call, as the web
process then stays down until the long jobs end.

Then verify (see also §6):

```bash
# the app answers
curl -s https://<site>/api/method/vansale.api.auth.site_info

# the new endpoints exist and refuse an anonymous caller: 403 ...
curl -s -o /dev/null -w '%{http_code}\n' \
  https://<site>/api/method/vansale.steelforce.approvals.availability
# ... while a method that does not exist answers 417
curl -s -o /dev/null -w '%{http_code}\n' \
  https://<site>/api/method/vansale.steelforce.approvals.no_such_endpoint

# the SPA entry file name changed from the one you noted before the swap
curl -s https://<site>/vansale | grep -o 'index-[A-Za-z0-9_-]*\.js'
```

Then run the read-only parity report for an administrator and a few real
approvers. It compares the app's inbox, counts, sent-back list and "my requests"
with Permission Manager's own for that user (it writes nothing, apart from an
Error Log row an enrichment read may defer). Run it while nothing is moving: a
document decided between its reads shows as a difference.

```bash
bench --site <site> execute vansale.steelforce.approvals_parity.parity_report \
  --kwargs "{'user': '<user>'}"
```

A pass has `'ok': True` and `'differences': []`. `'skipped'` naming `sent_back`
is expected for a user whom Permission Manager's own sent-back list refuses (the
app then says the list is not available for that user); it does not fail the
report. `bench execute` hides the real exception, so when it fails run the report
from a small script that prints the traceback, as in §6:

```python
# /tmp/parity.py  -> cd /home/v15/frappe-bench/sites && ../env/bin/python /tmp/parity.py
import traceback

import frappe

frappe.init(site="<site>")
frappe.connect()
try:
    from vansale.steelforce.approvals_parity import parity_report

    print(parity_report("<user>"))
except Exception:
    traceback.print_exc()
finally:
    frappe.destroy()
```

Once everything checks out, delete `$PUB/spa.old-<stamp>`: it sits under `public/`,
which is served at `/assets/vansale/`.

**Rollback** (no migration to undo, so §7's warning does not apply): `git reset
--hard <commit id from ~/vansale-rollback-head-<stamp>.txt>` in the app
directory, put the old SPA back from `~/vansale-spa-before-<stamp>.tgz` (or swap
`spa.old-<stamp>` back in, if you have not deleted it), and restart the web
process only.

---

## 3. Release an APK

Prerequisites once per machine: JDK 17, Android SDK, and per customer a keystore.

```bash
export JAVA_HOME=/opt/homebrew/opt/openjdk@17
export ANDROID_HOME="$HOME/Library/Android/sdk"

cp customers/.env.example customers/.env.<client>   # fill in id, title, colours, site
mkdir -p customers/assets/<client>                  # drop icon.png (1024x1024)
bash scripts/generate-keystore.sh <client>          # ONCE. back it up twice.
bash scripts/build-customer.sh <client>
```

Output: `dist/vansale-<client>-<version>.apk` and a matching PWA tarball.

Rules that are load-bearing:

- **`CUSTOMER_APP_ID` must be unique per client.** A reused id makes the new APK
  overwrite the other client's app, and a different signing key on the same id
  makes Android refuse to install.
- **Never lose a keystore.** Re-signing with a new key forces every user to
  uninstall, which discards their offline queue.
- **Never hand-edit versions.** `scripts/bump-version.mjs` keeps `NATIVE_VERSION`
  and `versionCode` in lockstep. Desynced, Android silently skips the reinstall
  and you debug a stale build.
- **Commit before building.** The script refuses a dirty tree so the version bump
  is reproducible from a tag.
- `VITE_API_BASE` is optional. Set it for a pre-pointed APK; leave it unset and
  the app asks for the server address on first run.

---

## 4. Host an APK for a tester

```bash
cp vansale-<client>-<ver>.apk /home/v15/frappe-bench/sites/<site>/public/files/
chown v15:v15 .../files/vansale-<client>-<ver>.apk
chmod 644 .../files/vansale-<client>-<ver>.apk
```

Served at `https://<site>/files/vansale-<client>-<ver>.apk`. **Publicly
downloadable by anyone with the link** — delete it when testing is done.

---

## 5. Regenerate the docs

```bash
python3 scripts/gen-docs.py
```

Rewrites `docs/reference/{API,DOCTYPES,HOOKS}.md` from source. Run it in the same
commit as any change to a whitelisted endpoint, a DocType or `hooks.py`.

---

## 6. Verify a deploy

```bash
# app version + reachability
curl -s https://<site>/api/method/vansale.api.auth.site_info

# the SPA is served and carries the right branding
curl -s https://<site>/vansale -o /dev/null -w '%{http_code} %{redirect_url}\n'

# schema landed
bench --site <site> mariadb -e "SHOW COLUMNS FROM \`tabVansale Configuration\` LIKE '%mode%';"

# no import errors
tail -20 /home/v15/frappe-bench/logs/web.error.log
```

To exercise a report the way the UI does, rather than trusting that it imported:

```bash
su - v15 -c 'cd /home/v15/frappe-bench/sites && ../env/bin/python /path/script.py'
```

with `frappe.init(site=...)` + `frappe.connect()` in the script. **Do not use
`bench console < script.py`** — IPython echoes prompts and swallows your `print`
output, which looks exactly like a script that did nothing.

`bench execute --kwargs` parses its argument as **Python**, not JSON:
`{"force": True}`, not `true`.

---

## 7. Roll back

```bash
cd /home/v15/frappe-bench/apps/vansale
git log --oneline -10
git reset --hard <previous-sha>
/home/v15/frappe-bench/env/bin/pip install -e /home/v15/frappe-bench/apps/vansale
sudo supervisorctl signal QUIT frappe-bench-web:frappe-bench-frappe-web
```

Then restore the previous SPA tarball the same way as §2.

**Migrations do not roll back.** A patch that renamed a field or a DocType stays
applied. Read `patches.txt` for the range you are reverting across before
promising a rollback; if a destructive patch ran, restore from backup instead.

Rolling the APK back means distributing the older file. Android will refuse to
install a lower `versionCode` over a higher one — the tester must uninstall, which
**discards their offline queue**. Drain the queue first.

---

## 8. Backups before anything risky

```bash
bench --site <site> backup --with-files
tar czf /root/vansale-app-$(date -u +%Y%m%dT%H%M%SZ).tar.gz \
  -C /home/v15/frappe-bench/apps vansale
```

If the app directory has uncommitted local edits — it happens on servers that
were iterated on directly — capture them before resetting:

```bash
cd /home/v15/frappe-bench/apps/vansale
git diff > /root/vansale-local-$(date -u +%Y%m%dT%H%M%SZ).patch
git status --porcelain | grep '^??' > /root/vansale-untracked.txt
```

Then confirm the edits are not unique work before discarding:
`git diff --stat <remote>/develop -- vansale/` — a diff that is nearly all
deletions means git already has everything.
