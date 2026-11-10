"""Smoke tests for the sf_trading code merged into this app (vansale.sf_trading).

Read-only: nothing is created, so they are safe on any site.

    bench --site <site> run-tests --app vansale --module vansale.tests.test_sf_trading_merge

They guard the merge itself: every hook still resolves, the desk JS and its server
methods exist, the DocType controllers import from the new package, the van hooks
still run ahead of sf_trading's, and the fixtures (including the Steel Force
site customizations) landed in the database in their safe, switched-off form.
"""

from __future__ import annotations

import importlib
import json
import re
from pathlib import Path

import frappe
from frappe.tests.utils import FrappeTestCase

from vansale import hooks

APP = Path(hooks.__file__).resolve().parent  # .../apps/vansale/vansale
SF = APP / "sf_trading"


def _resolve(dotted: str):
	module, _, attr = dotted.rpartition(".")
	return getattr(importlib.import_module(module), attr)


def _flatten(value):
	if isinstance(value, str):
		yield value
	elif isinstance(value, (list, tuple)):
		for v in value:
			yield from _flatten(v)
	elif isinstance(value, dict):
		for v in value.values():
			yield from _flatten(v)


def _as_list(value):
	return [value] if isinstance(value, str) else list(value)


class TestHooks(FrappeTestCase):
	def test_every_hook_path_resolves(self):
		src = (APP / "hooks.py").read_text()
		paths = set(re.findall(r'"(vansale\.[\w.]+)"', src))
		self.assertGreater(len(paths), 50)
		missing = []
		for path in sorted(paths):
			try:
				_resolve(path)
			except Exception as e:  # noqa: BLE001 - report all, not only the first
				missing.append(f"{path}: {e!r}")
		self.assertEqual(missing, [])

	def test_desk_js_files_exist(self):
		files = [
			APP / "public" / u.split("?")[0].replace("/assets/vansale/", "")
			for u in hooks.app_include_js
		]
		for mapping in (hooks.doctype_js, hooks.doctype_list_js):
			files += [APP / v for x in mapping.values() for v in _as_list(x)]
		self.assertEqual([str(f) for f in files if not f.exists()], [])

	def test_js_method_strings_point_at_real_functions(self):
		bad = []
		js_files = list((APP / "public" / "sf_trading").rglob("*.js")) + list(SF.rglob("*.js"))
		for js in js_files:
			for dotted in set(re.findall(r'["\'](vansale\.sf_trading\.[\w.]+)["\']', js.read_text())):
				parts = dotted.split(".")
				py = APP.joinpath(*parts[1:-1]).with_suffix(".py")
				if not py.exists() or not re.search(rf"def {parts[-1]}\b", py.read_text()):
					bad.append(f"{js.name}: {dotted}")
		self.assertEqual(bad, [])

	def test_no_stale_sf_trading_import_paths(self):
		stale = re.compile(r"(?<![\w.])(?:from|import)\s+sf_trading[.\s]")
		offenders = [str(p.relative_to(APP)) for p in SF.rglob("*.py") if stale.search(p.read_text())]
		self.assertEqual(offenders, [])


class TestVanHooksStillWin(FrappeTestCase):
	"""sf_trading's dimension propagation must see the cost centre the van forced."""

	def test_sales_invoice_van_before_validate_runs_first(self):
		chain = _as_list(hooks.doc_events["Sales Invoice"]["before_validate"])
		self.assertEqual(
			chain[:2],
			[
				"vansale.van_defaults.override_cost_center_from_van",
				"vansale.van_defaults.override_warehouse_from_van",
			],
		)
		self.assertIn("vansale.sf_trading.branch_defaults.propagate_dimensions_to_items", chain)

	def test_delivery_note_and_stock_entry_van_first(self):
		dn = _as_list(hooks.doc_events["Delivery Note"]["before_validate"])
		self.assertEqual(dn[0], "vansale.van_defaults.override_cost_center_from_van")
		se = _as_list(hooks.doc_events["Stock Entry"]["before_validate"])
		self.assertEqual(se[0], "vansale.van_defaults.override_cost_center_from_van")

	def test_van_naming_series_hooks_kept(self):
		for dt in ("Sales Invoice", "Payment Entry", "Stock Entry"):
			self.assertEqual(
				hooks.doc_events[dt]["before_insert"], "vansale.van_series.set_naming_series_from_van"
			)
		self.assertEqual(
			hooks.doc_events["Customer"]["before_insert"], "vansale.customer_hooks.auto_assign_sales_person"
		)

	def test_no_event_registers_the_same_handler_twice(self):
		dupes = []
		for dt, events in hooks.doc_events.items():
			for event, handlers in events.items():
				handlers = _as_list(handlers)
				if len(handlers) != len(set(handlers)):
					dupes.append(f"{dt}.{event}")
		self.assertEqual(dupes, [])


