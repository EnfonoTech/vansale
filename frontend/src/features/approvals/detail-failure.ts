/**
 * What went wrong with a call, in the three kinds the sheets treat differently.
 * Pure (reads the error's shape, imports nothing), so it needs no network layer.
 *
 * - `server`: the server answered and said no (a rule, a state that changed).
 *   The sheet closes and the screen reloads; `message` is the server's own text.
 * - `network`: the call did not get through. The sheet stays open so what was
 *   typed is not lost; there is no message of our own, the screen words it.
 * - `unknown`: anything else; `message` is whatever the error carried.
 */
export type Failure =
  | { kind: "server"; message: string }
  | { kind: "network"; message: "" }
  | { kind: "unknown"; message: string };

export function failureOf(error: unknown): Failure {
  const named = error as { name?: string; message?: string; serverMessage?: string } | null;
  if (named && named.name === "NetworkError") return { kind: "network", message: "" };
  if (named && named.name === "ApiError") {
    const said = (named.serverMessage ?? "").trim();
    // Without a readable server message, "HTTP 500" says nothing to an approver.
    return said ? { kind: "server", message: said } : { kind: "unknown", message: "" };
  }
  const text = error instanceof Error ? error.message : typeof error === "string" ? error : "";
  return { kind: "unknown", message: text.trim() };
}
