/**
 * The last inbox the app fetched, kept on the phone so the list can still be
 * read without a connection. It holds one user's copy only: a read for anyone
 * else finds nothing, a save for another user replaces it, and logout clears
 * it. Every storage access is guarded (private windows and full storage throw).
 */
import type { Inbox } from "@/api/approvals";

const KEY = "vansale.approvals.cache.v1";

interface Stored {
  user: string;
  savedAt: string;
  inbox: Inbox;
}

export function saveInbox(user: string, inbox: Inbox): void {
  try {
    const stored: Stored = { user, savedAt: new Date().toISOString(), inbox };
    window.localStorage.setItem(KEY, JSON.stringify(stored));
  } catch {
    /* storage full or unavailable: the screen just has no offline copy */
  }
}

/** `user`'s saved inbox and when it was saved, or null (none, someone else's, unreadable). */
export function loadInbox(user: string): { inbox: Inbox; savedAt: string } | null {
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return null;
    const stored = JSON.parse(raw) as Partial<Stored> | null;
    if (!stored || typeof stored !== "object" || stored.user !== user) return null;
    if (typeof stored.savedAt !== "string" || !isInbox(stored.inbox)) return null;
    return { inbox: stored.inbox, savedAt: stored.savedAt };
  } catch {
    return null;
  }
}

export function clearApprovalsCache(): void {
  try {
    window.localStorage.removeItem(KEY);
  } catch {
    /* nothing to clear if storage is unavailable */
  }
}

/** Enough of the shape that the screen cannot crash on a damaged copy. */
function isInbox(value: unknown): value is Inbox {
  const inbox = value as Partial<Inbox> | null;
  return (
    !!inbox &&
    typeof inbox === "object" &&
    Array.isArray(inbox.sections) &&
    Array.isArray(inbox.waiting_items) &&
    typeof inbox.needs_you === "number"
  );
}
