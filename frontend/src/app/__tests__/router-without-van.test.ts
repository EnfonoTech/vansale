/**
 * A user without the van app may open only a short list of screens. The list
 * is a rule over route names, so a screen added later is a van screen (and
 * sent to Approvals) until someone says otherwise here.
 */
import { describe, expect, it } from "vitest";
import { routeAllowedWithoutVan } from "@/features/approvals/inbox";
import { router } from "../router";

describe("the route table, for a user without the van app", () => {
  it("opens only approvals, the approval detail, more and the sign-in screens", () => {
    const names = router
      .getRoutes()
      .map((route) => route.name)
      .filter((name): name is string => typeof name === "string");
    expect(names).toContain("dashboard");
    expect(names.filter(routeAllowedWithoutVan).sort()).toEqual([
      "approval-detail",
      "approvals",
      "login",
      "more",
      "pin",
      "setup",
    ]);
  });
});
