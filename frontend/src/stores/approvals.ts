/**
 * Approvals store: the inbox the Approvals screen shows, kept fresh.
 *
 * - The last inbox is saved per user on the phone. `refresh` shows that copy
 *   at once (marked `stale`) and then asks the server; offline it shows the
 *   copy and asks nothing.
 * - A decision that the server refuses reloads the inbox before the refusal
 *   is passed on: it usually means the document moved (someone else decided,
 *   it was recalled), and the list must not keep offering it.
 * - Polling every 60 s runs only while a screen asks for it (`startPolling`).
 * - Everything held here belongs to one user; it is dropped when another
 *   signs in, and on `reset()`.
 *
 * Approvals are never queued offline.
 */
import { defineStore } from "pinia";
import * as api from "@/api/approvals";
import type { ApprovalCount, HistoryRow, Inbox, MyRequestRow, SentBackRow } from "@/api/approvals";
import { clearApprovalsCache, loadInbox, saveInbox } from "@/features/approvals/cache";
import { isOnline } from "@/app/online";
import { useSessionStore } from "@/stores/session";

/** How often the open Approvals screen asks the server again. */
export const POLL_MS = 60_000;

interface State {
  inbox: Inbox | null;
  /** The numbers for badges: from the inbox, or from `refreshCount`. */
  counts: ApprovalCount | null;
  /** My requests, Sent back and History: filled by their tabs. */
  mine: MyRequestRow[];
  sentBack: SentBackRow[];
  history: HistoryRow[];
  loading: boolean;
  error: string | null;
  /** What is shown is the saved copy, or older than the last failed fetch. */
  stale: boolean;
  /** Who the data above belongs to. */
  owner: string | null;
}

function blank(): State {
  return {
    inbox: null,
    counts: null,
    mine: [],
    sentBack: [],
    history: [],
    loading: false,
    error: null,
    stale: false,
    owner: null,
  };
}

/** Bumped by every fetch, and by a reset or user change: only the latest answer may land. */
let fetchSeq = 0;
/** Stops the running poll (timer and listeners); null when none runs. */
let stopPoll: (() => void) | null = null;

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export const useApprovalsStore = defineStore("approvals", {
  state: (): State => blank(),
  getters: {
    /** Documents waiting on the user. */
    needsYou: (s): number => s.counts?.needs_you ?? 0,
    /** The number for the nav badge and the home card; 0 hides it. */
    badge(): number {
      return this.needsYou;
    },
  },
  actions: {
    /**
     * Take on `user`: what belongs to someone else is dropped first. Nothing
     * is dropped on the first call after a reset or a fresh start (nobody
     * owns anything yet, so whatever a tab already set is this user's).
     */
    adopt(user: string) {
      if (this.owner === user) return;
      if (this.owner === null) {
        this.owner = user;
        return;
      }
      fetchSeq++;
      this.$patch({ ...blank(), owner: user });
    },

    setInbox(inbox: Inbox) {
      this.inbox = inbox;
      this.counts = {
        total: inbox.total,
        needs_you: inbox.needs_you,
        waiting: inbox.waiting,
        high: inbox.stats.high,
        overdue: inbox.stats.overdue,
      };
    },

    async refresh(): Promise<void> {
      const session = useSessionStore();
      const user = session.user;
      if (!user) return;
      this.adopt(user);

      // The saved copy first: it is what an offline phone can show.
      if (!this.inbox) {
        const saved = loadInbox(user);
        if (saved) {
          this.setInbox(saved.inbox);
          this.stale = true;
        }
      }
      if (!isOnline()) {
        this.stale = this.inbox !== null;
        return;
      }

      const seq = ++fetchSeq;
      const current = () => seq === fetchSeq && session.user === user;
      this.loading = true;
      this.error = null;
      try {
        const fresh = await api.inbox();
        if (!current()) return;
        this.setInbox(fresh);
        this.stale = false;
        saveInbox(user, fresh);
      } catch (error) {
        if (!current()) return;
        this.error = messageOf(error);
        this.stale = this.inbox !== null;
      } finally {
        if (seq === fetchSeq) this.loading = false;
      }
    },

    /** Just the numbers, for a badge on a screen that does not list the inbox. */
    async refreshCount(): Promise<void> {
      const session = useSessionStore();
      const user = session.user;
      if (!user || !isOnline()) return;
      this.adopt(user);
      try {
        const counts = await api.count();
        if (this.owner !== user || session.user !== user) return;
        this.counts = counts;
      } catch {
        /* keep the last numbers */
      }
    },

    /**
     * Take `action` on one document, then reload the inbox. A refusal reloads
     * it too, before being thrown unchanged, so the list shows what is true.
     */
    async apply(
      doctype: string,
      name: string,
      action: string,
      comment: string,
      priority: string,
    ): Promise<void> {
      try {
        await api.apply(doctype, name, action, comment, priority);
      } catch (error) {
        await this.refresh();
        throw error;
      }
      await this.refresh();
    },

    /** Refresh every 60 s while the app is in front, and when it returns to the front or the network returns. */
    startPolling() {
      if (stopPoll) return;
      const tick = () => {
        void this.refresh();
      };
      const onVisible = () => {
        if (document.visibilityState === "visible") tick();
      };
      const timer = setInterval(() => {
        if (document.visibilityState !== "hidden") tick();
      }, POLL_MS);
      document.addEventListener("visibilitychange", onVisible);
      window.addEventListener("online", tick);
      stopPoll = () => {
        clearInterval(timer);
        document.removeEventListener("visibilitychange", onVisible);
        window.removeEventListener("online", tick);
      };
    },

    stopPolling() {
      stopPoll?.();
      stopPoll = null;
    },

    /** Forget everything: state, saved copy and the poll. */
    reset() {
      this.stopPolling();
      fetchSeq++;
      this.$patch(blank());
      clearApprovalsCache();
    },
  },
});
