/**
 * How long `apiCall` waits for an answer: 20 s unless the caller asks for
 * more (a bulk decision, which the server works through document by document).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { apiCall, NetworkError } from "../frappe";

/** A fetch that never answers; it fails with an AbortError when its signal fires. */
function hangingFetch() {
  return vi.fn((_url: string, init?: RequestInit) => {
    return new Promise<Response>((_resolve, reject) => {
      init?.signal?.addEventListener("abort", () => {
        reject(Object.assign(new Error("The operation was aborted"), { name: "AbortError" }));
      });
    });
  });
}

beforeEach(() => {
  vi.useFakeTimers();
  // A page-supplied token: no extra request for one before the call.
  (window as unknown as { csrf_token?: string }).csrf_token = "token";
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  delete (window as unknown as { csrf_token?: string }).csrf_token;
});

describe("apiCall timeout", () => {
  it("gives up after 20 seconds by default", async () => {
    vi.stubGlobal("fetch", hangingFetch());
    const settled = vi.fn();
    const call = apiCall("POST", "vansale.api.demo.slow", {}).catch((error) => {
      settled(error);
    });

    await vi.advanceTimersByTimeAsync(19_999);
    expect(settled).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);
    await call;

    expect(settled).toHaveBeenCalledTimes(1);
    const error = settled.mock.calls[0][0];
    expect(error).toBeInstanceOf(NetworkError);
    expect((error as Error).message).toBe("Request timed out");
  });

  it("waits as long as the caller asks", async () => {
    vi.stubGlobal("fetch", hangingFetch());
    const settled = vi.fn();
    const call = apiCall("POST", "vansale.api.demo.slow", {}, 120_000).catch((error) => {
      settled(error);
    });

    await vi.advanceTimersByTimeAsync(60_000);
    expect(settled).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(59_999);
    expect(settled).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);
    await call;

    expect(settled).toHaveBeenCalledTimes(1);
    expect((settled.mock.calls[0][0] as Error).message).toBe("Request timed out");
  });

  it("an answer that comes in time is returned and the timer is cleared", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify({ message: { ok: true } }), { status: 200 })),
    );
    await expect(apiCall("GET", "vansale.api.demo.fast", undefined, 120_000)).resolves.toEqual({ ok: true });
    expect(vi.getTimerCount()).toBe(0);
  });
});
