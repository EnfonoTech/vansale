<script setup lang="ts">
/**
 * Customer statement rendered in-app via `v-html`.
 *
 * Why not `window.open('/api/method/…')`? On the Capacitor APK the WebView
 * serves from `https://localhost`, so a relative method URL never reaches
 * trading-demo.enfonoerp.com. The JSON endpoint + `apiCall` goes through
 * the same auth path as every other request, back-button is native router
 * (TopAppBar), and print uses `window.print()` inside an iframe so the
 * host chrome doesn't hijack it.
 */
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";
import { statement, downloadStatementPdf } from "@/api/customer";
import { ApiError, NetworkError } from "@/app/frappe";
import { useToastStore } from "@/stores/toasts";
import Icon from "@/components/Icon.vue";

const toasts = useToastStore();

const route = useRoute();
const customerName = computed(() => String(route.params.name ?? ""));

const html = ref("");
const loading = ref(false);
const err = ref("");
const iframe = ref<HTMLIFrameElement | null>(null);
const fromDate = ref("");
const toDate = ref("");
const downloading = ref(false);

async function load() {
  if (!customerName.value) return;
  loading.value = true;
  err.value = "";
  try {
    const res = await statement(
      customerName.value,
      fromDate.value || undefined,
      toDate.value || undefined,
    );
    html.value = res.html ?? "";
  } catch (e) {
    if (e instanceof ApiError) {
      // Backend without the JSON endpoint raises "Method Not Found" /
      // "AttributeError"; surface a clear instruction to the operator
      // instead of the raw stack trace.
      const sm = e.serverMessage ?? "";
      if (/method|attribute|not found/i.test(sm) || e.status === 404) {
        err.value = "Server needs an update — statement endpoint not available yet. Contact your admin.";
      } else {
        err.value = sm || "Could not load statement";
      }
    } else if (e instanceof NetworkError) {
      err.value = "You're offline — statement needs a connection";
    } else {
      err.value = e instanceof Error ? e.message : String(e);
    }
  } finally {
    loading.value = false;
  }
}

/**
 * Print via iframe contentWindow so we only print the statement body, not
 * the surrounding app shell (bottom nav, top bar, etc.). `focus()` first
 * is required on Chrome — otherwise `print()` targets the outer frame.
 */
function printStatement() {
  const frame = iframe.value;
  if (!frame || !frame.contentWindow) return;
  frame.contentWindow.focus();
  frame.contentWindow.print();
}

async function saveAsPdf() {
  if (downloading.value) return;
  downloading.value = true;
  try {
    await downloadStatementPdf(
      customerName.value,
      fromDate.value || undefined,
      toDate.value || undefined,
    );
    toasts.success("Statement PDF saved to Documents");
  } catch (e) {
    if (e instanceof NetworkError) toasts.error("Offline — try again when connected");
    else toasts.error(e instanceof Error ? e.message : String(e));
  } finally {
    downloading.value = false;
  }
}

onMounted(load);
</script>

<template>
  <div class="stack">
    <section class="card filter-card">
      <div class="date-range">
        <label class="field">
          <span class="label">From</span>
          <input type="date" v-model="fromDate" />
        </label>
        <label class="field">
          <span class="label">To</span>
          <input type="date" v-model="toDate" />
        </label>
      </div>
      <button type="button" class="ghost small" :disabled="loading" @click="load">
        <Icon name="refresh" :size="14" /> Apply
      </button>
    </section>

    <div v-if="loading" class="skeleton" style="height:12rem" />
    <p v-if="err" class="error">{{ err }}</p>

    <template v-if="!loading && html">
      <div class="toolbar">
        <button type="button" class="ghost" :disabled="downloading" @click="saveAsPdf">
          <Icon name="receipt" :size="16" />
          <span>{{ downloading ? "Saving…" : "PDF" }}</span>
        </button>
        <button type="button" class="primary" @click="printStatement">
          <Icon name="receipt" :size="16" /> Print
        </button>
      </div>
      <!--
        `srcdoc` renders fully isolated from the host CSS (scoped styles,
        variables, media queries). Height is set once the iframe loads.
      -->
      <iframe
        ref="iframe"
        class="statement-frame"
        :srcdoc="html"
        sandbox="allow-same-origin allow-modals allow-popups"
        title="Customer statement"
      />
    </template>
  </div>
</template>

<style scoped>
.toolbar {
  display: flex;
  justify-content: flex-end;
  gap: 0.5rem;
}
.filter-card {
  display: flex;
  align-items: flex-end;
  gap: 0.6rem;
  padding: 0.85rem;
  flex-wrap: wrap;
}
.date-range {
  display: flex;
  gap: 0.5rem;
  flex: 1;
  min-width: 12rem;
}
.field { display: flex; flex-direction: column; gap: 0.2rem; flex: 1; }
.label { font-size: var(--text-xs); color: var(--text-muted); font-weight: 500; }
.field input { min-height: 2.4rem; }
.statement-frame {
  width: 100%;
  min-height: 70vh;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface);
  box-shadow: var(--shadow-sm);
}
</style>
