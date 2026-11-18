/**
 * What went wrong with a call, in the three kinds the sheets treat differently.
 * Pure (reads the error's shape), so it needs no network layer. Every message
 * it hands on is plain text: the server's markup and entities are removed.
 *
 * - `server`: the server answered and said no (a rule, a state that changed).
 *   The sheet closes and the screen reloads; `message` is the server's own text.
 * - `network`: the call did not get through. The sheet stays open so what was
 *   typed is not lost; there is no message of our own, the screen words it.
 * - `unknown`: anything else; `message` is whatever the error carried.
 */
import { plainText } from "./plain-text";

export type Failure =
  | { kind: "server"; message: string }
  | { kind: "network"; message: "" }
  | { kind: "unknown"; message: string };

export function failureOf(error: unknown): Failure {
  const named = error as { name?: string; message?: string; serverMessage?: string } | null;
  if (named && named.name === "NetworkError") return { kind: "network", message: "" };
  if (named && named.name === "ApiError") {
    const said = plainText(named.serverMessage);
    // Without a readable server message, "HTTP 500" says nothing to an approver.
    return said ? { kind: "server", message: said } : { kind: "unknown", message: "" };
  }
  const text = error instanceof Error ? error.message : typeof error === "string" ? error : "";
  return { kind: "unknown", message: plainText(text) };
}

/**
 * What a sheet does with a failure, by what it was doing when it failed.
 *
 * - `file`: the server refused the FILE (type, size, permission). The sheet
 *   stays open, shows the words and keeps what was typed.
 * - `refused`: the server said no to the decision. The sheet closes, the
 *   screen shows the words and reloads.
 * - `unconfirmed`: the decision was sent and no answer came back (the
 *   connection dropped, the wait ran out, a gateway gave up). It may have gone
 *   through, so the sheet never offers Confirm again as if nothing happened:
 *   it closes, says the result could not be confirmed, and the screen reloads
 *   the document.
 * - `retry`: it did not get through or failed without telling why; safe to ask
 *   again (the sheet says what it can).
 */
export type SheetOutcome =
  | { kind: "file"; message: string }
  | { kind: "refused"; message: string }
  | { kind: "unconfirmed" }
  | { kind: "retry" };

/** A reverse proxy answering for a backend that is busy, restarting or too slow: the work may have finished. */
const GATEWAY_STATUSES = new Set([502, 503, 504]);

export function sheetOutcome(stage: "attach" | "apply", error: unknown): SheetOutcome {
  const failure = failureOf(error);
  if (stage === "attach") {
    return failure.kind === "server" ? { kind: "file", message: failure.message } : { kind: "retry" };
  }
  if (failure.kind === "server") return { kind: "refused", message: failure.message };
  if (failure.kind === "network") return { kind: "unconfirmed" };
  const status = (error as { status?: number } | null)?.status;
  if (typeof status === "number" && GATEWAY_STATUSES.has(status)) return { kind: "unconfirmed" };
  return { kind: "retry" };
}
