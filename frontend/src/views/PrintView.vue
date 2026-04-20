<script setup lang="ts">
/**
 * In-app print view.
 *
 * Why a route rather than `window.open`:
 *  - Native WebView is at `https://localhost`; relative /printview resolves
 *    to the wrong origin and 404s.
 *  - External window.open on native either opens the system browser (no
 *    auth cookie) or a blank tab. Neither prints the ZATCA format.
 *
 * Flow:
 *  1. Fetch `/printview?doctype=...&name=...&format=...` directly from
 *     the Frappe host (auth via API token on native, session on web).
 *     The `frappe.client.get_print` RPC is not available on every
 *     Frappe build, so we avoid that and hit the website route instead.
 *  2. Inject an absolute `<base href>` so the document's relative
 *     asset URLs resolve against the server, not `about:srcdoc`.
 *  3. Render inside a sandboxed iframe for CSS isolation.
 *  4. Trigger print via `iframe.contentWindow.print()` so only the
 *     invoice paper prints, not the app chrome.
 */
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";
import { fetchPrintHtml, DEFAULT_SI_PRINT_FORMAT } from "@/api/print";
import { ApiError, NetworkError } from "@/app/frappe";
import Icon from "@/components/Icon.vue";

const route = useRoute();
const doctype = computed(() => String(route.params.doctype ?? ""));
const name = computed(() => String(route.params.name ?? ""));
const format = computed(() => String(route.query.format ?? DEFAULT_SI_PRINT_FORMAT));

const html = ref("");
const loading = ref(false);
const err = ref("");
const iframe = ref<HTMLIFrameElement | null>(null);

async function load() {
  if (!doctype.value || !name.value) return;
  loading.value = true;
  err.value = "";
  try {
    html.value = await fetchPrintHtml(doctype.value, name.value, format.value);
  } catch (e) {
    if (e instanceof ApiError) err.value = e.serverMessage ?? "Could not render print";
    else if (e instanceof NetworkError) err.value = "You're offline — print needs a connection";
    else err.value = e instanceof Error ? e.message : String(e);
  } finally {
    loading.value = false;
  }
}

function doPrint() {
  const frame = iframe.value;
  if (!frame?.contentWindow) return;
  frame.contentWindow.focus();
  frame.contentWindow.print();
}

onMounted(load);
</script>

<template>
  <div class="stack">
    <div v-if="loading" class="skeleton" style="height: 14rem" />
    <p v-if="err" class="error">{{ err }}</p>

    <template v-if="!loading && html">
      <div class="toolbar">
        <span class="eyebrow">{{ doctype }} · {{ name }}</span>
        <button type="button" class="primary" @click="doPrint">
          <Icon name="receipt" :size="16" />
          <span>Print</span>
        </button>
      </div>
      <iframe
        ref="iframe"
        class="print-frame"
        :srcdoc="html"
        sandbox="allow-same-origin allow-modals allow-popups"
        title="Print view"
      />
    </template>
  </div>
</template>

<style scoped>
.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
}
.eyebrow {
  font-size: var(--text-xs);
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  font-weight: 600;
}
.print-frame {
  width: 100%;
  min-height: 80vh;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface);
  box-shadow: var(--shadow-sm);
}
</style>