class TestDocTypesAndPages(FrappeTestCase):
	def test_doctype_controllers_import_from_vansale(self):
		bad = []
		for json_file in sorted((SF / "doctype").glob("*/*.json")):
			meta = json.loads(json_file.read_text())
			if meta.get("doctype") != "DocType":
				continue
			module = f"vansale.sf_trading.doctype.{json_file.parent.name}.{json_file.parent.name}"
			try:
				importlib.import_module(module)
			except Exception as e:  # noqa: BLE001
				bad.append(f"{module}: {e!r}")
		self.assertEqual(bad, [])

	def test_script_reports_import_from_vansale(self):
		bad = []
		for py in sorted((SF / "report").glob("*/*.py")):
			if py.name.startswith("test_") or py.name == "__init__.py":
				continue
			module = f"vansale.sf_trading.report.{py.parent.name}.{py.stem}"
			try:
				self.assertTrue(hasattr(importlib.import_module(module), "execute"), module)
			except Exception as e:  # noqa: BLE001
				bad.append(f"{module}: {e!r}")
		self.assertEqual(bad, [])

	def test_modules_and_patches_registered(self):
		self.assertIn("Sf Trading", (APP / "modules.txt").read_text().splitlines())
		patches = (APP / "patches.txt").read_text()
		for patch in re.findall(r"^(vansale\.[\w.]+)$", patches, flags=re.M):
			_resolve(patch + ".execute")


class TestFixturesLanded(FrappeTestCase):
	def test_sf_trading_custom_fields_exist(self):
		for name in (
			"Sales Invoice-custom_sale_type",
			"Customer-custom_branch_access",
			"Company-custom_enable_stock_delivered_but_not_billed",
			"Quotation-custom_payment_mode",
		):
			self.assertTrue(frappe.db.exists("Custom Field", name), name)

	def test_vansale_own_custom_fields_not_lost_in_merge(self):
		fixture = json.loads((APP / "fixtures" / "custom_field.json").read_text())
		own = [f["name"] for f in fixture if f.get("module") == "Vansale"]
		self.assertTrue(own)
		missing = [n for n in own if not frappe.db.exists("Custom Field", n)]
		self.assertEqual(missing, [])

	def test_site_property_setters_imported(self):
		self.assertTrue(frappe.db.exists("Property Setter", "Sales Invoice-scan_barcode-hidden"))

	def test_naming_series_options_were_not_shipped(self):
		fixture = json.loads((APP / "fixtures" / "property_setter.json").read_text())
		self.assertEqual([p["name"] for p in fixture if p["name"].endswith("-options")], [])

	def test_workflows_and_server_script_ship_switched_off(self):
		for name in ("Purchase Inv", "Sales Approval"):
			self.assertEqual(frappe.db.get_value("Workflow", name, "is_active"), 0, name)
		self.assertEqual(frappe.db.get_value("Server Script", "comment", "disabled"), 1)

	def test_item_search_client_script_points_at_vansale(self):
		script = frappe.db.get_value("Client Script", "Item order", "script")
		self.assertIn("vansale.sf_trading.custom_search.item_search_sorted", script)
		self.assertNotIn('"sf_trading.sf_trading', script)

	def test_fixture_hook_covers_every_fixture_file(self):
		listed = {(f.get("doctype") or f.get("dt")).lower().replace(" ", "_") for f in hooks.fixtures}
		files = {p.stem for p in (APP / "fixtures").glob("*.json")}
		# dcr_* files are per-report extras kept from sf_trading, not dt fixtures
		self.assertEqual({f for f in files if not f.startswith("dcr_")} - listed, set())
