/**
 * The web app lives at /vansale and, as an alias, at /sf-connect: the router's
 * base and the service worker's scope follow the path it was opened at.
 */
import { describe, expect, it } from "vitest";
import { webBase, webScope } from "@/app/web-base";

describe("web base", () => {
  it("is /sf-connect/ under the alias", () => {
    for (const path of ["/sf-connect", "/sf-connect/", "/sf-connect/login", "/sf-connect/invoices/new"]) {
      expect(webBase(path)).toBe("/sf-connect/");
      expect(webScope(path)).toBe("/sf-connect");
    }
  });

  it("is /vansale/ everywhere else", () => {
    for (const path of ["/vansale", "/vansale/login", "/", "", "/sf-connectx", "/app/sf-connect"]) {
      expect(webBase(path)).toBe("/vansale/");
      expect(webScope(path)).toBe("/vansale");
    }
  });
});
