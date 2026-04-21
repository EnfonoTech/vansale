<script setup lang="ts">
/**
 * In-app print view.
 *
 * Two output paths:
 *  - `Print` uses `iframe.contentWindow.print()` — works in browsers
 *    and Capacitor's Android WebView via its default Print service.
 *  - `Download PDF` hits Frappe's `download_pdf` endpoint and saves
 *    the file via `saveBlobToDevice` (Documents/ on native, browser
 *    download on web). This is what users actually want on Android —
 *    the system print dialog from inside a sandboxed iframe is flaky.
 */
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";
import { fetchPrintHtml, downloadPrintPdf, DEFAULT_SI_PRINT_FORMAT } from "@/api/print";
import { ApiError, NetworkError } from "@/app/frappe";
import { useToastStore } from "@/stores/toasts";
import Icon from "@/components/Icon.vue";

const route = useRoute();
const toasts = useToastStore();
const doctype = computed(() => String(route.params.doctype ?? ""));
const name = computed(() => String(route.params.name ?? ""));
const format = computed(() => String(route.query.format ?? DEFAULT_SI_PRINT_FORMAT));

const html = ref("");
const loading = ref(false);
const err = ref("");
const downloading = ref(false);
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

async function doDownload() {
  if (downloading.value) return;
  downloading.value = true;
  try {
    await downloadPrintPdf(doctype.value, name.value, format.value);
    toasts.success("PDF saved to Documents");
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
    <div v-if="loading" class="skeleton" style="height: 14rem" />
    <p v-if="err" class="error">{{ err }}</p>

    <template v-if="!loading && html">
      <div class="toolbar">
        <span class="eyebrow">{{ doctype }} · {{ name }}</span>
        <div class="toolbar-actions">
          <button type="button" class="ghost" :disabled="downloading" @click="doDownload">
            <Icon name="receipt" :size="16" />
            <span>{{ downloading ? "Saving…" : "PDF" }}</span>
          </button>
          <button type="button" class="primary" @click="doPrint">
            <Icon name="receipt" :size="16" />
            <span>Print</span>
          </button>
        </div>
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
.toolbar-actions { display: flex; gap: 0.5rem; }
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
