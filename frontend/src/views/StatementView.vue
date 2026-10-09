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
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { useRoute } from "vue-router";
import { statement, fetchStatementPdf, downloadStatementPdf } from "@/api/customer";
import { ApiError, NetworkError } from "@/app/frappe";
import { hasNativePrint, printPdfNative } from "@/app/native-print";
import { useSessionStore } from "@/stores/session";
import { useToastStore } from "@/stores/toasts";
import Icon from "@/components/Icon.vue";

const toasts = useToastStore();

const route = useRoute();
const customerName = computed(() => String(route.params.name ?? ""));

const html = ref("");
const loading = ref(false);
const err = ref("");
const session = useSessionStore();
const iframe = ref<HTMLIFrameElement | null>(null);

// The statement is an A4 page: lay it out at A4 width and shrink it to the
// screen, so a phone shows the printed page instead of a squeezed one.
const A4_PX = 794;
const preview = ref<HTMLElement | null>(null);
const scale = ref(1);
const pageHeight = ref(0);
let resizeObs: ResizeObserver | null = null;

function fitPreview() {
  const box = preview.value;
  if (box) scale.value = Math.min(1, box.clientWidth / A4_PX);
}
function onFrameLoad() {
  const doc = iframe.value?.contentDocument;
  pageHeight.value = doc ? doc.documentElement.scrollHeight : 0;
  fitPreview();
  if (!resizeObs && preview.value && "ResizeObserver" in window) {
    resizeObs = new ResizeObserver(fitPreview);
    resizeObs.observe(preview.value);
  }
}
onBeforeUnmount(() => resizeObs?.disconnect());
// Pre-filled with the server's default period (last 90 days) so the shown
// range is visible; local dates, not UTC.
const isoLocal = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const today = new Date();
const fromDate = ref(isoLocal(new Date(today.getFullYear(), today.getMonth(), today.getDate() - 90)));
const toDate = ref(isoLocal(today));
const downloading = ref(false);
const printing = ref(false);

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
 * Print the statement.
 *
 * Native Android: fetch the PDF binary from `statement_pdf` and hand it to
 * the `AndroidPrint` Capacitor plugin (same path as invoice print). Android
 * WebView silently swallows `iframe.contentWindow.print()` from a sandboxed
 * frame, which is why the previous wiring showed nothing on tap — the JS
 * call succeeded, but the WebView never surfaced the system dialog.
 *
 * Web: fall back to the iframe's `contentWindow.print()` — browsers honour
 * it there because the page is not sandboxed away from the user gesture.
 */
async function printStatement() {
  if (printing.value) return;
  printing.value = true;
  try {
    if (hasNativePrint()) {
      const blob = await fetchStatementPdf(
        customerName.value,
        fromDate.value || undefined,
        toDate.value || undefined,
      );
      await printPdfNative(blob, `statement-${customerName.value}`);
      return;
    }
    const frame = iframe.value;
    if (!frame || !frame.contentWindow) {
      toasts.error("Statement not loaded yet");
      return;
    }
    frame.contentWindow.focus();
    frame.contentWindow.print();
  } catch (e) {
    if (e instanceof NetworkError) toasts.error("Offline — try again when connected");
    else toasts.error(e instanceof Error ? e.message : String(e));
  } finally {
    printing.value = false;
  }
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
      <label class="field">
        <span class="label">From</span>
        <input type="date" v-model="fromDate" />
      </label>
      <label class="field">
        <span class="label">To</span>
        <input type="date" v-model="toDate" />
      </label>
      <button type="button" class="apply" aria-label="Apply" :disabled="loading" @click="load">
        <Icon name="refresh" :size="16" /> <span class="apply-text">Apply</span>
      </button>
    </section>

    <div v-if="loading" class="skeleton" style="height:12rem" />
    <p v-if="err" class="error">{{ err }}</p>

    <template v-if="!loading && html">
      <div class="toolbar">
        <button v-if="session.showPdfButton" type="button" class="ghost" :disabled="downloading" @click="saveAsPdf">
          <Icon name="receipt" :size="16" />
          <span>{{ downloading ? "Saving…" : "PDF" }}</span>
        </button>
        <button type="button" class="primary" :disabled="printing" @click="printStatement">
          <Icon name="receipt" :size="16" /> {{ printing ? "Printing…" : "Print" }}
        </button>
      </div>
      <!--
        `srcdoc` renders fully isolated from the host CSS (scoped styles,
        variables, media queries). Height is set once the iframe loads.
      -->
      <div
        ref="preview"
        class="statement-preview"
        :style="pageHeight ? { height: `${Math.ceil(pageHeight * scale)}px` } : undefined"
      >
        <iframe
          ref="iframe"
          class="statement-frame"
          :style="{ width: `${A4_PX}px`, height: pageHeight ? `${pageHeight}px` : '70vh', transform: `scale(${scale})` }"
          @load="onFrameLoad"
          :srcdoc="html"
          sandbox="allow-same-origin allow-modals allow-popups"
          title="Customer statement"
        />
      </div>
    </template>
  </div>
</template>

<style scoped>
.toolbar {
  display: flex;
  justify-content: flex-end;
  gap: 0.5rem;
}
/* From | To | Apply on one line, Apply level with the date boxes. */
.filter-card {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) auto;
  align-items: end;
  gap: 0.5rem;
  padding: 0.85rem;
}
.field { display: flex; flex-direction: column; gap: 0.25rem; min-width: 0; }
.label { font-size: var(--text-xs); color: var(--text-muted); font-weight: 500; }
.field input, .apply { height: 2.75rem; box-sizing: border-box; }
.field input { min-width: 0; padding-inline: 0.6rem; }
.apply {
  background: var(--primary-soft);
  color: var(--primary);
  padding: 0 0.9rem;
  min-height: 0;
}
@media (max-width: 380px) {
  .apply-text { display: none; }
  .apply { padding: 0 0.8rem; }
}
.statement-preview {
  overflow: hidden;
  min-height: 12rem;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: #fff;
  box-shadow: var(--shadow-sm);
}
.statement-frame {
  display: block;
  border: 0;
  background: #fff;
  transform-origin: top left;
}
</style>
