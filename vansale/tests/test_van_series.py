"""Per-van naming series.

The assertion that matters is that every generated template carries a
per-doctype abbreviation. Without it Frappe keys `tabSeries` on the shared
resolved prefix and Sales Invoice / Payment Entry / Stock Entry consume ONE
counter between them — RMAX shipped that and had to strip it out.

Run: bench --site <site> run-tests --module vansale.tests.test_van_series
"""

from __future__ import annotations

import unittest

from vansale.van_series import (
    SERIES_SUFFIX,
    SERIES_TARGETS,
    normalise_prefix,
    template_for,
)


class TestVanSeriesTemplates(unittest.TestCase):
    def test_normalise_prefix(self):
        self.assertEqual(normalise_prefix("van1"), "VAN1-")
        self.assertEqual(normalise_prefix("VAN1-"), "VAN1-")
        self.assertEqual(normalise_prefix("  van1---  "), "VAN1-")
        self.assertEqual(normalise_prefix(""), "")
        self.assertEqual(normalise_prefix(None), "")

    def test_blank_prefix_produces_no_template_prefix(self):
        # A van with no prefix must fall through to the site's own series
        # rather than generating a bare "-INV-.YYYY.-.####".
        self.assertEqual(normalise_prefix(None), "")

    def test_template_shape(self):
        self.assertEqual(template_for("van1", "INV"), f"VAN1-INV{SERIES_SUFFIX}")

    def test_every_doctype_gets_a_distinct_prefix(self):
        """The counter-isolation guarantee."""
        prefix = "VAN1-"
        resolved: list[str] = []
        for doctype, abbrev, ret_abbrev in SERIES_TARGETS:
            resolved.append(template_for(prefix, abbrev))
            if ret_abbrev:
                resolved.append(template_for(prefix, ret_abbrev))

        self.assertEqual(len(resolved), len(set(resolved)), "templates must be unique")

        # The part before `.YYYY.` is what Frappe uses as the tabSeries key.
        keys = [t.split(".YYYY.")[0] for t in resolved]
        self.assertEqual(len(keys), len(set(keys)), f"shared tabSeries counter across {keys}")

        # And none of them is just the bare van prefix.
        for key in keys:
            self.assertNotEqual(key, prefix)

    def test_returns_do_not_share_the_invoice_series(self):
        inv = template_for("VAN1-", "INV")
        cn = template_for("VAN1-", "CN")
        self.assertNotEqual(inv, cn)

    def test_two_vans_never_collide(self):
        a = {template_for("VAN1-", ab) for _dt, ab, _r in SERIES_TARGETS}
        b = {template_for("VAN2-", ab) for _dt, ab, _r in SERIES_TARGETS}
        self.assertFalse(a & b)
