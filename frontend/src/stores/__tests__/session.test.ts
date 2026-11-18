import { beforeEach, describe, expect, it } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import type { ConfigDefaults } from "@/api/me";
import { approvalsOnly } from "@/features/approvals/inbox";
import { useSessionStore } from "../session";

/** Settings as the server sends them: only the role flags matter here. */
function settings(
  flags: Partial<Pick<ConfigDefaults, "is_van_user" | "is_van_manager" | "is_system_manager" | "van_code" | "approvals">>,
): ConfigDefaults {
  return { is_van_user: false, is_van_manager: false, van_code: null, ...flags } as ConfigDefaults;
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

  it("is true for a user with a van but without the Van User role: the van code is enough", () => {
    const session = useSessionStore();
    session.defaults = settings({ van_code: "VAN-01" });
    expect(session.isVanUser).toBe(false);
    expect(session.hasVanShell).toBe(true);
  });

  it("is true for a System Manager with no van role and no van code: they keep the van screens", () => {
    const session = useSessionStore();
    session.defaults = settings({ is_system_manager: true });
    expect(session.isVanUser).toBe(false);
    expect(session.hasVanShell).toBe(true);
  });

  it("is false for a plain approver, and for an older server that sends no System Manager flag", () => {
    const session = useSessionStore();
    session.defaults = settings({ is_system_manager: false });
    expect(session.hasVanShell).toBe(false);
    session.defaults = settings({});
    expect(session.hasVanShell).toBe(false);
  });

  it("is false for no role and no van code, or a blank one", () => {
    const session = useSessionStore();
    session.defaults = settings({ van_code: null });
    expect(session.hasVanShell).toBe(false);
    session.defaults = settings({ van_code: "" });
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
    session.setDefaults(settings({ van_code: "VAN-02" }));
    expect(session.hasVanShell).toBe(true);
  });
});

/** The shell decision the router, nav and Home take: the real store, the real rule. */
describe("approvalsOnly with the session store", () => {
  beforeEach(() => {
    window.localStorage.clear();
    setActivePinia(createPinia());
  });

  const on = { approvals: { enabled: true } };
  const off = { approvals: { enabled: false } };

  it("a user with a van code but no van role keeps the van shell", () => {
    const session = useSessionStore();
    session.defaults = settings({ van_code: "VAN-01", ...on });
    expect(approvalsOnly(session)).toBe(false);
  });

  it("a user with no van at all and approvals on gets the approvals-only shell", () => {
    const session = useSessionStore();
    session.defaults = settings({ ...on });
    expect(approvalsOnly(session)).toBe(true);
  });

  it("a System Manager with no van setup keeps the van shell and still has approvals", () => {
    const session = useSessionStore();
    session.defaults = settings({ is_system_manager: true, ...on });
    expect(approvalsOnly(session)).toBe(false);
    expect(session.approvalsEnabled).toBe(true);
  });

  it("a plain approver with none of the van signs and approvals on is approvals-only", () => {
    const session = useSessionStore();
    session.defaults = settings({ is_system_manager: false, van_code: null, ...on });
    expect(approvalsOnly(session)).toBe(true);
  });

  it("with Permission Manager off (approvals disabled) nobody gets the approvals-only shell", () => {
    const session = useSessionStore();
    session.defaults = settings(off);
    expect(approvalsOnly(session)).toBe(false);
    session.defaults = settings({ van_code: "VAN-01", ...off });
    expect(approvalsOnly(session)).toBe(false);
    session.defaults = settings({ is_system_manager: false, ...off });
    expect(approvalsOnly(session)).toBe(false);
  });

  it("an older server that sends no approvals flag counts as Permission Manager off", () => {
    const session = useSessionStore();
    session.defaults = settings({});
    expect(session.approvalsEnabled).toBe(false);
    expect(approvalsOnly(session)).toBe(false);
  });

  it("unloaded settings (defaults null) count as van and are never approvals-only", () => {
    const session = useSessionStore();
    expect(session.defaults).toBeNull();
    expect(session.hasVanShell).toBe(true);
    expect(approvalsOnly(session)).toBe(false);
  });
});
