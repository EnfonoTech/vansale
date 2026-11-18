/**
 * The phone's download of a private file: fetched with the app's token, saved
 * to the device, and the token never sent anywhere but this site.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

const getCredentials = vi.hoisted(() => vi.fn());
const saveBlobToDevice = vi.hoisted(() => vi.fn());
const fetchMock = vi.hoisted(() => vi.fn());

vi.mock("@/app/frappe", () => {
  class NetworkError extends Error {
    constructor(message = "Network unreachable") {
      super(message);
      this.name = "NetworkError";
    }
  }
  return { NetworkError, getCredentials, saveBlobToDevice };
});
vi.mock("@/app/platform", () => ({
  apiBase: () => "https://erp.example",
  absoluteUrl: (url: string) => (url.startsWith("/") ? `https://erp.example${url}` : url),
}));

import { downloadPrivateFile } from "../detail-download";

describe("downloadPrivateFile", () => {
  beforeEach(() => {
    getCredentials.mockReset();
    saveBlobToDevice.mockReset();
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
    getCredentials.mockResolvedValue({ apiKey: "key", apiSecret: "secret" });
  });

  it("fetches with the app's token, without cookies, and saves the bytes under the name", async () => {
    const blob = new Blob(["pdf"]);
    fetchMock.mockResolvedValue({ ok: true, status: 200, blob: async () => blob });

    await downloadPrivateFile("/private/files/cheque.pdf", "cheque.pdf");

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("https://erp.example/private/files/cheque.pdf");
    expect(init.method).toBe("GET");
    expect(init.headers).toEqual({ Authorization: "token key:secret" });
    expect(init.credentials).toBe("omit");
    expect(saveBlobToDevice).toHaveBeenCalledWith(blob, "cheque.pdf");
  });

  it("refuses what is not a path on this site, without any request", async () => {
    await expect(downloadPrivateFile("https://evil.example/x.pdf", "x.pdf")).rejects.toThrow("Not a file on this site");
    await expect(downloadPrivateFile("//evil.example/x.pdf", "x.pdf")).rejects.toThrow("Not a file on this site");
    expect(fetchMock).not.toHaveBeenCalled();
    expect(getCredentials).not.toHaveBeenCalled();
  });

  it("throws with the status when the server refuses, and saves nothing", async () => {
    fetchMock.mockResolvedValue({ ok: false, status: 403, blob: async () => new Blob() });
    await expect(downloadPrivateFile("/private/files/a.pdf", "a.pdf")).rejects.toThrow("HTTP 403");
    expect(saveBlobToDevice).not.toHaveBeenCalled();
  });

  it("raises a NetworkError when the call does not get through", async () => {
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));
    await expect(downloadPrivateFile("/private/files/a.pdf", "a.pdf")).rejects.toMatchObject({ name: "NetworkError" });
    expect(saveBlobToDevice).not.toHaveBeenCalled();
  });

  it("raises a NetworkError on a timeout", async () => {
    fetchMock.mockRejectedValue(Object.assign(new Error("aborted"), { name: "AbortError" }));
    await expect(downloadPrivateFile("/private/files/a.pdf", "a.pdf")).rejects.toThrow("timed out");
  });

  it("sends no Authorization when the app holds no credentials", async () => {
    getCredentials.mockResolvedValue(null);
    fetchMock.mockResolvedValue({ ok: true, status: 200, blob: async () => new Blob(["x"]) });
    await downloadPrivateFile("/private/files/a.pdf", "a.pdf");
    expect(fetchMock.mock.calls[0][1].headers).toEqual({});
  });
});
