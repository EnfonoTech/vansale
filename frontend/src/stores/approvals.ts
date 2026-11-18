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

/** The three list tabs the store holds besides the inbox. */
export type ListName = "mine" | "sentBack" | "history";

/** Where one list tab stands; the inbox keeps its own `loading` and `error`. */
export interface ListStatus {
  loading: boolean;
  error: string | null;
  /** An answer has arrived at least once: an empty list is then really empty. */
  loaded: boolean;
}

/** What the History tab narrows by; every part is optional. */
export interface HistoryFilters {
  /** YYYY-MM-DD. */
  fromDate?: string;
  /** YYYY-MM-DD. */
  toDate?: string;
  /** A row's `transaction_filter`. */
  transaction?: string;
  /** Page size; the server's default is 100. */
  limit?: number;
}

interface State {
  inbox: Inbox | null;
  /** The numbers for badges: from the inbox, or from `refreshCount`. */
  counts: ApprovalCount | null;
  /** My requests, Sent back and History: filled by their tabs. */
  mine: MyRequestRow[];
  sentBack: SentBackRow[];
  history: HistoryRow[];
  /** Loading and error of each list tab (kept apart from the inbox's). */
  lists: Record<ListName, ListStatus>;
  loading: boolean;
  error: string | null;
  /** What is shown is the saved copy, or older than the last failed fetch. */
  stale: boolean;
  /** Who the data above belongs to. */
  owner: string | null;
}

function blankList(): ListStatus {
  return { loading: false, error: null, loaded: false };
}

function blank(): State {
  return {
    inbox: null,
    counts: null,
    mine: [],
    sentBack: [],
    history: [],
    lists: { mine: blankList(), sentBack: blankList(), history: blankList() },
    loading: false,
    error: null,
    stale: false,
    owner: null,
  };
}

/** Bumped by every fetch, and by a reset or user change: only the latest answer may land. */
let fetchSeq = 0;
/** The same for each list tab, so a tab's answer never lands on the inbox's sequence or another tab's. */
const listSeq: Record<ListName, number> = { mine: 0, sentBack: 0, history: 0 };
/** Stops the running poll (timer and listeners); null when none runs. */
let stopPoll: (() => void) | null = null;

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

/** Drop every list answer still on its way (a reset, or another user). */
function dropListAnswers(): void {
  listSeq.mine++;
  listSeq.sentBack++;
  listSeq.history++;
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
      dropListAnswers();
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

    /**
     * Fetch one list tab into its slot. Offline it asks nothing and keeps what
     * it holds (these tabs are not saved on the phone). A failure keeps the
     * rows already shown and records the message; the tab offers a retry. Only
     * the latest answer of a tab lands, and none after a reset or user change.
     */
    async loadList<T>(name: ListName, call: () => Promise<T>, assign: (value: T) => void): Promise<void> {
      const session = useSessionStore();
      const user = session.user;
      if (!user) return;
      this.adopt(user);
      if (!isOnline()) return;

      const seq = ++listSeq[name];
      const current = () => seq === listSeq[name] && session.user === user;
      this.lists[name].loading = true;
      this.lists[name].error = null;
      try {
        const value = await call();
        if (!current()) return;
        assign(value);
        this.lists[name].loaded = true;
      } catch (error) {
        if (!current()) return;
        this.lists[name].error = messageOf(error);
      } finally {
        if (seq === listSeq[name]) this.lists[name].loading = false;
      }
    },

    /** My requests: the documents the user raised that are still in approval. */
    loadMine(): Promise<void> {
      return this.loadList("mine", api.myRequests, (res) => {
        this.mine = res.items ?? [];
      });
    },

    /** Sent back: the documents returned to the user for correction. */
    loadSentBack(): Promise<void> {
      return this.loadList("sentBack", api.sentBack, (res) => {
        this.sentBack = res.items ?? [];
      });
    },

    /** History: the user's decisions, narrowed by `filters`. */
    loadHistory(filters: HistoryFilters = {}): Promise<void> {
      const { fromDate = "", toDate = "", transaction = "", limit = 100 } = filters;
      return this.loadList("history", () => api.history(limit, fromDate, toDate, transaction), (res) => {
        this.history = res.items ?? [];
      });
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
      dropListAnswers();
      this.$patch(blank());
      clearApprovalsCache();
    },
  },
});
