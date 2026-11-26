import { describe, expect, it } from "vitest";
import { bytesToBase64Url, urlBase64ToUint8Array } from "../encoding";

describe("urlBase64ToUint8Array", () => {
  it("decodes base64url: - and _ stand for + and /", () => {
    // 0xfb 0xff in standard base64 is "+/8=".
    expect(Array.from(urlBase64ToUint8Array("-_8"))).toEqual([0xfb, 0xff]);
  });

  it("takes the text with or without padding", () => {
    expect(Array.from(urlBase64ToUint8Array("-_8="))).toEqual([0xfb, 0xff]);
    expect(Array.from(urlBase64ToUint8Array("AQID"))).toEqual([1, 2, 3]);
    expect(Array.from(urlBase64ToUint8Array("AQI"))).toEqual([1, 2]);
    expect(Array.from(urlBase64ToUint8Array("AQ"))).toEqual([1]);
  });

  it("ignores spaces around the key", () => {
    expect(Array.from(urlBase64ToUint8Array("  AQID\n"))).toEqual([1, 2, 3]);
  });

  it("turns a VAPID public key (65 bytes: 0x04 and the point) back into those bytes", () => {
    const point = Uint8Array.from({ length: 65 }, (_, i) => (i === 0 ? 4 : (i * 7 + 3) % 256));
    const text = bytesToBase64Url(point);
    expect(text).toHaveLength(87);
    expect(Array.from(urlBase64ToUint8Array(text))).toEqual(Array.from(point));
  });

  it("returns nothing for an empty key", () => {
    expect(urlBase64ToUint8Array("")).toHaveLength(0);
  });

  it.each(["AB+/", "A B", "AB!D", "A", "AQIDB", "é"])("refuses %j: it is not base64url", (text) => {
    expect(() => urlBase64ToUint8Array(text)).toThrow();
  });
});

describe("bytesToBase64Url", () => {
  it("writes - and _ and no padding", () => {
    expect(bytesToBase64Url(Uint8Array.of(0xfb, 0xff))).toBe("-_8");
    expect(bytesToBase64Url(Uint8Array.of(1))).toBe("AQ");
    expect(bytesToBase64Url(new Uint8Array(0))).toBe("");
  });

  it("takes an ArrayBuffer, as the browser's getKey gives", () => {
    expect(bytesToBase64Url(Uint8Array.of(1, 2, 3).buffer)).toBe("AQID");
  });

  it("takes only the bytes a view covers, not the whole buffer behind it", () => {
    const backing = Uint8Array.of(9, 9, 1, 2, 3, 9);
    expect(bytesToBase64Url(backing.subarray(2, 5))).toBe("AQID");
  });

  it("round-trips every byte value", () => {
    const all = Uint8Array.from({ length: 256 }, (_, i) => i);
    expect(Array.from(urlBase64ToUint8Array(bytesToBase64Url(all)))).toEqual(Array.from(all));
  });
});
