# Enfono Frappe App — CLAUDE.md Template

Copy this file to `CLAUDE.md` in any Frappe custom app root.
Replace `vansale`, `vansale`, `KSA` placeholders.

---

```markdown
# vansale — Claude Code Instructions

## MANDATORY: Frappe Skill

**RULE:** Before writing ANY Frappe code, answering ANY Frappe question, or making ANY plan — invoke the `frappe-erpnext-expert` skill. No exceptions.

Trigger: any prompt containing frappe, erpnext, doctype, hooks, bench, custom field, print format, salary slip, sales invoice, purchase invoice, stock entry, workflow, fixtures, whitelist, server script, client script, patch, migration.

## Brain MCP Tools (use before guessing)

Always available in Claude Code sessions. Call these FIRST for any field/hook/pattern question:

- `mcp__frappe-brain__frappe_corpus_search` — ripgrep 615 Frappe repos
- `mcp__frappe-brain__frappe_find_doctype` — locate DocType JSON + controllers  
- `mcp__frappe-brain__frappe_find_hook` — find hooks.py registrations
- `mcp__frappe-brain__frappe_knowledge_search` — semantic search (Voyage embeddings)
- `mcp__frappe-brain__frappe_get_print_format` — 481 Enfono print formats
- `mcp__frappe-brain__frappe_client_context` — per-client merged config

**Do NOT guess field names, hook signatures, or v15 API behavior. Brain corpus is ground truth.**

## Project Context

- **App:** `vansale`
- **Client:** `vansale`
- **Region:** `KSA` (KSA / UAE / India)
- **Frappe version:** v15 (default unless bench shows otherwise)
- **Bench root:** `/home/frappe/frappe-bench/` (or per-client path)

## Key Files — Read First on Any Task

```
apps/vansale/
├── hooks.py                          # Extension points — read before adding any
├── vansale/
│   ├── config/
│   │   └── desktop.py                # Module icons
│   ├── patches.txt                   # Migration order — add new patches here
│   ├── patches/                      # Patch scripts per version
│   ├── fixtures/                     # Exported Custom Fields, Property Setters, Workflows
│   └── <module>/
│       └── doctype/
│           └── <doctype>/
│               ├── <doctype>.json    # DocType definition — source of truth for fields
│               ├── <doctype>.py     # Controller — lifecycle hooks go here
│               ├── <doctype>.js    # Client script
│               └── test_<doctype>.py # Tests — required for accounting/stock DocTypes
```

## Hard Rules (non-negotiable)

### Database
- ❌ `frappe.db.sql(f"… {var} …")` — SQL injection blocker
- ✅ `frappe.qb` by default; raw SQL only parameterised: `frappe.db.sql("WHERE name = %s", (val,))`
- ✅ Right reader: `get_value` (one field), `get_list` (perms), `get_all` (no perms), `get_doc` (full), `get_cached_doc` (cached)

### Type Coercion
- ❌ `int(x)`, `float(x)`, `str(x)` on user input
- ✅ `cint`, `flt`, `cstr` from `frappe.utils` — handle None/empty/locale

### Errors
- User-facing: `frappe.throw(_("Message"))` — translatable, shows in UI
- Diagnostic: `frappe.log_error(message, title)` — doesn't interrupt
- ❌ `print(...)` or bare `raise Exception(...)` in production

### Translations
- Every user-visible string: `_("text")` (Python) / `__("text")` (JS)
- Includes throw messages, button labels, print format text, dialog titles

### Hooks vs Controllers
- DocType lifecycle events → controller `.py` class only
- `hooks.py doc_events` → only for extending ANOTHER app's DocType
- ❌ Never edit `apps/frappe/` or `apps/erpnext/` directly

### Performance
- N+1 queries in loops = blocker. Use `filters={"name": ["in", [...]]}` or joins
- Long operations (>30s) → `frappe.enqueue(method, queue="long", timeout=1500, enqueue_after_commit=True)`

### External API calls (ZATCA / WhatsApp / Payment Gateway)
- Must be idempotent. Use `job_name=f"zatca_{invoice_name}"` for deduplication
- Worker must check if already done before executing
- Wrap in try/except, log with `frappe.log_error`, write status field for retry

## Workflow on Every Task

1. **Read environment** — `hooks.py`, `patches.txt`, target DocType `.json`
2. **Search brain** — call `frappe_corpus_search` or `frappe_knowledge_search` before writing custom code
3. **Plan** — for non-trivial tasks: files changed, DocTypes touched, hooks fired, migrations needed, tests to add
4. **Code with tests** — every controller method and whitelisted endpoint gets a test
5. **Update fixtures** — any Custom Field / Property Setter / Workflow change → `bench export-fixtures`
6. **Migration safety** — field rename or DocType change → patch in `patches/` + entry in `patches.txt`

## Print Formats

- Use bilingual (Arabic/English) template from skill: `assets/templates/print_format_bilingual_zatca.html`
- ZATCA QR placeholder already included — do NOT reimplement QR logic
- Tax lines: read from `doc.taxes` (handles zero-rated/exempt correctly)
- Store in fixture: `bench export-fixtures --doctype "Print Format"` after saving

## Regional Defaults — KSA

### KSA
- VAT: 15%, SAR currency, 2 decimals
- ZATCA Phase 2: use `8848digital/KSA` — never reimplement XML/QR
- Bilingual print formats mandatory
- HR: GOSI, Iqama expiry, WPS payroll
- Check `references/regional-ksa-uae.md` before any compliance work

### UAE
- VAT: 5%, AED currency, 2 decimals
- Bilingual print formats expected
- HR: labour law leave accruals

## Quick Reference

| Task | API |
|---|---|
| Get one field | `frappe.db.get_value(dt, name, field)` |
| Get a doc | `frappe.get_doc(dt, name)` |
| Cached doc | `frappe.get_cached_doc(dt, name)` |
| Get many (perms) | `frappe.get_list(dt, filters, fields)` |
| Get many (no perms) | `frappe.get_all(dt, filters, fields)` |
| Insert | `doc = frappe.get_doc({...}); doc.insert()` |
| Submit | `doc.submit()` |
| Throw user error | `frappe.throw(_("..."))` |
| Log error | `frappe.log_error(message, title)` |
| Background job | `frappe.enqueue(method, queue, timeout)` |
| Realtime push | `frappe.publish_realtime(event, message, user=...)` |
| Permission check | `frappe.has_permission(dt, ptype, doc)` |
| Today | `frappe.utils.today()` |
| Coerce int/float/str | `cint`, `flt`, `cstr` from `frappe.utils` |

## What to Refuse (push back, explain why)

- Editing core Frappe/ERPNext files → propose fixture/hook/override
- Bypassing permissions "for convenience" → require justification
- Storing secrets in client scripts or plain Data fields → use Password fieldtype or `frappe.conf`
- Custom DocType when existing core DocType + custom fields would do
- Skipping tests on submittable accounting/stock DocTypes
- Raw SQL with f-strings / format strings

## Commit Standards

```bash
# Format: <type>(<scope>): <description>
feat(sales-invoice): add VAT exemption custom field + fixture
fix(zatca): handle empty tax_id on invoice submit
patch(v1_2): rename custom_vat_reg to custom_vat_registration_number
docs: update print format README
```

## Useful Bench Commands

```bash
bench --site <site> migrate                    # after schema changes
bench export-fixtures --app vansale       # after Custom Field changes
bench --site <site> run-tests --app vansale  # run all tests
bench --site <site> console                    # Python REPL with frappe context
bench --site <site> execute <method>           # run a whitelisted method directly
```
```
