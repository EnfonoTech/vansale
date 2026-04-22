/**
 * Error classification — maps raw drain failures into user-facing
 * categories so the sync-errors view can offer the right action
 * (retry, edit, discard).
 *
 * Categories:
 *   - `network`             — transient, auto-retry silently
 *   - `idempotent-replay`   — server already has this clientId; treat
 *                             as SUCCESS (delete the queue entry)
 *   - `permission`          — user lacks rights; edit won't help
 *   - `not-found`           — referenced doc missing; user should edit
 *   - `validation`          — bad payload; user should edit
 *   - `unknown`             — fall-through; retryable
 */
import { describe, expect, it } from "vitest";
import { classifyError } from "@/offline/classify";
import { ApiError, NetworkError } from "@/app/frappe";

describe("classifyError", () => {
  it("classifies NetworkError as network (retryable, silent)", () => {
    const c = classifyError(new NetworkError("offline"));
    expect(c.kind).toBe("network");
    expect(c.retryable).toBe(true);
    expect(c.userFacing).toBe(false);
  });

  it("classifies 'already submitted' as idempotent-replay (treat as success)", () => {
    const c = classifyError(new ApiError("dup", 417, "Sales Invoice has already been submitted"));
    expect(c.kind).toBe("idempotent-replay");
    expect(c.retryable).toBe(false);
    expect(c.treatAsSuccess).toBe(true);
  });

  it("classifies 'not permitted' as permission (not retryable)", () => {
    const c = classifyError(new ApiError("perm", 403, "User not permitted to perform this action"));
    expect(c.kind).toBe("permission");
    expect(c.retryable).toBe(false);
    expect(c.userFacing).toBe(true);
  });

  it("classifies 'not found' as not-found (user must edit)", () => {
    const c = classifyError(new ApiError("nf", 404, "Customer CUST-0001 not found"));
    expect(c.kind).toBe("not-found");
    expect(c.retryable).toBe(false);
    expect(c.requiresEdit).toBe(true);
  });

  it("classifies 'Mandatory' as validation (user must edit)", () => {
    const c = classifyError(new ApiError("val", 417, "Mandatory fields required: customer_name"));
    expect(c.kind).toBe("validation");
    expect(c.retryable).toBe(false);
    expect(c.requiresEdit).toBe(true);
  });

  it("falls through to unknown (retryable) for unrecognised errors", () => {
    const c = classifyError(new ApiError("boom", 500, "Internal server error"));
    expect(c.kind).toBe("unknown");
    expect(c.retryable).toBe(true);
  });

  it("falls through to unknown for plain Error instances", () => {
    const c = classifyError(new Error("wat"));
    expect(c.kind).toBe("unknown");
    expect(c.retryable).toBe(true);
  });
});
