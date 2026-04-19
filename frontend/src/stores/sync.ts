/**
 * Sync store — lightweight facade over the queue counts and drain
 * engine. Views subscribe to this to show pending badges / error lists
 * without importing `offline/*` directly.
 */
import { defineStore } from "pinia";
import { totalPending } from "@/offline/queue";
import { drainAll, flagOrphans } from "@/offline/drain";
import { isOnline } from "@/app/online";

interface State {
  pending: number;
  lastDrainAt: number | null;
  lastError: string | null;
  draining: boolean;
}

export const useSyncStore = defineStore("sync", {
  state: (): State => ({ pending: 0, lastDrainAt: null, lastError: null, draining: false }),
  actions: {
    async refresh() {
      this.pending = await totalPending();
    },
    async requestDrain(): Promise<void> {
      if (this.draining || !isOnline()) return;
      this.draining = true;
      this.lastError = null;
      try {
        await flagOrphans();
        const res = await drainAll();
        this.lastDrainAt = Date.now();
        const totalFailed =
          res.invoices.failed + res.payments.failed + res.returns.failed + res.visits.failed;
        if (totalFailed > 0) this.lastError = `${totalFailed} entr${totalFailed === 1 ? "y" : "ies"} needs attention`;
      } catch (err) {
        this.lastError = err instanceof Error ? err.message : String(err);
      } finally {
        this.draining = false;
        await this.refresh();
      }
    },
  },
});
