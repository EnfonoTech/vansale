/**
 * What the detail screen shows, worked out from one `Detail`: which actions
 * sit in the bar and in what order, what replaces the bar when the user cannot
 * act, who else can act on the current step. Pure: no Vue, no Pinia, no
 * network; the server stays the owner of who may do what.
 */
import type { ActionSpec, Banner, DetailLines, Priority, Route } from "@/api/approvals";
import { priorityTone } from "./format";

/** The priorities Permission Manager offers, lowest first. */
export const PRIORITIES: Priority[] = ["Low", "Medium", "High", "Critical"];

/** `value` as one of the four priorities; anything unknown reads as Medium. */
export function normalizePriority(value: string | null | undefined): Priority {
  const wanted = (value ?? "").trim().toLowerCase();
  return PRIORITIES.find((priority) => priority.toLowerCase() === wanted) ?? "Medium";
}

export type PillTone = "danger" | "warning" | "success";

/** The pill colour of a priority: Critical and High red, Medium amber, Low green. */
export function priorityPillTone(priority: string): PillTone {
  const tone = priorityTone(priority);
  if (tone === "critical" || tone === "high") return "danger";
  return tone === "low" ? "success" : "warning";
}

export type BarMode =
  /** The document's own actions (or recommendations) are offered. */
  | { kind: "actions" }
  /** The user cannot act: one line says why, in place of the buttons. */
  | { kind: "reason"; banner: Banner }
  /** Nothing to offer (a read-only look at a document the user raised). */
  | { kind: "none" };

/**
 * What the sticky bar holds. A "recommend" banner is advice, not a block: the
 * recommendation buttons stay. The other banners take the bar's place even if
 * the server also sent actions, so a wrong combination can never offer a
 * button the user may not press.
 */
export function barMode(detail: { banner: Banner | null; actions: ActionSpec[] }): BarMode {
  const banner = detail.banner;
  if (banner && banner.kind !== "recommend") return { kind: "reason", banner };
  return detail.actions.length ? { kind: "actions" } : { kind: "none" };
}

/** An i18n key under `approvalsDetail.banner` and its parameters. */
export interface Message {
  key: string;
  params: Record<string, string>;
}

/** The sentence a banner says. A missing name falls back to a sentence without one. */
export function bannerMessage(banner: Banner): Message {
  switch (banner.kind) {
    case "recommend":
      return banner.forwarder
        ? { key: "approvalsDetail.banner.recommend", params: { name: banner.forwarder } }
        : { key: "approvalsDetail.banner.recommendAnon", params: {} };
    case "waiting":
      return banner.holder
        ? { key: "approvalsDetail.banner.waiting", params: { name: banner.holder } }
        : { key: "approvalsDetail.banner.waitingAnon", params: {} };
    case "self_owned":
      return { key: "approvalsDetail.banner.selfOwned", params: {} };
    case "cannot_read":
      return { key: "approvalsDetail.banner.cannotRead", params: {} };
  }
}

const TONE_RANK: Record<string, number> = { other: 0, reject: 1, approve: 2 };

/**
 * The order of the buttons, left to right in English: other actions, then
 * Reject, then Approve last (the one a thumb reaches first). Stable within a tone.
 */
export function orderActions(actions: ActionSpec[]): ActionSpec[] {
  return actions
    .map((action, index) => ({ action, index }))
    .sort((a, b) => (TONE_RANK[a.action.tone] ?? 0) - (TONE_RANK[b.action.tone] ?? 0) || a.index - b.index)
    .map((entry) => entry.action);
}

/** How many of the document's lines the preview leaves out. */
export function moreLines(lines: Pick<DetailLines, "rows" | "total">): number {
  return Math.max(0, lines.total - lines.rows.length);
}

export interface Holder {
  role: string;
  /** Full names of the others who hold the role now (not the viewer). */
  names: string[];
  /** Holders of the role beyond the names listed. */
  more: number;
  /** The viewer is one of the role's holders. */
  includesMe: boolean;
}

/**
 * Who can act on the current step besides the viewer, per role. A role with
 * nobody else (and not the viewer) is left out.
 */
export function currentHolders(route: Route, me: string): Holder[] {
  return route.roles
    .map((entry): Holder => {
      const others = entry.users.filter((holder) => holder.user !== me);
      return {
        role: entry.role,
        names: others.map((holder) => holder.full_name || holder.user),
        more: Math.max(0, entry.count - entry.users.length),
        includesMe: others.length !== entry.users.length,
      };
    })
    .filter((holder) => holder.names.length > 0 || holder.more > 0 || holder.includesMe);
}

/** Up to two letters for an avatar: "Mariam K." gives "MK". */
export function initials(name: string): string {
  const words = name.trim().split(/\s+/).filter(Boolean);
  if (!words.length) return "?";
  const first = Array.from(words[0])[0] ?? "";
  const last = words.length > 1 ? (Array.from(words[words.length - 1])[0] ?? "") : "";
  return (first + last).toUpperCase();
}
