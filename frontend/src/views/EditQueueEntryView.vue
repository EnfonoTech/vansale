<script setup lang="ts">
/**
 * Edit-a-queued-entry view.
 *
 * Last-resort recovery path for validation / not-found failures: if
 * the server rejected an offline save because a field was wrong (bad
 * tax_id, missing address, stale item_code), the user needs a way to
 * fix the payload without losing the entry. Dismiss + re-enter is too
 * punitive when a van driver has already walked the route.
 *
 * Deliberate trade-off: MVP is a JSON editor. Power users / managers
 * can patch the payload directly; regular users still have Dismiss as
 * the "give up" escape hatch. Per-store structured forms (line items
 * grid for invoices, etc.) are a future iteration once we know which
 * fields actually break in the field.
 *
 * On save we clear `lastError`, `errorKind`, and `nextAttemptAt` and
 * reset `attempts` to 0 so the drain engine treats the edited entry
 * as a fresh submission. The `clientId` is preserved so server-side
 * idempotency still applies — two devices racing won't duplicate.
 */
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { db, type QueueStoreName } from "@/offline/db";
import { useSyncStore } from "@/stores/sync";

const props = defineProps<{ store: string; id: string }>();

const router = useRouter();
const sync = useSyncStore();

const store = computed<QueueStoreName>(() => props.store as QueueStoreName);
const entryId = computed<number>(() => Number(props.id));

type RawEntry = {
  id?: number;
  clientId: string;
  clientTs: string;
  createdAt: number;
  attempts: number;
  lastError?: string;
  errorKind?: string;
  nextAttemptAt?: number;
  status?: "pending" | "draining" | "dismissed";
  payload: Record<string, unknown>;
  [extra: string]: unknown;
};

const entry = ref<RawEntry | null>(null);
const jsonText = ref<string>("");
const parseError = ref<string>("");
const saveError = ref<string>("");
const saving = ref<boolean>(false);

async function load() {
  const d = await db();
  const row = (await (d.get as (s: QueueStoreName, k: number) => Promise<unknown>)(
    store.value,
    entryId.value,
  )) as RawEntry | undefined;
  if (!row) {
    entry.value = null;
    return;
  }
  entry.value = row;
  jsonText.value = JSON.stringify(row.payload ?? {}, null, 2);
}

onMounted(load);

async function save() {
  if (!entry.value) return;
  parseError.value = "";
  saveError.value = "";
  let parsed: Record<string, unknown>;
  try {
    const raw = JSON.parse(jsonText.value);
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
      parseError.value = "Payload must be a JSON object";
      return;
    }
    parsed = raw as Record<string, unknown>;
  } catch (err) {
    parseError.value = err instanceof Error ? err.message : String(err);
    return;
  }

  saving.value = true;
  try {
    const d = await db();
    const next: RawEntry = {
      ...entry.value,
      payload: parsed,
      // Reset drain state so the next cycle treats this as a new try.
      attempts: 0,
      lastError: undefined,
      errorKind: undefined,
      nextAttemptAt: undefined,
      status: "pending",
    };
    // Strip undefined keys — idb/IDB writes them as `undefined` which
    // keeps the bad state visible in the UI after save.
    for (const k of Object.keys(next) as Array<keyof RawEntry>) {
      if (next[k] === undefined) delete next[k];
    }
    await (d.put as (s: QueueStoreName, v: unknown) => Promise<IDBValidKey>)(store.value, next);
    await sync.refresh();
    // Kick a drain so the user sees the result immediately if online.
    void sync.requestDrain();
    await router.push({ name: "sync-errors" });
  } catch (err) {
    saveError.value = err instanceof Error ? err.message : String(err);
  } finally {
    saving.value = false;
  }
}

function cancel() {
  void router.push({ name: "sync-errors" });
}
</script>

<template>
  <section class="card stack">
    <header class="head">
      <h1>Edit queued entry</h1>
      <button class="ghost" @click="cancel">Cancel</button>
    </header>

    <div v-if="!entry" class="muted small">
      Entry not found. It may have already synced — go back to the sync queue.
    </div>

    <template v-else>
      <dl class="meta">
        <div><dt>Store</dt><dd>{{ store }}</dd></div>
        <div><dt>Client ID</dt><dd class="mono">{{ entry.clientId }}</dd></div>
        <div><dt>Attempts</dt><dd>{{ entry.attempts }}</dd></div>
        <div v-if="entry.lastError">
          <dt>Last error</dt><dd class="error">{{ entry.lastError }}</dd>
        </div>
      </dl>

      <label class="field stack">
        <span>Payload (JSON)</span>
        <textarea v-model="jsonText" rows="16" class="mono" spellcheck="false" />
      </label>
      <p v-if="parseError" class="error">Invalid JSON: {{ parseError }}</p>
      <p v-if="saveError" class="error">Save failed: {{ saveError }}</p>

      <div class="footer">
        <button class="ghost" @click="cancel" :disabled="saving">Cancel</button>
        <button @click="save" :disabled="saving">
          {{ saving ? "Saving…" : "Save & retry" }}
        </button>
      </div>
    </template>
  </section>
</template>

<style scoped>
.head {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 0.5rem;
}
.meta {
  display: grid;
  grid-template-columns: max-content 1fr;
  column-gap: 0.75rem;
  row-gap: 0.25rem;
  font-size: 0.88rem;
}
.meta > div {
  display: contents;
}
.meta dt {
  color: var(--text-muted);
  font-weight: 600;
}
.meta dd {
  margin: 0;
}
.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 0.85rem;
}
textarea.mono {
  width: 100%;
  padding: 0.6rem;
  border: 1px solid var(--border, #d1d5db);
  border-radius: var(--radius);
  background: var(--bg-muted, #f9fafb);
  resize: vertical;
}
.footer {
  display: flex;
  justify-content: flex-end;
  gap: 0.5rem;
}
.small {
  font-size: 0.85rem;
}
</style>
