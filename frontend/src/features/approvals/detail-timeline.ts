/**
 * The review timeline: the approvers' workflow comments and the state
 * changes Permission Manager recorded, merged and newest first. Pure.
 */
import type { DetailComment, RouteEvent } from "@/api/approvals";

/**
 * A server timestamp as milliseconds, or null when it cannot be read.
 * Permission Manager writes "dd/MM/yy HH:mm"; ISO "yyyy-MM-dd HH:mm[:ss]" is
 * accepted too. Local time: only the order matters here.
 */
export function parseStamp(text: string): number | null {
  const value = (text ?? "").trim();
  let year: number;
  let month: number;
  let day: number;
  let rest: (string | undefined)[];

  let match = value.match(/^(\d{1,2})\/(\d{1,2})\/(\d{2}|\d{4})(?:[ T](\d{1,2}):(\d{2})(?::(\d{2}))?)?$/);
  if (match) {
    day = Number(match[1]);
    month = Number(match[2]);
    year = match[3].length === 2 ? 2000 + Number(match[3]) : Number(match[3]);
    rest = [match[4], match[5], match[6]];
  } else {
    match = value.match(/^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{1,2}):(\d{2})(?::(\d{2}))?)?/);
    if (!match) return null;
    year = Number(match[1]);
    month = Number(match[2]);
    day = Number(match[3]);
    rest = [match[4], match[5], match[6]];
  }
  const [hours, minutes, seconds] = rest.map((part) => (part === undefined ? 0 : Number(part)));
  const date = new Date(year, month - 1, day, hours, minutes, seconds);
  // A date that rolled over (31/02) is not a date.
  if (date.getFullYear() !== year || date.getMonth() !== month - 1 || date.getDate() !== day) return null;
  return date.getTime();
}

export type TimelineEntry =
  | { kind: "comment"; by: string; when: string; ts: number | null; text: string }
  | { kind: "event"; by: string; when: string; ts: number | null; from: string; to: string };

/** Comments and state changes together, newest first; undated ones keep their order, last. */
export function buildTimeline(comments: DetailComment[], events: RouteEvent[]): TimelineEntry[] {
  const entries: TimelineEntry[] = [
    ...comments.map(
      (comment): TimelineEntry => ({
        kind: "comment",
        by: comment.by,
        when: comment.when,
        ts: parseStamp(comment.when),
        text: comment.text,
      }),
    ),
    ...events.map(
      (event): TimelineEntry => ({
        kind: "event",
        by: event.by || event.user,
        when: event.on,
        ts: parseStamp(event.on),
        from: event.state,
        to: event.to_state,
      }),
    ),
  ];
  // Array.prototype.sort is stable: equal and undated entries keep their order.
  return entries.sort((a, b) => (b.ts ?? -Infinity) - (a.ts ?? -Infinity) || 0);
}
