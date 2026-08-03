/**
 * Classify a drain failure into an actionable category.
 *
 * Keeps the drain engine free of string-matching spaghetti — drain just
 * dispatches on `kind`:
 *   - `network`             → silent retry (no user alert)
 *   - `idempotent-replay`   → server already has this clientId, treat
 *                             as success (delete queue entry)
 *   - `permission`          → hard-stop, user must contact admin
 *   - `not-found` / `validation` → user needs to edit + retry
 *   - `unknown`             → default retryable bucket
 *
 * Regex set is deliberately narrow (§4.5 rule 5 — bare substrings match
 * harmless messages). If a new server error emerges, add a case here
 * with a covering test, not ad-hoc string checks in drain.ts.
 */
import { ApiError, NetworkError } from "@/app/frappe";

export type ErrorKind =
  | "network"
  | "idempotent-replay"
  | "permission"
  | "not-found"
  | "validation"
  | "blocked"
  | "unknown";

export interface ClassifiedError {
  kind: ErrorKind;
  /** Safe to auto-retry on next drain pass. */
  retryable: boolean;
  /** Drain should delete the entry — server confirms success. */
  treatAsSuccess: boolean;
  /** Show the reason to the user; `network` is silent. */
  userFacing: boolean;
  /** User should edit the queued payload before retry makes sense. */
  requiresEdit: boolean;
  /** Normalised message to display in the sync-errors view. */
  message: string;
}

// "has already been submitted" / "already exists" — allow up to a couple
// intervening words between the keywords.
const IDEMPOTENT = [
  /already\b[\s\S]{0,20}\bsubmitted/i,
  /duplicate\s+client_id/i,
  /already\s+exists/i,
];
const PERMISSION = [/not\s+permitted/i, /permission/i, /forbidden/i];
const NOT_FOUND = [/not\s+found/i, /does\s+not\s+exist/i];
// Backend data/setup faults. The van user CANNOT fix these by editing the
// queued payload — an admin has to set the item's valuation rate or post
// the stock into the van warehouse. Must be tested BEFORE `VALIDATION`,
// whose /required/i also matches "Valuation Rate ... is required to do
// accounting entries". Misfiling these as `validation` is what left a
// 102-day-old invoice in the queue with an Edit button that could never
// resolve it.
const BLOCKED = [
  /valuation\s+rate/i,
  /negative\s+stock/i,
  /(not\s+enough|insufficient)\s+stock/i,
];
const VALIDATION = [/mandatory/i, /missing/i, /invalid/i, /required/i];

function extractMessage(err: unknown): string {
  if (err instanceof ApiError) return err.serverMessage ?? err.message;
  if (err instanceof Error) return err.message;
  return String(err);
}

export function classifyError(err: unknown): ClassifiedError {
  if (err instanceof NetworkError) {
    return {
      kind: "network",
      retryable: true,
      treatAsSuccess: false,
      userFacing: false,
      requiresEdit: false,
      message: err.message || "Offline",
    };
  }

  const msg = extractMessage(err);

  if (IDEMPOTENT.some((re) => re.test(msg))) {
    return {
      kind: "idempotent-replay",
      retryable: false,
      treatAsSuccess: true,
      userFacing: false,
      requiresEdit: false,
      message: msg,
    };
  }
  if (PERMISSION.some((re) => re.test(msg))) {
    return {
      kind: "permission",
      retryable: false,
      treatAsSuccess: false,
      userFacing: true,
      requiresEdit: false,
      message: msg,
    };
  }
  if (NOT_FOUND.some((re) => re.test(msg))) {
    return {
      kind: "not-found",
      retryable: false,
      treatAsSuccess: false,
      userFacing: true,
      requiresEdit: true,
      message: msg,
    };
  }
  if (BLOCKED.some((re) => re.test(msg))) {
    return {
      kind: "blocked",
      retryable: false,
      treatAsSuccess: false,
      userFacing: true,
      requiresEdit: false,
      message: msg,
    };
  }
  if (VALIDATION.some((re) => re.test(msg))) {
    return {
      kind: "validation",
      retryable: false,
      treatAsSuccess: false,
      userFacing: true,
      requiresEdit: true,
      message: msg,
    };
  }
  return {
    kind: "unknown",
    retryable: true,
    treatAsSuccess: false,
    userFacing: true,
    requiresEdit: false,
    message: msg,
  };
}
