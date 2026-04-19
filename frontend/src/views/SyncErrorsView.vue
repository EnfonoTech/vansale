<script setup lang="ts">
import { onMounted, ref } from "vue";
import { db, type QueueStoreName } from "@/offline/db";
import { useSyncStore } from "@/stores/sync";

interface Row {
  store: QueueStoreName;
  id: number;
  clientId: string;
  clientTs: string;
  attempts: number;
  lastError?: string;
  summary: string;
}

const rows = ref<Row[]>([]);
const sync = useSyncStore();

function summarise(store: QueueStoreName, payload: Record<string, unknown>): string {
  if (store === "invoice_queue") return `Invoice for ${String(payload.customer ?? "—")}`;
  if (store === "payment_queue") return `Payment against ${String(payload.invoice_name ?? payload.customer ?? "—")}`;
  if (store === "return_queue") return `Return against ${String(payload.original_invoice ?? "—")}`;
  if (store === "visit_queue") return `Visit ${String(payload.stop_name ?? payload.customer ?? "—")}`;
  return store;
}

async function load() {
  const d = await db();
  const out: Row[] = [];
  for (const store of [
    "invoice_queue",
    "payment_queue",
    "return_queue",
    "visit_queue",
  ] as const) {
    const all = (await (d.getAll as (s: typeof store) => Promise<unknown[]>)(store)) as Array<{
      id?: number;
      clientId: string;
      clientTs: string;
      attempts: number;
      lastError?: string;
      payload: Record<string, unknown>;
    }>;
    for (const e of all) {
      if (typeof e.id !== "number") continue;
      if (!e.lastError && e.attempts === 0) continue;
      out.push({
        store,
        id: e.id,
        clientId: e.clientId,
        clientTs: e.clientTs,
        attempts: e.attempts,
        lastError: e.lastError,
        summary: summarise(store, e.payload),
      });
    }
  }
  rows.value = out;
}

onMounted(load);

async function dismiss(row: Row) {
  const d = await db();
  const fresh = (await (d.get as (s: QueueStoreName, k: number) => Promise<unknown>)(
    row.store,
    row.id,
  )) as { id?: number; status?: string } | undefined;
  if (fresh) {
    fresh.status = "dismissed";
    await (d.put as (s: QueueStoreName, v: unknown) => Promise<IDBValidKey>)(row.store, fresh);
  }
  await load();
  await sync.refresh();
}

async function retryAll() {
  await sync.requestDrain();
  await load();
}
</script>

<template>
  <section class="card stack">
    <h1>Sync errors</h1>
    <p v-if="rows.length === 0" class="muted">Everything is in sync.</p>
    <ul v-else class="stack" style="padding: 0; list-style: none">
      <li v-for="row in rows" :key="`${row.store}:${row.id}`" class="row">
        <div class="row-head">
          <strong>{{ row.summary }}</strong>
          <span class="muted small">{{ new Date(row.clientTs).toLocaleString() }}</span>
        </div>
        <p v-if="row.lastError" class="error">{{ row.lastError }}</p>
        <p class="muted small">Attempts: {{ row.attempts }}</p>
        <button class="ghost" @click="dismiss(row)">Dismiss (will not retry)</button>
      </li>
    </ul>
    <button v-if="rows.length > 0" @click="retryAll">Retry all</button>
  </section>
</template>

<style scoped>
.row {
  background: var(--surface);
  padding: 0.75rem;
  border-radius: var(--radius);
  box-shadow: var(--shadow-sm);
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
}
.row-head {
  display: flex;
  justify-content: space-between;
  gap: 0.5rem;
  align-items: flex-start;
}
.small {
  font-size: 0.8rem;
}
</style>
