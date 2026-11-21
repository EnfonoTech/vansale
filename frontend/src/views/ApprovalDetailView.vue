<script setup lang="ts">
/**
 * One document waiting on an approval: what it is, what it says, where it is
 * in its route and what was said about it, then a sticky bar with its real
 * actions (Approve primary, Reject red, others plain, Forward). Tapping an
 * action opens the action sheet, which asks only for what the action needs;
 * nothing is decided from this screen without that second tap.
 *
 * When the user cannot act the bar gives way to one line saying why (waiting
 * on someone else, their own document, no access to read it). A user asked
 * for advice sees recommendation buttons and a banner saying the answer goes
 * back. A document opened from My requests or History has no bar at all.
 *
 * Approvals need a connection: the screen has nothing to show offline, and
 * while the phone drops off the buttons are disabled with a line saying so.
 */
import { computed, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { useI18n } from "vue-i18n";
import * as api from "@/api/approvals";
import type { ActionSpec, Detail, DetailAttachment, RouteStep } from "@/api/approvals";
import { absoluteUrl, isNative } from "@/app/platform";
import { useOnline } from "@/app/online";
import {
  bannerMessage,
  barMode,
  cameFromInbox,
  currentHolders,
  type Holder,
  moreLines,
  normalizePriority,
  orderActions,
  priorityPillTone,
} from "@/features/approvals/detail-display";
import { downloadPrivateFile } from "@/features/approvals/detail-download";
import { failureOf } from "@/features/approvals/detail-failure";
import { fileAccess, fileLabel, safeLinkUrl } from "@/features/approvals/detail-file";
import { safeDeskUrl } from "@/features/approvals/lists";
import { buildTimeline } from "@/features/approvals/detail-timeline";
import { priorityTone } from "@/features/approvals/format";
import { useApprovalsStore } from "@/stores/approvals";
import { useSessionStore } from "@/stores/session";
import { useToastStore } from "@/stores/toasts";
import ApprovalActionSheet from "@/components/ApprovalActionSheet.vue";
import ForwardSheet from "@/components/ForwardSheet.vue";
import Icon from "@/components/Icon.vue";
import SarSymbol from "@/components/SarSymbol.vue";

const props = defineProps<{ doctype: string; name: string }>();

const { t } = useI18n();
const router = useRouter();
const session = useSessionStore();
const approvals = useApprovalsStore();
const toasts = useToastStore();
const online = useOnline();

// ─── Loading ────────────────────────────────────────────────────────────────

const detail = ref<Detail | null>(null);
const loading = ref(false);
/** Why there is nothing to show, or "" when there is. */
const loadError = ref("");
/** Only the latest answer may land. */
let loadSeq = 0;

async function load(quiet = false) {
  const mine = ++loadSeq;
  if (!online.value) {
    if (!detail.value) loadError.value = t("approvalsDetail.errors.offlineLoad");
    return;
  }
  if (!quiet || !detail.value) loading.value = true;
  try {
    const fresh = await api.detail(props.doctype, props.name);
    if (mine !== loadSeq) return;
    detail.value = fresh;
    loadError.value = "";
  } catch (error) {
    if (mine !== loadSeq) return;
    // A document already on screen stays; only an empty screen shows the failure.
    if (!detail.value) {
      const failure = failureOf(error);
      loadError.value =
        failure.kind === "network"
          ? t("approvalsDetail.errors.offlineLoad")
          : failure.message || t("approvalsDetail.errors.loadFailed");
    }
  } finally {
    if (mine === loadSeq) loading.value = false;
  }
}

onMounted(() => void load());
watch(
  () => [props.doctype, props.name],
  () => {
    detail.value = null;
    loadError.value = "";
    void load();
  },
);
// Back online with nothing to show: try again.
watch(online, (now) => {
  if (now && (!detail.value || loadError.value)) void load();
});

// ─── What is shown ──────────────────────────────────────────────────────────

const mode = computed(() => (detail.value ? barMode(detail.value) : ({ kind: "none" } as const)));
const canForward = computed(() => Boolean(detail.value?.can_forward && detail.value.action_id));
const showBar = computed(() => mode.value.kind !== "none" || canForward.value);
const cannotRead = computed(() => mode.value.kind === "reason" && mode.value.banner.kind === "cannot_read");
const recommendBanner = computed(() =>
  detail.value?.banner?.kind === "recommend" ? bannerMessage(detail.value.banner) : null,
);
const reason = computed(() => (mode.value.kind === "reason" ? bannerMessage(mode.value.banner) : null));

type BarItem = { kind: "action"; spec: ActionSpec } | { kind: "forward" };
/** Reject, Forward, Approve: Forward sits before the Approve the thumb reaches first. */
const barItems = computed<BarItem[]>(() => {
  const items: BarItem[] = [];
  if (mode.value.kind === "actions" && detail.value) {
    for (const spec of orderActions(detail.value.actions)) items.push({ kind: "action", spec });
  }
  if (canForward.value) {
    const at = items.findIndex((item) => item.kind === "action" && item.spec.tone === "approve");
    items.splice(at < 0 ? items.length : at, 0, { kind: "forward" });
  }
  return items;
});

/** The document's desk page, or "" when the server's address is not one (no link is then shown). */
const deskHref = computed(() => {
  const url = safeDeskUrl(detail.value?.desk_url ?? "");
  return url ? absoluteUrl(url) : "";
});

const currency = computed(() => detail.value?.currency || session.currency || "");
function money(amount: number): string {
  const digits = session.currencyPrecision;
  return amount.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

const priority = computed(() => normalizePriority(detail.value?.priority));

const linesNote = computed(() => {
  const count = detail.value ? moreLines(detail.value.lines) : 0;
  return count > 0 ? t("approvalsDetail.lines.more", { count }, count) : "";
});

const myStep = computed(
  () => mode.value.kind === "actions" && detail.value?.banner?.kind !== "recommend" && Boolean(detail.value?.action_id),
);
const holders = computed(() =>
  detail.value && !detail.value.route.finished ? currentHolders(detail.value.route, session.user ?? "") : [],
);

/** "Mariam K., Ahmed, you +2 more": the others, the viewer, and the rest. */
function holderText(holder: Holder): string {
  const names = [...holder.names];
  if (holder.includesMe) names.push(t("approvalsDetail.route.you"));
  const text = names.join(", ");
  if (holder.more <= 0) return text;
  return [text, t("approvalsDetail.route.more", { count: holder.more })].filter(Boolean).join(" ");
}

function stepNote(step: RouteStep): string {
  const parts: string[] = [];
  if (step.status === "done" && step.by) parts.push(t("approvalsDetail.route.by", { name: step.by }));
  else if (step.roles.length) parts.push(step.roles.join(", "));
  if (step.final) parts.push(t("approvalsDetail.route.final"));
  return parts.join(" · ");
}

const TIMELINE_SHORT = 4;
const timelineOpen = ref(false);
const timeline = computed(() => (detail.value ? buildTimeline(detail.value.comments, detail.value.route.events) : []));
const timelineShown = computed(() => (timelineOpen.value ? timeline.value : timeline.value.slice(0, TIMELINE_SHORT)));

/** The phone app signs in with a token header, so its WebView cannot follow a private file's link. */
const native = isNative();
/** The files being saved to the phone (by URL), so a second tap waits. */
const saving = ref<string[]>([]);

async function saveFile(file: DetailAttachment) {
  if (saving.value.includes(file.url)) return;
  saving.value.push(file.url);
  const label = fileLabel(file);
  try {
    await downloadPrivateFile(file.url, label);
    toasts.success(t("approvalsDetail.file.saved", { name: label }));
  } catch {
    toasts.error(t("approvalsDetail.file.failed"));
  } finally {
    saving.value = saving.value.filter((url) => url !== file.url);
  }
}

function actionLabel(spec: ActionSpec): string {
  return spec.recommend_only ? t("approvalsDetail.recommend", { action: spec.action }) : spec.action;
}

// ─── Deciding ───────────────────────────────────────────────────────────────

const activeSpec = ref<ActionSpec | null>(null);
const forwardOpen = ref(false);

/** Back to where the user came from, or to the inbox. */
function leave() {
  if (cameFromInbox(window.history.state?.back)) router.back();
  else void router.replace({ name: "approvals" });
}

function onActionDone() {
  const spec = activeSpec.value;
  activeSpec.value = null;
  if (!spec) return;
  const forwarder = detail.value?.banner?.kind === "recommend" ? detail.value.banner.forwarder : "";
  toasts.success(
    spec.recommend_only
      ? forwarder
        ? t("approvalsDetail.toast.recommendedTo", { name: forwarder })
        : t("approvalsDetail.toast.recommended")
      : t("approvalsDetail.toast.done", { action: spec.action, name: props.name }),
  );
  leave();
}

async function onForwarded(person: string) {
  forwardOpen.value = false;
  await approvals.refresh();
  toasts.success(t("approvalsDetail.toast.forwarded", { name: person }));
  leave();
}

const REFUSAL_TOAST_MS = 7000;

/**
 * The decision was sent and no answer came back: it may have gone through.
 * Say so and reload the document, so what is offered next is what is true
 * (the bar is gone if it moved) and not a Confirm button asking again blindly.
 */
async function onUnconfirmed() {
  activeSpec.value = null;
  toasts.warn(t("approvalsDetail.toast.unconfirmed"), REFUSAL_TOAST_MS);
  await load(true);
}

/** The server said no: its words, as given, then what is true now. */
async function onRefused(message: string) {
  const forwarding = forwardOpen.value;
  activeSpec.value = null;
  forwardOpen.value = false;
  // Long enough to read a sentence such as "This document changed since you opened it".
  toasts.error(message, REFUSAL_TOAST_MS);
  // An apply reloaded the inbox already; a forward did not.
  await Promise.all([load(true), forwarding ? approvals.refresh() : Promise.resolve()]);
}
</script>

<template>
  <div class="page stack" :class="{ 'has-bar': showBar }">
    <div v-if="loading && !detail" class="stack" aria-busy="true">
      <div class="skeleton" style="height: 8rem" />
      <div class="skeleton" style="height: 9rem" />
      <div class="skeleton" style="height: 7rem" />
    </div>

    <section v-else-if="!detail" class="card empty-state" role="alert">
      <Icon :name="online ? 'alert' : 'wifi-off'" :size="28" />
      <p>{{ loadError || t("approvalsDetail.errors.loadFailed") }}</p>
      <button type="button" :disabled="loading" @click="load()">
        <Icon name="refresh" :size="16" /> {{ t("approvalsDetail.retry") }}
      </button>
    </section>

    <template v-else>
      <section class="card head" :data-priority="priorityTone(detail.priority)">
        <div class="head-top">
          <span class="muted xsmall kind">{{ detail.transaction }}</span>
          <span class="pill" :data-tone="priorityPillTone(detail.priority)">{{ t(`approvalsDetail.priority.${priority}`) }}</span>
        </div>
        <h2 class="docname ltr">{{ detail.docname }}</h2>
        <div v-if="detail.state"><span class="pill" data-tone="info">{{ detail.state }}</span></div>
        <p v-if="detail.amount !== null" class="amount">
          <SarSymbol v-if="currency" :code="currency" /><bdi>{{ money(detail.amount) }}</bdi>
        </p>
        <p v-if="detail.party || detail.creator" class="muted small subline">
          <span v-if="detail.party">{{ detail.party }}</span>
          <span v-if="detail.creator">{{ t("approvalsDetail.raisedBy", { name: detail.creator }) }}</span>
        </p>
      </section>

      <aside v-if="recommendBanner" class="banner" role="status">
        <Icon name="alert" :size="18" />
        <span>{{ t(recommendBanner.key, recommendBanner.params) }}</span>
      </aside>

      <section v-if="detail.facts.length" class="card">
        <h3 class="section-h">{{ t("approvalsDetail.facts") }}</h3>
        <dl class="facts">
          <div v-for="(fact, i) in detail.facts" :key="i" class="fact">
            <dt>{{ fact.label }}</dt>
            <dd>{{ fact.value }}</dd>
          </div>
        </dl>
      </section>

      <section v-if="detail.lines.rows.length" class="card">
        <h3 class="section-h">{{ t("approvalsDetail.lines.title", { count: detail.lines.total }) }}</h3>
        <ul class="lines">
          <li v-for="(row, i) in detail.lines.rows" :key="i">
            <strong class="line-main">{{ row[0] }}</strong>
            <span class="line-rest">
              <template v-for="(cell, j) in row.slice(1)" :key="j">
                <span v-if="cell" class="cell">
                  <em>{{ detail.lines.columns[j + 1] }}</em> {{ cell }}
                </span>
              </template>
            </span>
          </li>
        </ul>
        <p v-if="linesNote" class="muted small more">
          {{ linesNote }}
          <a v-if="!cannotRead && deskHref" :href="deskHref" target="_blank" rel="noopener">
            {{ t("approvalsDetail.lines.openAll") }}
          </a>
        </p>
      </section>

      <section v-if="detail.attachments.length" class="card">
        <h3 class="section-h">{{ t("approvalsDetail.attachments", { count: detail.attachments.length }) }}</h3>
        <ul class="files">
          <li v-for="(file, i) in detail.attachments" :key="i">
            <!-- Web, and public files on the phone: a plain link. -->
            <a v-if="fileAccess(file, native) === 'link' && safeLinkUrl(file.url)" :href="absoluteUrl(safeLinkUrl(file.url))" target="_blank" rel="noopener">
              <Icon name="invoice" :size="18" />
              <span class="file-name ltr">{{ fileLabel(file) }}</span>
            </a>
            <!-- A private file on the phone: fetched with the app's token and saved. -->
            <button
              v-else-if="fileAccess(file, native) === 'download'"
              type="button"
              class="file-save"
              :disabled="saving.includes(file.url) || !online"
              @click="saveFile(file)"
            >
              <Icon :name="saving.includes(file.url) ? 'sync' : 'invoice'" :size="18" />
              <span class="file-text">
                <span class="file-name ltr">{{ fileLabel(file) }}</span>
                <span class="muted xsmall">{{ t("approvalsDetail.file.saveHint") }}</span>
              </span>
            </button>
            <!-- Nothing here can open it: say where to. -->
            <div v-else class="file-plain">
              <Icon name="invoice" :size="18" />
              <span class="file-text">
                <span class="file-name ltr">{{ fileLabel(file) }}</span>
                <span class="xsmall">{{ t("approvalsDetail.file.explain") }}</span>
              </span>
            </div>
          </li>
        </ul>
      </section>

      <section v-if="detail.route.chain.length" class="card">
        <h3 class="section-h">{{ t("approvalsDetail.route.title") }}</h3>
        <ol class="steps">
          <li v-for="(step, i) in detail.route.chain" :key="i" :data-status="step.status">
            <span class="dot" aria-hidden="true"><Icon v-if="step.status === 'done'" name="check" :size="12" /></span>
            <span class="step-body">
              <strong>
                {{ step.state }}
                <span v-if="step.status === 'current' && myStep" class="you">{{ t("approvalsDetail.route.you") }}</span>
              </strong>
              <span v-if="stepNote(step)" class="muted xsmall">{{ stepNote(step) }}</span>
            </span>
            <span class="sr-only">{{ t(`approvalsDetail.route.${step.status}`) }}</span>
          </li>
        </ol>
        <p v-if="detail.route.finished" class="muted small route-note">{{ t("approvalsDetail.route.finished") }}</p>
        <div v-else-if="holders.length" class="holders">
          <span class="holders-title">{{ t("approvalsDetail.route.canActNow") }}</span>
          <ul>
            <li v-for="holder in holders" :key="holder.role">
              <strong>{{ holder.role }}</strong>
              <span class="muted">
                {{ holderText(holder) }}
              </span>
            </li>
          </ul>
        </div>
      </section>

      <section v-if="timeline.length" class="card">
        <h3 class="section-h">{{ t("approvalsDetail.timeline.title") }}</h3>
        <ul class="timeline">
          <li v-for="(entry, i) in timelineShown" :key="i" :data-kind="entry.kind">
            <div class="who">
              <strong>{{ entry.by }}</strong>
              <span class="muted xsmall ltr">{{ entry.when }}</span>
            </div>
            <p v-if="entry.kind === 'comment'" class="said">{{ entry.text }}</p>
            <p v-else class="moved muted small">
              {{ t("approvalsDetail.timeline.moved", { from: entry.from, to: entry.to }) }}
            </p>
          </li>
        </ul>
        <button v-if="timeline.length > TIMELINE_SHORT" type="button" class="link" @click="timelineOpen = !timelineOpen">
          {{ timelineOpen ? t("approvalsDetail.timeline.less") : t("approvalsDetail.timeline.all", { count: timeline.length }) }}
        </button>
      </section>

      <p v-if="!showBar" class="muted small read-only">{{ t("approvalsDetail.readOnly") }}</p>

      <a v-if="!cannotRead && deskHref" class="desk" :href="deskHref" target="_blank" rel="noopener">
        {{ t("approvalsDetail.openFull") }}
        <Icon name="chevron-right" :size="16" />
      </a>
    </template>

    <div v-if="detail && showBar" class="bar" role="region" :aria-label="t('approvalsDetail.bar.label')">
      <p v-if="reason" class="reason">
        <Icon name="alert" :size="16" />
        <span>{{ t(reason.key, reason.params) }}</span>
      </p>
      <p v-else-if="!online" class="reason" data-tone="danger">
        <Icon name="wifi-off" :size="16" />
        <span>{{ t("approvalsDetail.bar.offline") }}</span>
      </p>
      <div v-if="barItems.length" class="bar-buttons">
        <template v-for="item in barItems" :key="item.kind === 'action' ? item.spec.action : 'forward'">
          <button
            v-if="item.kind === 'action'"
            type="button"
            class="act"
            :data-tone="item.spec.tone"
            :disabled="!online"
            @click="activeSpec = item.spec"
          >
            {{ actionLabel(item.spec) }}
          </button>
          <button v-else type="button" class="act forward" :disabled="!online" @click="forwardOpen = true">
            <Icon name="share" :size="16" /> {{ t("approvalsDetail.bar.forward") }}
          </button>
        </template>
      </div>
    </div>

    <ApprovalActionSheet
      v-if="detail && activeSpec"
      :key="activeSpec.action"
      :doctype="doctype"
      :name="name"
      :spec="activeSpec"
      :has-attachment="detail.has_attachment"
      :expected-state="detail.state"
      @close="activeSpec = null"
      @done="onActionDone"
      @refused="onRefused"
      @unconfirmed="onUnconfirmed"
    />
    <ForwardSheet
      v-if="detail && forwardOpen && detail.action_id"
      :doctype="doctype"
      :name="name"
      :action-id="detail.action_id"
      @close="forwardOpen = false"
      @done="onForwarded"
      @refused="onRefused"
    />
  </div>
</template>

<style scoped>
.page.has-bar {
  /* Room for the sticky bar, so the last card is not hidden behind it. */
  padding-bottom: 6.5rem;
}
.ltr {
  direction: ltr;
  unicode-bidi: isolate;
}
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.6rem;
  padding: 2rem 1rem;
  text-align: center;
  color: var(--text-muted);
}
.empty-state p {
  margin: 0;
}

/* Header */
.head {
  --bar: var(--warning);
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  border-inline-start: 5px solid var(--bar);
  background: linear-gradient(135deg, color-mix(in srgb, var(--bar) 7%, var(--surface)) 0%, var(--surface) 70%);
}
.head[data-priority="critical"] { --bar: color-mix(in srgb, var(--danger) 55%, black); }
.head[data-priority="high"] { --bar: var(--danger); }
.head[data-priority="medium"] { --bar: var(--warning); }
.head[data-priority="low"] { --bar: var(--success); }
.head-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 0.5rem;
}
.kind {
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.docname {
  margin: 0;
  font-family: var(--font-mono, ui-monospace), monospace;
  font-size: var(--text-lg);
  overflow-wrap: anywhere;
}
.amount {
  margin: 0.1rem 0 0;
  font-size: var(--text-2xl);
  font-weight: 800;
  letter-spacing: -0.02em;
  font-variant-numeric: tabular-nums;
}
.subline {
  margin: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 0 0.5rem;
}
.subline span + span::before {
  content: "\00b7";
  margin-inline-end: 0.5rem;
}

.banner {
  display: flex;
  gap: 0.6rem;
  align-items: flex-start;
  padding: 0.75rem 0.85rem;
  border-radius: var(--radius);
  background: var(--info-soft);
  color: var(--text);
  font-size: var(--text-sm);
  line-height: 1.45;
  border: 1px solid color-mix(in srgb, var(--info) 30%, transparent);
}
.banner svg {
  flex-shrink: 0;
  margin-top: 0.1rem;
  color: var(--info);
}

.section-h {
  margin: 0 0 0.5rem;
  font-size: var(--text-xs);
  color: var(--text-muted);
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

/* Facts */
.facts {
  margin: 0;
  display: flex;
  flex-direction: column;
}
.fact {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
  padding: 0.4rem 0;
  border-bottom: 1px dashed var(--border);
  font-size: var(--text-sm);
}
.fact:last-child {
  border-bottom: none;
}
.fact dt {
  color: var(--text-muted);
  flex-shrink: 0;
  max-width: 45%;
}
.fact dd {
  unicode-bidi: plaintext;
  margin: 0;
  text-align: end;
  font-weight: 500;
  overflow-wrap: anywhere;
  white-space: pre-line;
}

/* Lines */
.lines {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
}
.lines li {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
  padding: 0.5rem 0;
  border-bottom: 1px dashed var(--border);
}
.lines li:last-child {
  border-bottom: none;
}
.line-main {
  unicode-bidi: plaintext;
  font-size: var(--text-sm);
  overflow-wrap: anywhere;
}
.line-rest {
  display: flex;
  flex-wrap: wrap;
  gap: 0.15rem 0.9rem;
  font-size: var(--text-xs);
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
}
.cell {
  unicode-bidi: plaintext;
}
.cell em {
  font-style: normal;
  color: var(--text-faint);
}
.more {
  margin: 0.4rem 0 0;
}
.more a {
  margin-inline-start: 0.3rem;
}

/* Attachments */
.files {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
}
.files a,
.file-save,
.file-plain {
  display: flex;
  align-items: center;
  gap: 0.55rem;
  min-height: 2.5rem;
  font-size: var(--text-sm);
  font-weight: 500;
}
/* The phone's save button looks like the link beside it. */
.file-save {
  width: 100%;
  justify-content: flex-start;
  padding: 0;
  background: transparent;
  color: var(--primary);
  text-align: start;
}
.file-plain {
  color: var(--text-muted);
}
.file-plain .xsmall {
  font-weight: 400;
}
.file-text {
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.file-text .xsmall {
  font-weight: 400;
}
.file-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* Route */
.steps {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
}
.steps li {
  position: relative;
  display: flex;
  gap: 0.7rem;
  align-items: flex-start;
  padding-bottom: 0.75rem;
}
.steps li:last-child {
  padding-bottom: 0;
}
.steps li:not(:last-child)::before {
  content: "";
  position: absolute;
  inset-inline-start: 0.6rem;
  top: 1.35rem;
  bottom: 0.1rem;
  width: 2px;
  margin-inline-start: -1px;
  background: var(--border-strong);
}
.steps li[data-status="done"]:not(:last-child)::before {
  background: var(--success);
}
.dot {
  flex-shrink: 0;
  width: 1.2rem;
  height: 1.2rem;
  margin-top: 0.1rem;
  display: grid;
  place-items: center;
  border-radius: 50%;
  background: var(--surface-sunk);
  border: 2px solid var(--border-strong);
  color: #fff;
}
.steps li[data-status="done"] .dot {
  background: var(--success);
  border-color: var(--success);
}
.steps li[data-status="current"] .dot {
  background: var(--primary);
  border-color: var(--primary);
  box-shadow: 0 0 0 4px var(--primary-soft-strong);
}
.step-body {
  display: flex;
  flex-direction: column;
  min-width: 0;
  font-size: var(--text-sm);
  line-height: 1.3;
}
.steps li[data-status="upcoming"] strong {
  color: var(--text-muted);
  font-weight: 500;
}
.you {
  margin-inline-start: 0.3rem;
  padding: 0.05rem 0.45rem;
  border-radius: var(--radius-pill);
  background: var(--primary);
  color: var(--primary-ink);
  font-size: var(--text-xs);
  font-weight: 700;
}
.route-note {
  margin: 0.6rem 0 0;
}
.holders {
  margin-top: 0.8rem;
  padding-top: 0.7rem;
  border-top: 1px solid var(--border);
  font-size: var(--text-sm);
}
.holders-title {
  display: block;
  margin-bottom: 0.25rem;
  font-size: var(--text-xs);
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--text-muted);
}
.holders ul {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
}
.holders li {
  display: flex;
  flex-wrap: wrap;
  gap: 0.1rem 0.5rem;
}

/* Timeline */
.timeline {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.7rem;
}
.timeline li {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
  padding-inline-start: 0.7rem;
  border-inline-start: 3px solid var(--border-strong);
}
.timeline li[data-kind="comment"] {
  border-inline-start-color: var(--warning);
}
.timeline .who {
  display: flex;
  justify-content: space-between;
  gap: 0.5rem;
  font-size: var(--text-sm);
}
.timeline p {
  margin: 0;
}
.said {
  unicode-bidi: plaintext;
  font-size: var(--text-sm);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.link {
  margin-top: 0.4rem;
  background: transparent;
  color: var(--primary);
  padding: 0.3rem 0.1rem;
  min-height: 2.25rem;
  font-size: var(--text-sm);
}

.read-only {
  margin: 0;
  text-align: center;
}
.desk {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.3rem;
  min-height: 2.75rem;
  font-size: var(--text-sm);
  font-weight: 600;
}

/* Sticky bar: above the bottom navigation, in the page column. */
.bar {
  position: fixed;
  inset-inline: 0;
  bottom: calc(var(--bottom-nav-height) + var(--safe-bottom));
  z-index: 15;
  width: 100%;
  max-width: var(--max-content);
  margin-inline: auto;
  padding: 0.6rem 0.75rem;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  background: var(--surface);
  border-top: 1px solid var(--border-strong);
  box-shadow: 0 -6px 18px rgba(15, 23, 42, 0.08);
}
.reason {
  display: flex;
  align-items: flex-start;
  gap: 0.45rem;
  margin: 0;
  font-size: var(--text-sm);
  line-height: 1.4;
  color: var(--text-muted);
}
.reason svg {
  flex-shrink: 0;
  margin-top: 0.1rem;
}
.reason[data-tone="danger"] {
  color: var(--danger);
}
.bar-buttons {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}
.act {
  flex: 1 1 6rem;
  min-height: 2.9rem;
  background: var(--surface-sunk);
  color: var(--text);
}
.act[data-tone="approve"] {
  flex-grow: 1.4;
  background: var(--success);
  color: #fff;
}
.act[data-tone="reject"] {
  background: var(--danger-soft);
  color: var(--danger);
}
.act:disabled {
  opacity: 0.45;
}
</style>
