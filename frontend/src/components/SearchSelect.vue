<script setup lang="ts" generic="T extends { value: string; label: string; sub?: string }">
/**
 * Searchable single-select for long lists.
 *
 * Replaces `<select>` where the option count is unbounded. A native select
 * with 200+ customers is unusable on a phone: no typing, no filtering, and on
 * Android it opens a full-screen scroll wheel the driver has to flick through
 * while a customer waits.
 *
 * Filtering is local over `options`; the parent may additionally hit the
 * server via `@search` (debounced here) so results are not capped by whatever
 * page size was preloaded. Local-only still works offline, which is the point.
 */
import { computed, nextTick, ref, watch } from "vue";
import Icon from "./Icon.vue";

const props = withDefaults(
  defineProps<{
    modelValue: string;
    options: T[];
    placeholder?: string;
    /** Emit `search` as the user types. Omit for purely local filtering. */
    remote?: boolean;
    disabled?: boolean;
  }>(),
  { placeholder: "Search…", remote: false, disabled: false },
);

const emit = defineEmits<{
  "update:modelValue": [value: string];
  search: [term: string];
}>();

const open = ref(false);
const term = ref("");
const inputEl = ref<HTMLInputElement | null>(null);

const selected = computed(() => props.options.find((o) => o.value === props.modelValue));

const filtered = computed(() => {
  const q = term.value.trim().toLowerCase();
  if (!q) return props.options.slice(0, 50);
  return props.options
    .filter((o) => o.label.toLowerCase().includes(q) || (o.sub ?? "").toLowerCase().includes(q))
    .slice(0, 50);
});

let timer: number | undefined;
watch(term, (t) => {
  if (!props.remote) return;
  // Debounced: a driver types faster than a 3G round trip completes, and
  // every keystroke firing a request makes the list flicker between
  // out-of-order responses.
  window.clearTimeout(timer);
  timer = window.setTimeout(() => emit("search", t.trim()), 300);
});

async function show() {
  if (props.disabled) return;
  open.value = true;
  term.value = "";
  await nextTick();
  inputEl.value?.focus();
}

function pick(o: T) {
  emit("update:modelValue", o.value);
  open.value = false;
}

function clear() {
  emit("update:modelValue", "");
  open.value = false;
}
</script>

<template>
  <div class="ss">
    <button type="button" class="ss-trigger" :disabled="props.disabled" @click="show">
      <span v-if="selected" class="ss-val truncate">{{ selected.label }}</span>
      <span v-else class="ss-ph">{{ props.placeholder }}</span>
      <Icon name="search" :size="16" />
    </button>

    <Teleport to="body">
      <div v-if="open" class="ss-sheet" @click.self="open = false">
        <div class="ss-panel">
          <div class="ss-search">
            <Icon name="search" :size="18" class="ss-ic" />
            <input
              ref="inputEl"
              v-model="term"
              type="search"
              :placeholder="props.placeholder"
              autocapitalize="none"
              autocorrect="off"
              spellcheck="false"
            />
            <button type="button" class="ss-close" @click="open = false">Cancel</button>
          </div>

          <ul class="ss-list">
            <li v-if="props.modelValue">
              <button type="button" class="ss-row ss-clear" @click="clear">Clear selection</button>
            </li>
            <li v-for="o in filtered" :key="o.value">
              <button
                type="button"
                class="ss-row"
                :class="{ 'is-active': o.value === props.modelValue }"
                @click="pick(o)"
              >
                <strong class="truncate">{{ o.label }}</strong>
                <span v-if="o.sub" class="muted xsmall truncate">{{ o.sub }}</span>
              </button>
            </li>
            <li v-if="!filtered.length" class="ss-empty muted small">No match</li>
          </ul>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.ss { width: 100%; }
.ss-trigger {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  padding: 0.6rem 0.7rem;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface);
  color: var(--text);
  font: inherit;
  text-align: start;
  min-height: 2.75rem;
}
.ss-trigger:disabled { opacity: 0.6; }
.ss-ph { color: var(--text-muted); }
.ss-val { font-weight: 600; }

.ss-sheet {
  position: fixed;
  inset: 0;
  z-index: 60;
  background: rgb(0 0 0 / 40%);
  display: flex;
  align-items: flex-end;
}
.ss-panel {
  width: 100%;
  max-height: 80dvh;
  display: flex;
  flex-direction: column;
  background: var(--bg);
  border-start-start-radius: var(--radius-lg);
  border-start-end-radius: var(--radius-lg);
  padding-bottom: env(safe-area-inset-bottom);
}
.ss-search {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.75rem;
  border-bottom: 1px solid var(--border);
}
.ss-search input { flex: 1; min-width: 0; }
.ss-ic { color: var(--text-muted); flex: none; }
.ss-close { all: unset; cursor: pointer; color: var(--primary); font-weight: 600; flex: none; }

.ss-list { list-style: none; margin: 0; padding: 0.25rem; overflow-y: auto; }
.ss-row {
  all: unset;
  cursor: pointer;
  display: flex;
  flex-direction: column;
  gap: 0.1rem;
  width: 100%;
  box-sizing: border-box;
  padding: 0.7rem;
  border-radius: var(--radius);
  min-height: 2.75rem;
}
.ss-row.is-active { background: var(--primary-soft); color: var(--primary); }
.ss-clear { color: var(--text-muted); }
.ss-empty { padding: 1.25rem; text-align: center; }
.truncate { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
</style>
