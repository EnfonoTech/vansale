import { beforeEach, describe, expect, it } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import type { ConfigDefaults } from "@/api/me";
import { useSessionStore } from "../session";

/** Settings as the server sends them: only the role flags matter here. */
function settings(flags: Partial<Pick<ConfigDefaults, "is_van_user" | "is_van_manager">>): ConfigDefaults {
  return { is_van_user: false, is_van_manager: false, ...flags } as ConfigDefaults;
}

describe("hasVanShell", () => {
  beforeEach(() => {
    window.localStorage.clear();
    setActivePinia(createPinia());
  });

  it("is true for a Van User", () => {
    const session = useSessionStore();
    session.defaults = settings({ is_van_user: true });
    expect(session.hasVanShell).toBe(true);
  });

  it("is true for a Van Manager who is not a Van User", () => {
    const session = useSessionStore();
    session.defaults = settings({ is_van_manager: true });
    expect(session.isVanUser).toBe(false);
    expect(session.hasVanShell).toBe(true);
  });

  it("is true for both", () => {
    const session = useSessionStore();
    session.defaults = settings({ is_van_user: true, is_van_manager: true });
    expect(session.hasVanShell).toBe(true);
  });

  it("is false for neither: that user gets the approvals-only shell", () => {
    const session = useSessionStore();
    session.defaults = settings({});
    expect(session.hasVanShell).toBe(false);
  });

  it("is false when an older server sends no manager flag and the user is no Van User", () => {
    const session = useSessionStore();
    session.defaults = { is_van_user: false } as ConfigDefaults;
    expect(session.hasVanShell).toBe(false);
  });

  it("is true while the settings are not loaded, so the nav does not flicker", () => {
    const session = useSessionStore();
    expect(session.defaults).toBeNull();
    expect(session.hasVanShell).toBe(true);
  });

  it("follows the settings when they arrive", () => {
    const session = useSessionStore();
    session.setDefaults(settings({}));
    expect(session.hasVanShell).toBe(false);
    session.setDefaults(settings({ is_van_manager: true }));
    expect(session.hasVanShell).toBe(true);
  });
});
