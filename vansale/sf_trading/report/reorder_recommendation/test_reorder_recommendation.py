# apps/vansale/vansale/sf_trading/report/reorder_recommendation/test_reorder_recommendation.py
"""The arithmetic and the classification, tested without touching the ledger.

The queries are exercised against real data by running the report; what is worth pinning down
here is what the numbers mean once the quantities are in hand, because that is what a buyer acts
on and what would silently drift if the formula were edited.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from vansale.sf_trading.report.reorder_recommendation.reorder_recommendation import (
    _action,
    _build_row,
    _demand_clause,
    _item_clause,
)


def _scope(item_code=None, groups=None):
    return frappe._dict(item_code=item_code, groups=groups)


def _meta(**overrides):
    item = frappe._dict({
        "name": "ITEM-A",
        "item_name": "Item A",
        "item_group": "Products",
        "stock_uom": "Nos",
        "lead_time_days": 0,
        "safety_stock": 0,
        "min_order_qty": 0,
        "last_purchase_rate": 10,
        "disabled": 0,
        "is_stock_item": 1,
        "whole_number": False,
    })
    item.update(overrides)
    return {item.name: item}


def _row(days=90, default_lead=7, coverage=30, z=1.65,
         demand=None, bin_row=None, meta=None, lead_times=None, configured=None):
    key = ("ITEM-A", "WH-1")
    return _build_row(
        key,
        meta if meta is not None else _meta(),
        {key: frappe._dict(sold_qty=90, purchased_qty=0, issued_qty=0, received_qty=0,
                           last_movement="2026-08-01")},
        {key: frappe._dict(demand if demand is not None else
                           {"sum_qty": 90, "sum_sq": 90, "active_days": 90, "peak_day": 1})},
        {key: frappe._dict(bin_row if bin_row is not None else
                           {"actual_qty": 10, "projected_qty": 10, "valuation_rate": 10})},
        configured or {},
        lead_times or {},
        _scope(),
        days=days, default_lead=default_lead, coverage=coverage, z=z,
    )


class TestReorderRecommendation(FrappeTestCase):
    # ── the formula ───────────────────────────────────────────────────────────

    def test_level_is_lead_time_demand_plus_safety(self):
        """One a day, flat, with a week's lead time: a week's worth on the shelf."""
        row = _row()
        self.assertEqual(row["avg_daily"], 1.0)
        self.assertEqual(row["variability"], 0.0)          # no day differed from any other
        self.assertEqual(row["safety_stock"], 0.0)
        self.assertEqual(row["reorder_level"], 7.0)

    def test_order_up_to_covers_the_coverage_days(self):
        row = _row()
        self.assertEqual(row["order_up_to"], 37.0)         # 7 lead + 30 coverage, one a day
        # 37 wanted, 10 already there or coming
        self.assertEqual(row["reorder_qty"], 27.0)

    def test_inbound_stock_is_not_ordered_twice(self):
        """Projected, not actual, drives the order: 20 on a purchase order is 20 fewer to buy."""
        with_inbound = _row(bin_row={"actual_qty": 10, "projected_qty": 30, "valuation_rate": 10})
        without = _row(bin_row={"actual_qty": 10, "projected_qty": 10, "valuation_rate": 10})
        self.assertEqual(without["reorder_qty"] - with_inbound["reorder_qty"], 20.0)

    def test_a_full_shelf_is_not_topped_up(self):
        row = _row(bin_row={"actual_qty": 500, "projected_qty": 500, "valuation_rate": 10})
        self.assertEqual(row["reorder_qty"], 0.0)

    def test_lumpy_demand_earns_safety_stock(self):
        """Ninety sold in one day, not one a day. Same average, and no buyer should treat them
        the same, so the variability has to show up as safety stock."""
        flat = _row()
        lumpy = _row(demand={"sum_qty": 90, "sum_sq": 8100, "active_days": 1, "peak_day": 90})
        self.assertEqual(flat["avg_daily"], lumpy["avg_daily"])
        self.assertGreater(lumpy["safety_stock"], 0)
        self.assertGreater(lumpy["reorder_level"], flat["reorder_level"])

    def test_quiet_days_count_as_zero_demand(self):
        """Halving the window doubles the daily average for the same quantity sold."""
        long_window = _row(days=90)
        short_window = _row(days=45)
        self.assertAlmostEqual(short_window["avg_daily"], long_window["avg_daily"] * 2, places=3)

    def test_service_level_moves_only_the_safety_stock(self):
        lumpy = {"sum_qty": 90, "sum_sq": 8100, "active_days": 1, "peak_day": 90}
        cautious = _row(demand=lumpy, z=2.33)
        relaxed = _row(demand=lumpy, z=1.04)
        self.assertGreater(cautious["safety_stock"], relaxed["safety_stock"])
        self.assertEqual(cautious["avg_daily"], relaxed["avg_daily"])

    # ── lead time ─────────────────────────────────────────────────────────────

    def test_purchase_history_beats_the_item_master_and_the_filter(self):
        row = _row(
            meta=_meta(lead_time_days=14),
            lead_times={"ITEM-A": frappe._dict(lead_days=3, receipts=4)},
        )
        self.assertEqual(row["lead_days"], 3)
        self.assertIn("Purchase history", row["lead_source"])

    def test_item_master_is_used_when_there_is_no_purchase_history(self):
        row = _row(meta=_meta(lead_time_days=14))
        self.assertEqual(row["lead_days"], 14)
        self.assertEqual(row["reorder_level"], 14.0)

    def test_filter_default_is_the_last_resort(self):
        """Every item on this site has a zero lead time, so this is the usual path."""
        row = _row(default_lead=10)
        self.assertEqual(row["lead_days"], 10)
        self.assertEqual(row["reorder_level"], 10.0)

    # ── respecting what someone already decided ───────────────────────────────

    def test_a_typed_safety_stock_is_never_undercut(self):
        row = _row(meta=_meta(safety_stock=100))
        self.assertEqual(row["safety_stock"], 100.0)
        self.assertEqual(row["reorder_level"], 107.0)

    def test_minimum_order_quantity_is_respected(self):
        row = _row(meta=_meta(min_order_qty=500))
        self.assertEqual(row["reorder_qty"], 500.0)

    def test_whole_number_uoms_are_rounded_up(self):
        """Half a day's worth over the line still means ordering a whole one."""
        fractional = _row(demand={"sum_qty": 45, "sum_sq": 45, "active_days": 45, "peak_day": 1})
        whole = _row(
            meta=_meta(whole_number=True),
            demand={"sum_qty": 45, "sum_sq": 45, "active_days": 45, "peak_day": 1},
        )
        # one a day on half the days: 0.5/day, and enough variability to earn 2.195 of safety
        self.assertEqual(fractional["reorder_qty"], 10.695)
        self.assertEqual(whole["reorder_qty"], 11.0)

    def test_the_existing_setting_is_shown_beside_the_suggestion(self):
        key = ("ITEM-A", "WH-1")
        row = _row(configured={key: frappe._dict(warehouse_reorder_level=5,
                                                warehouse_reorder_qty=50)})
        self.assertEqual(row["existing_level"], 5.0)
        self.assertEqual(row["reorder_level"], 7.0)        # the suggestion is not overwritten

    # ── what the row is telling the buyer ─────────────────────────────────────

    def test_empty_shelf_on_a_selling_item_is_out_of_stock(self):
        self.assertEqual(_action(1.0, 0, 0, 7, 0, 7, 30), "Out of Stock")

    def test_well_under_the_level_says_order_now(self):
        self.assertEqual(_action(1.0, 2, 2, 7, 2, 7, 30), "Order Now")

    def test_just_under_the_level_says_below_level(self):
        self.assertEqual(_action(1.0, 6, 6, 7, 6, 7, 30), "Below Level")

    def test_close_above_the_level_is_worth_watching(self):
        self.assertEqual(_action(1.0, 8, 8, 7, 8, 7, 30), "Watch")

    def test_comfortable_is_ok(self):
        self.assertEqual(_action(1.0, 20, 20, 7, 20, 7, 30), "OK")

    def test_years_of_cover_is_excess_not_health(self):
        self.assertEqual(_action(1.0, 400, 400, 7, 400, 7, 30), "Overstocked")

    def test_stock_that_never_sells_is_dead_not_ok(self):
        self.assertEqual(_action(0, 100, 100, 0, None, 7, 30), "Dead Stock")

    def test_no_stock_and_no_sales_is_neither(self):
        self.assertEqual(_action(0, 0, 0, 0, None, 7, 30), "No Demand")

    def test_nothing_is_ordered_for_an_item_nobody_buys(self):
        row = _row(
            demand={"sum_qty": 0, "sum_sq": 0, "active_days": 0, "peak_day": 0},
            bin_row={"actual_qty": 100, "projected_qty": 100, "valuation_rate": 10},
        )
        self.assertEqual(row["action"], "Dead Stock")
        self.assertEqual(row["reorder_qty"], 0.0)
        self.assertEqual(row["stock_value"], 1000.0)

    # ── scope and skipping ────────────────────────────────────────────────────

    def test_a_disabled_item_is_left_out(self):
        self.assertIsNone(_row(meta=_meta(disabled=1)))

    def test_a_non_stock_item_is_left_out(self):
        self.assertIsNone(_row(meta=_meta(is_stock_item=0)))

    def test_an_item_outside_the_chosen_group_is_left_out(self):
        key = ("ITEM-A", "WH-1")
        row = _build_row(
            key, _meta(item_group="Products"), {}, {}, {}, {}, {},
            _scope(groups=["Raw Material"]),
            days=90, default_lead=7, coverage=30, z=1.65,
        )
        self.assertIsNone(row)

    # ── the SQL fragments ─────────────────────────────────────────────────────

    def test_material_issue_counts_as_demand_only_when_asked(self):
        self.assertNotIn("Material Issue", _demand_clause(frappe._dict()))
        self.assertIn("Material Issue",
                      _demand_clause(frappe._dict(include_material_issue=1)))

    def test_transfers_are_never_demand(self):
        for filters in (frappe._dict(), frappe._dict(include_material_issue=1)):
            self.assertNotIn("Material Transfer", _demand_clause(filters))

    def test_the_item_scope_travels_as_bound_parameters(self):
        clause = _item_clause(_scope(item_code="ITEM-A", groups=["Products"]))
        self.assertIn("%(item_code)s", clause)
        self.assertIn("%(groups)s", clause)
        self.assertNotIn("ITEM-A", clause)          # no value is ever pasted into the SQL
        self.assertNotIn("Products", clause)

    def test_unsellable_items_are_dropped_in_the_database(self):
        clause = _item_clause(_scope())
        self.assertIn("it.is_stock_item = 1", clause)
        self.assertIn("it.disabled = 0", clause)
