/**
 * How `apiCall` reads a failed answer: a server restarting (502 / 503 / 504)
 * is a network failure (queue and retry), an ended web session is said once,
 * and the server's exception type travels with the error.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { apiCall, ApiError, NetworkError, SESSION_EXPIRED_EVENT, SessionExpiredError } from "../frappe";

function answer(status: number, body: unknown) {
  return vi.fn(() => Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } })));
}

beforeEach(() => {
  (window as unknown as { csrf_token?: string }).csrf_token = "token";
});
afterEach(() => {
  vi.unstubAllGlobals();
  delete (window as unknown as { csrf_token?: string }).csrf_token;
});

describe("apiCall failed answers", () => {
  it.each([502, 503, 504])("treats HTTP %i as a network failure", async (status) => {
    vi.stubGlobal("fetch", answer(status, {}));
    await expect(apiCall("POST", "vansale.api.invoice.save", {})).rejects.toBeInstanceOf(NetworkError);
  });

  it("an ended session raises SessionExpiredError and tells the app", async () => {
    vi.stubGlobal("fetch", answer(403, { session_expired: 1, exc_type: "PermissionError" }));
    const heard = vi.fn();
    window.addEventListener(SESSION_EXPIRED_EVENT, heard);
    await expect(apiCall("GET", "vansale.api.customer.list_mine")).rejects.toBeInstanceOf(SessionExpiredError);
    expect(heard).toHaveBeenCalledTimes(1);
    window.removeEventListener(SESSION_EXPIRED_EVENT, heard);
  });

  it("a wrong password while signing in is not taken for an ended session", async () => {
    vi.stubGlobal("fetch", answer(401, { session_expired: 1, message: "Invalid login credentials" }));
    const err = await apiCall("POST", "vansale.api.auth.login", {}).catch((e) => e);
    expect(err).not.toBeInstanceOf(SessionExpiredError);
    expect(err).toBeInstanceOf(ApiError);
  });

  it("carries the server's exception type", async () => {
    vi.stubGlobal("fetch", answer(417, { exc_type: "ValidationError", exception: "frappe.exceptions.ValidationError: لا" }));
    const err = await apiCall("POST", "vansale.api.invoice.save", {}).catch((e) => e);
    expect((err as ApiError).excType).toBe("ValidationError");
  });
});
