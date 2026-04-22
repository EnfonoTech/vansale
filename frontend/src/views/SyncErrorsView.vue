<script setup lang="ts">
/**
 * Pending & errors view.
 *
 * Shows every non-dismissed queued operation — whether it has attempted
 * yet or not. This replaces the "errors-only" list so the user can
 * inspect ALL offline work in flight (§ offline-hardening roadmap).
 *
 * Rendering is driven by `describeQueueEntry` so the view stays thin:
 * classify + age formatting + retry/edit eligibility are decided in the
 * pure helper and covered by unit tests.
 */
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { useSyncStore } from "@/stores/sync";
import {
  listAllPending,
  describeQueueEntry,
  type EntryDescriptor,
  type PendingEntry,
} from "@/offline/observability";
import { purgeDismissed, queueUtilization } from "@/offline/capacity";
import { db, type QueueStoreName } from "@/offline/db";

const rows = ref<EntryDescriptor[]>([]);
const raw = ref<PendingEntry[]>([]);
const now = ref<number>(Date.now());
const util = ref<Awaited<ReturnType<typeof queueUtilization>> | null>(null);
const sync = useSyncStore();
const router = useRouter();

async function load() {
  now.value = Date.now();
  const pending = await listAllPending();
  raw.value = pending;
  rows.value = pending.map((e) =>
    describeQueueEntry(
      e.store,
      {
        id: e.id,
        clientId: e.clientId,
        clientTs: e.clientTs,
        createdAt: e.createdAt,
        attempts: e.attempts,
        lastError: e.lastError,
        errorKind: e.errorKind,
        nextAttemptAt: e.nextAttemptAt,
        payload: e.payload,
      },
      now.value,
    ),
  );
  util.value = await queueUtilization();
}

onMounted(load);

async function dismiss(row: EntryDescriptor) {
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

async function purge() {
  const n = await purgeDismissed();
  if (n > 0) await load();
}

function edit(row: EntryDescriptor) {
  void router.push({
    name: "sync-edit-entry",
    params: { store: row.store, id: String(row.id) },
  });
}

const atCap = computed(() =>
  util.value
    ? Object.values(util.value).some((u) => u.atCap)
    : false,
);
const nearCap = computed(() =>
  util.value
    ? Object.values(util.value).some((u) => u.nearCap && !u.atCap)
    : false,
);

function kindLabel(kind: EntryDescriptor["kind"]): string {
  switch (kind) {
    case "pending":
      return "Queued";
    case "network":
      return "Retrying";
    case "idempotent-replay":
      return "Already saved";
    case "permission":
      return "Not permitted";
    case "not-found":
      return "Reference missing";
    case "validation":
      return "Needs edit";
    case "unknown":
    default:
      return "Error";
  }
}

function kindTone(kind: EntryDescriptor["kind"]): string {
  if (kind === "pending" || kind === "network") return "info";
  if (kind === "permission") return "danger";
  if (kind === "validation" || kind === "not-found") return "warn";
  return "warn";
}
</script>

<template>
  <section class="card stack">
    <header class="head">
      <h1>Sync queue</h1>
      <span class="muted small" v-if="rows.length === 0">Everything is in sync.</span>
      <span class="muted small" v-else>{{ rows.length }} item{{ rows.length === 1 ? "" : "s" }} pending</span>
    </header>

    <div v-if="atCap" class="banner danger">
      Queue is at its cap — drain online before you create more entries.
    </div>
    <div v-else-if="nearCap" class="banner warn">
      Queue is nearly full — go online soon to drain.
    </div>

    <ul v-if="rows.length > 0" class="stack" style="padding: 0; list-style: none; margin: 0">
      <li v-for="row in rows" :key="`${row.store}:${row.id}`" class="row">
        <div class="row-head">
          <strong>{{ row.summary }}</strong>
          <span class="chip" :data-tone="kindTone(row.kind)">{{ kindLabel(row.kind) }}</span>
        </div>
        <div class="row-meta">
          <span class="muted small">{{ row.age }}</span>
          <span v-if="row.attempts > 0" class="muted small">· {{ row.attempts }} attempt{{ row.attempts === 1 ? "" : "s" }}</span>
          <span v-if="row.cooldown" class="muted small">· {{ row.cooldown }}</span>
        </div>
        <p v-if="row.errorMessage" class="error">{{ row.errorMessage }}</p>
        <div class="actions">
          <button v-if="row.canRetry" class="ghost" @click="retryAll">Retry</button>
          <button v-if="row.canEdit" class="ghost" @click="edit(row)">Edit</button>
          <button class="ghost" @click="dismiss(row)">Dismiss</button>
        </div>
      </li>
    </ul>

    <div class="footer" v-if="rows.length > 0">
      <button @click="retryAll">Retry all</button>
      <button class="ghost" @click="purge">Purge dismissed</button>
    </div>
  </section>
</template>

<style scoped>
.head {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
}
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
  align-items: center;
}
.row-meta {
  display: flex;
  gap: 0.3rem;
  flex-wrap: wrap;
}
.actions {
  display: flex;
  gap: 0.5rem;
  margin-top: 0.2rem;
}
.footer {
  display: flex;
  justify-content: space-between;
  gap: 0.5rem;
  margin-top: 0.2rem;
}
.small {
  font-size: 0.8rem;
}
.chip {
  padding: 0.1rem 0.55rem;
  border-radius: 999px;
  font-size: 0.68rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  background: var(--bg-muted, #eef2f7);
  color: var(--text-muted);
}
.chip[data-tone="info"] {
  background: #e0ebff;
  color: #1e40af;
}
.chip[data-tone="warn"] {
  background: #fef3c7;
  color: #92400e;
}
.chip[data-tone="danger"] {
  background: #fee2e2;
  color: #991b1b;
}
.banner {
  padding: 0.55rem 0.75rem;
  border-radius: var(--radius);
  font-size: 0.85rem;
}
.banner.danger {
  background: #fee2e2;
  color: #991b1b;
}
.banner.warn {
  background: #fef3c7;
  color: #92400e;
}
</style>
