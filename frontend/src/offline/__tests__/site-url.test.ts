/**
 * `normalizeSiteUrl` guards the one field a layman user types by hand, on a
 * phone keyboard, from an address read off a WhatsApp message. Everything it
 * accepts becomes the base of every API call for the life of the install, so
 * the failure mode of a bad parse is "app never works and cannot be fixed
 * without a reinstall".
 */
import { describe, expect, it } from "vitest";
import { normalizeSiteUrl } from "@/app/platform";

describe("normalizeSiteUrl", () => {
  it("assumes https for a bare host", () => {
    expect(normalizeSiteUrl("van.company.com")).toBe("https://van.company.com");
  });

  it("keeps an explicit http scheme (on-prem sites without TLS)", () => {
    expect(normalizeSiteUrl("http://192.168.1.50:8000")).toBe("http://192.168.1.50:8000");
  });

  it("strips trailing slashes", () => {
    expect(normalizeSiteUrl("https://van.company.com/")).toBe("https://van.company.com");
    expect(normalizeSiteUrl("van.company.com///")).toBe("https://van.company.com");
  });

  it("drops a pasted path — the app appends its own /api/method/...", () => {
    expect(normalizeSiteUrl("https://van.company.com/app/sales-invoice")).toBe(
      "https://van.company.com",
    );
    expect(normalizeSiteUrl("van.company.com/vansale")).toBe("https://van.company.com");
  });

  it("trims whitespace and preserves a non-default port", () => {
    expect(normalizeSiteUrl("  van.company.com:8443  ")).toBe("https://van.company.com:8443");
  });

  it("keeps localhost for bench development", () => {
    expect(normalizeSiteUrl("http://localhost:8000")).toBe("http://localhost:8000");
  });

  it("rejects an empty value", () => {
    expect(() => normalizeSiteUrl("")).toThrow(/Enter your server address/);
    expect(() => normalizeSiteUrl("   ")).toThrow(/Enter your server address/);
  });

  it("rejects a bare word that is not a hostname", () => {
    // A driver typing just the company name is the likeliest mistake, and it
    // would otherwise be stored as https://fateh and fail every call.
    expect(() => normalizeSiteUrl("fateh")).toThrow(/full address/);
  });
});
