/**
 * The state of the "Approval notifications" switch, kept apart from the page
 * so every path through it can be tested: what the switch shows, whether it
 * may be touched, and which status line it carries.
 */
import type { Support } from "./support";

export type Target = "on" | "off";

/** Why a change did not happen: no connection, or anything else (the server or the browser said no). */
export type Problem = "offline" | "failed";

export type ToggleState =
  /** Reading the browser and asking the server. */
  | { kind: "checking" }
  /** This device cannot take Web Push (or it is the native app). */
  | { kind: "unsupported" }
  /** Notifications are blocked for the site: only the browser's settings can lift it. */
  | { kind: "blocked" }
  | { kind: "off" }
  | { kind: "on" }
  /** A change is on its way; the switch already shows where it is going. */
  | { kind: "busy"; target: Target }
  /** The last change failed; `was` is what the switch goes back to. */
  | { kind: "error"; was: Target; problem: Problem };

export type ToggleEvent =
  /** What a look at the browser and the server found. */
  | { type: "checked"; support: Support; subscribed: boolean }
  | { type: "start"; target: Target }
  | { type: "done" }
  /** The user refused the permission prompt. */
  | { type: "denied" }
  /** The prompt was closed without an answer: nothing changed. */
  | { type: "dismissed" }
  | { type: "failed"; problem: Problem };

export const INITIAL: ToggleState = { kind: "checking" };

/** What the switch shows: the committed side, or where a running change is heading. */
export function isOn(state: ToggleState): boolean {
  switch (state.kind) {
    case "on":
      return true;
    case "busy":
      return state.target === "on";
    case "error":
      return state.was === "on";
    default:
      return false;
  }
}

/** The side a switch tap leads to, or null when the switch cannot move. */
function nextTarget(state: ToggleState): Target | null {
  switch (state.kind) {
    case "off":
      return "on";
    case "on":
      return "off";
    case "error":
      return state.was === "on" ? "off" : "on";
    default:
      return null;
  }
}

export function reduce(state: ToggleState, event: ToggleEvent): ToggleState {
  switch (event.type) {
    case "checked":
      // A look that began before a change was asked must not undo it.
      if (state.kind === "busy") return state;
      if (event.support === "unsupported") return { kind: "unsupported" };
      if (event.support === "denied") return { kind: "blocked" };
      return event.subscribed ? { kind: "on" } : { kind: "off" };
    case "start":
      return nextTarget(state) === event.target ? { kind: "busy", target: event.target } : state;
    case "done":
      return state.kind === "busy" ? { kind: state.target } : state;
    case "denied":
      return state.kind === "busy" ? { kind: "blocked" } : state;
    case "dismissed":
      return state.kind === "busy" ? { kind: state.target === "on" ? "off" : "on" } : state;
    case "failed":
      return state.kind === "busy"
        ? { kind: "error", was: state.target === "on" ? "off" : "on", problem: event.problem }
        : state;
  }
}

/**
 * Whether a tap may start a change. Both directions talk to the server, so
 * both need a connection; a change under way, a blocked or unsupported device
 * and the first look all leave the switch still.
 */
export function canToggle(state: ToggleState, online: boolean): boolean {
  return online && nextTarget(state) !== null;
}

/** Keys under `approvalsPush.status` (`locales/approvals/<lang>/push.json`). */
export type StatusKey =
  | "checking"
  | "off"
  | "on"
  | "working"
  | "blocked"
  | "unsupported"
  | "unsupportedIos"
  | "needsConnection"
  | "turnOnFailed"
  | "turnOffFailed";

/** The one line under the switch. `ios` gives the iPhone its own advice where the device is unsupported. */
export function statusKey(state: ToggleState, online: boolean, ios = false): StatusKey {
  switch (state.kind) {
    case "checking":
      return "checking";
    case "unsupported":
      return ios ? "unsupportedIos" : "unsupported";
    case "blocked":
      return "blocked";
    case "busy":
      return "working";
    case "error":
      if (state.problem === "offline") return "needsConnection";
      return state.was === "off" ? "turnOnFailed" : "turnOffFailed";
    case "on":
      return "on";
    case "off":
      return online ? "off" : "needsConnection";
  }
}
