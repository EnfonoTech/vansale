<script setup lang="ts">
/**
 * In-app print view.
 *
 * Two output paths:
 *  - `Print` — on native APK, fetches the PDF bytes and hands them to our
 *    `AndroidPrint` Capacitor plugin, which triggers Android's system
 *    print dialog (preview, copies, Save-as-PDF, Bluetooth/Wi-Fi printers).
 *    On web, falls back to `iframe.contentWindow.print()`.
 *  - `PDF` — Frappe's `download_pdf` endpoint + `saveBlobToDevice`.
 *    Kept as a manual save path for users who want an archive copy
 *    without opening the print dialog.
 */
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";
import {
  fetchPrintHtml,
  downloadPrintPdf,
  fetchPrintPdfBlob,
  DEFAULT_SI_PRINT_FORMAT,
} from "@/api/print";
import { ApiError, NetworkError } from "@/app/frappe";
import { hasNativePrint, printPdfNative } from "@/app/native-print";
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
const printing = ref(false);
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

async function doPrint() {
  if (printing.value) return;
  // Native APK: fetch PDF bytes and open the system print dialog via our
  // AndroidPrint plugin. The WebView silently ignores `window.print()`
  // from inside a sandboxed iframe — PrintManager is the only reliable
  // path to the real Android print service.
  if (hasNativePrint()) {
    printing.value = true;
    try {
      const blob = await fetchPrintPdfBlob(doctype.value, name.value, format.value);
      await printPdfNative(blob, `${doctype.value}-${name.value}`);
    } catch (e) {
      if (e instanceof NetworkError) toasts.error("Offline — can't fetch PDF for print");
      else toasts.error(e instanceof Error ? e.message : String(e));
    } finally {
      printing.value = false;
    }
    return;
  }
  // Web fallback: browser's native print dialog on the iframe.
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
          <button type="button" class="primary" :disabled="printing" @click="doPrint">
            <Icon name="receipt" :size="16" />
            <span>{{ printing ? "Opening…" : "Print" }}</span>
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
