<script setup lang="ts">
/**
 * Customer list — "sales ledger" layout.
 *
 * User feedback: the chromatic-avatar + alphabet-header layout read as a
 * phone contact book. Stripped that entirely — no avatars, no letter
 * sections. This is a working CRM list: dense, scannable, typographic.
 *
 * Visual direction:
 *  - Single flat list. Rows separated by hairlines, not cards.
 *  - Customer name in display face, tight letter-spacing.
 *  - Meta compressed into one middot-separated line (phone · territory · VAT).
 *  - Leading accent bar on hover/active to reinforce tap affordance
 *    without stealing attention from the name.
 *  - Floating action button for "New" so the header stays calm.
 *  - Result count is a quiet footer note, not a hero number.
 */
import { computed, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { listMine, fromCache, refreshCache, type CustomerRow } from "@/api/customer";
import { isOnline, useOnline } from "@/app/online";
import { NetworkError } from "@/app/frappe";
import Icon from "@/components/Icon.vue";

const router = useRouter();
const online = useOnline();
const rows = ref<CustomerRow[]>([]);
const search = ref("");
const err = ref("");
const source = ref<"live" | "cache">("live");
const loading = ref(false);

async function load() {
  err.value = "";

  // SWR: paint cache instantly (skips 2-3s of skeleton), then hit the
  // network. Search queries skip the cache — the cache contains the
  // unfiltered recent set, not search results.
  if (!search.value && rows.value.length === 0) {
    try {
      const cached = (await fromCache()).map((c) => c.raw as unknown as CustomerRow);
      if (cached.length > 0) {
        rows.value = cached;
        source.value = "cache";
      }
    } catch { /* cache miss is fine */ }
  }

  // Only show spinner when we have nothing on screen yet.
  loading.value = rows.value.length === 0;

  try {
    if (isOnline()) {
      rows.value = await listMine(search.value || undefined, 120);
      source.value = "live";
      // Fire-and-forget — don't block render on cache write.
      if (!search.value) void refreshCache();
    } else if (rows.value.length === 0) {
      rows.value = (await fromCache()).map((c) => c.raw as unknown as CustomerRow);
      source.value = "cache";
    }
  } catch (e) {
    if (e instanceof NetworkError) {
      if (rows.value.length === 0) {
        rows.value = (await fromCache()).map((c) => c.raw as unknown as CustomerRow);
        source.value = "cache";
      }
      err.value = "Offline — showing cached customers";
    } else {
      err.value = e instanceof Error ? e.message : String(e);
    }
  } finally {
    loading.value = false;
  }
}

onMounted(load);

let to: ReturnType<typeof setTimeout> | null = null;
watch(search, () => {
  if (to) clearTimeout(to);
  to = setTimeout(load, 250);
});

watch(online, (v) => { if (v) void load(); });

function openCustomer(c: CustomerRow) {
  void router.push({ name: "customer-detail", params: { name: c.name } });
}

const sorted = computed<CustomerRow[]>(() =>
  [...rows.value].sort((a, b) => a.customer_name.localeCompare(b.customer_name)),
);

const totalCount = computed(() => rows.value.length);
</script>

<template>
  <div class="stack screen">
    <header class="head">
      <div class="search-bar">
        <Icon name="search" :size="16" class="search-ic" />
        <input
          v-model="search"
          placeholder="Search customers, phone, VAT…"
          aria-label="Search customers"
          autocomplete="off"
        />
        <button
          v-if="search"
          type="button"
          class="clear"
          aria-label="Clear search"
          @click="search = ''"
        >
          <Icon name="x" :size="14" />
        </button>
      </div>
    </header>

    <p v-if="source === 'cache'" class="offline-hint">
      <Icon name="wifi-off" :size="14" />
      Offline — showing cached customers.
    </p>
    <p v-if="err" class="error">{{ err }}</p>

    <div v-if="loading && totalCount === 0" class="stack">
      <div class="skeleton" style="height: 3rem" />
      <div class="skeleton" style="height: 3rem" />
      <div class="skeleton" style="height: 3rem" />
      <div class="skeleton" style="height: 3rem" />
    </div>

    <div v-else-if="totalCount === 0" class="empty">
      <Icon name="customer" :size="32" class="empty-icon" />
      <strong>No customers found</strong>
      <span>{{ search ? "Try a different search term." : "Ask your admin to add customers to this company." }}</span>
    </div>

    <ul v-else class="ledger">
      <li v-for="c in sorted" :key="c.name" class="row">
        <button
          type="button"
          class="row-btn"
          @click="openCustomer(c)"
          :aria-label="`Open customer ${c.customer_name}`"
        >
          <span class="accent" aria-hidden="true" />
          <span class="content">
            <strong class="name">{{ c.customer_name }}</strong>
            <span class="meta">
              <span v-if="c.mobile_no" class="meta-item">{{ c.mobile_no }}</span>
              <span v-if="c.mobile_no && (c.territory || c.tax_id)" class="sep">·</span>
              <span v-if="c.territory" class="meta-item">{{ c.territory }}</span>
              <span v-if="c.territory && c.tax_id" class="sep">·</span>
              <span v-if="c.tax_id" class="meta-item mono">VAT {{ c.tax_id }}</span>
              <span v-if="!c.mobile_no && !c.territory && !c.tax_id" class="meta-item muted">{{ c.name }}</span>
            </span>
          </span>
          <Icon name="chevron-right" :size="16" class="chev" />
        </button>
      </li>
    </ul>

    <p v-if="totalCount > 0" class="footnote">
      {{ totalCount }} {{ totalCount === 1 ? "customer" : "customers" }}
      <span v-if="search"> · filtered</span>
    </p>

    <button
      type="button"
      class="fab"
      aria-label="New customer"
      @click="router.push({ name: 'customer-new' })"
    >
      <Icon name="plus" :size="20" />
    </button>
  </div>
</template>

<style scoped>
.screen { position: relative; padding-bottom: 5.5rem; }

.head { padding: 0.1rem 0 0.3rem; }

.search-bar { position: relative; }
.search-ic {
  position: absolute;
  inset-inline-start: 0.85rem;
  top: 50%;
  transform: translateY(-50%);
  color: var(--text-faint);
  pointer-events: none;
}
.search-bar input {
  padding-inline-start: 2.35rem;
  padding-inline-end: 2.35rem;
  min-height: 2.6rem;
  background: var(--surface);
  border-radius: var(--radius);
  border: 1px solid var(--border);
}
.search-bar input:focus-visible {
  border-color: var(--primary);
  box-shadow: 0 0 0 3px var(--primary-soft);
}
.clear {
  all: unset;
  position: absolute;
  inset-inline-end: 0.55rem;
  top: 50%;
  transform: translateY(-50%);
  width: 1.6rem;
  height: 1.6rem;
  border-radius: var(--radius-pill);
  background: var(--surface-sunk);
  color: var(--text-muted);
  display: grid;
  place-items: center;
  cursor: pointer;
}

.offline-hint {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.3rem 0.6rem;
  background: var(--warning-soft);
  color: var(--warning);
  border-radius: var(--radius-pill);
  font-size: var(--text-xs);
  align-self: flex-start;
  margin: 0;
}

.ledger {
  list-style: none;
  padding: 0;
  margin: 0;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
}
.row + .row { border-top: 1px solid var(--border); }

.row-btn {
  all: unset;
  display: grid;
  grid-template-columns: auto 1fr auto;
  align-items: center;
  width: 100%;
  padding: 0.7rem 0.85rem 0.7rem 0;
  cursor: pointer;
  transition: background var(--dur-fast) var(--ease);
  box-sizing: border-box;
}
.row-btn:hover, .row-btn:focus-visible { background: var(--surface-muted); }
.row-btn:active { background: var(--surface-sunk); }

.accent {
  width: 3px;
  height: 2rem;
  margin-inline-end: 0.75rem;
  border-radius: 0 2px 2px 0;
  background: transparent;
  transition: background var(--dur-fast) var(--ease);
}
.row-btn:hover .accent,
.row-btn:focus-visible .accent,
.row-btn:active .accent { background: var(--primary); }

.content {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
  min-width: 0;
}
.name {
  font-family: var(--font-display);
  font-size: var(--text-base);
  font-weight: 600;
  letter-spacing: -0.012em;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  color: var(--text);
}
.meta {
  display: flex;
  align-items: baseline;
  gap: 0.3rem;
  font-size: var(--text-xs);
  color: var(--text-muted);
  flex-wrap: wrap;
  line-height: 1.35;
}
.meta-item { white-space: nowrap; }
.meta-item.muted { color: var(--text-faint); }
.meta-item.mono { font-variant-numeric: tabular-nums; }
.sep { color: var(--text-faint); }

.chev { color: var(--text-faint); }

.footnote {
  margin: 0.1rem 0 0;
  padding-inline: 0.2rem;
  font-size: var(--text-xs);
  color: var(--text-faint);
  letter-spacing: 0.02em;
}

.fab {
  position: fixed;
  inset-inline-end: 1rem;
  bottom: calc(var(--bottom-nav-height) + 1rem + var(--safe-bottom));
  width: 3.5rem;
  height: 3.5rem;
  border-radius: var(--radius-pill);
  background: var(--primary);
  color: var(--primary-ink);
  display: grid;
  place-items: center;
  cursor: pointer;
  border: none;
  box-shadow: var(--shadow-float);
  transition: transform var(--dur-fast) var(--ease);
  z-index: 5;
}
.fab:active { transform: scale(0.94); }
</style>
