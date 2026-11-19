<script setup lang="ts">
/**
 * One document in the approvals inbox: what it is, whose it is, how much,
 * how long it has waited and how urgent it is. A coloured bar on the leading
 * edge carries the priority. A document that waits on someone else (`is_waiting`)
 * is shown dimmed and has nothing to press but "open".
 *
 * In selection mode the card shows a tick box instead of opening: `selected`
 * says whether it is in, `blocked` (already worded, "" when it may join) says
 * why it cannot.
 *
 * A long press asks for selection (`select`); the click that follows a long
 * press is swallowed, so the document does not also open. If that click never
 * comes it is forgotten shortly after the finger lifts (and by the next press),
 * so it cannot swallow a later tap.
 */
import { computed, onBeforeUnmount } from "vue";
import { useI18n } from "vue-i18n";
import type { ApprovalItem } from "@/api/approvals";
import { ageText, formatAmount, isOverdue } from "@/features/approvals/inbox";
import { priorityTone } from "@/features/approvals/format";
import { createClickSwallow } from "@/features/approvals/long-press";
import { useSessionStore } from "@/stores/session";
import Icon from "@/components/Icon.vue";
import SarSymbol from "@/components/SarSymbol.vue";

const props = defineProps<{
  item: ApprovalItem;
  /** Selection mode is on: tapping ticks the card instead of opening it. */
  selecting?: boolean;
  selected?: boolean;
  /** Why the card cannot join the selection; "" when it can. */
  blocked?: string;
  /** A long press may start selection (false for waiting items and offline). */
  canSelect?: boolean;
}>();

const emit = defineEmits<{
  (e: "open", item: ApprovalItem): void;
  (e: "toggle", item: ApprovalItem): void;
  (e: "select", item: ApprovalItem): void;
}>();

const { t, te } = useI18n();
const session = useSessionStore();

const tone = computed(() => priorityTone(props.item.priority));
const title = computed(() => props.item.transaction || props.item.doctype);
const currency = computed(() => props.item.currency || session.currency || "");
const amount = computed(() =>
  props.item.amount === null || props.item.amount === undefined
    ? ""
    : formatAmount(props.item.amount, session.currencyPrecision),
);
const age = computed(() => ageText(props.item.days, t));
const overdue = computed(() => isOverdue(props.item.days));
/** The priority in the user's language; one the app does not know is shown as the server wrote it. */
const priorityLabel = computed(() => {
  const key = `approvalsInbox.priority.${props.item.priority}`;
  return te(key) ? t(key) : props.item.priority || "";
});
/** Document, then party: "ACC-JV-2026-02580 · Al Noor Trading". */
const subline = computed(() => [props.item.docname, props.item.party].filter(Boolean).join(" · "));
const greyed = computed(() => Boolean(props.selecting && props.blocked && !props.selected));

// --- long press -------------------------------------------------------------

const HOLD_MS = 450;
const MOVE_PX = 10;
let holdTimer: number | undefined;
let startX = 0;
let startY = 0;
/** The press that just ended was a long one: the click after it is not a tap (and a click that never comes is forgotten). */
const swallow = createClickSwallow();

function cancelHold() {
  window.clearTimeout(holdTimer);
  holdTimer = undefined;
}

function onPointerDown(event: PointerEvent) {
  // A new press is a new gesture: nothing left from the last one may swallow its click.
  swallow.reset();
  if (props.selecting || !props.canSelect || event.button > 0) return;
  startX = event.clientX;
  startY = event.clientY;
  cancelHold();
  holdTimer = window.setTimeout(() => {
    holdTimer = undefined;
    swallow.arm();
    emit("select", props.item);
  }, HOLD_MS);
}

/** The finger lifted or the pointer was lost: stop the hold, and give the click that follows a moment to arrive. */
function onPointerEnd() {
  cancelHold();
  swallow.released();
}

function onPointerMove(event: PointerEvent) {
  if (holdTimer === undefined) return;
  if (Math.abs(event.clientX - startX) > MOVE_PX || Math.abs(event.clientY - startY) > MOVE_PX) cancelHold();
}

onBeforeUnmount(() => {
  cancelHold();
  swallow.reset();
});

function activate() {
  if (swallow.consume()) return;
  if (props.selecting) {
    // A greyed card is not ticked; one already in stays tickable (to leave).
    if (!greyed.value) emit("toggle", props.item);
    return;
  }
  emit("open", props.item);
}
</script>

<template>
  <div
    class="card-row"
    :class="{ waiting: item.is_waiting, selected, greyed, selecting }"
    :data-priority="tone"
    :role="selecting ? 'checkbox' : 'button'"
    :aria-checked="selecting ? Boolean(selected) : undefined"
    :aria-disabled="greyed || undefined"
    :aria-label="selecting ? t('approvalsInbox.card.select', { name: item.docname }) : t('approvalsInbox.card.open', { name: item.docname })"
    tabindex="0"
    @click="activate"
    @keyup.enter="activate"
    @keyup.space.prevent="activate"
    @pointerdown="onPointerDown"
    @pointermove="onPointerMove"
    @pointerup="onPointerEnd"
    @pointercancel="onPointerEnd"
    @pointerleave="onPointerEnd"
    @contextmenu.prevent
  >
    <span v-if="selecting" class="tick" :class="{ on: selected }" aria-hidden="true">
      <Icon v-if="selected" name="check" :size="14" />
    </span>

    <div class="top">
      <strong class="title">{{ title }}</strong>
      <strong v-if="amount" class="amount"><SarSymbol :code="currency" />{{ amount }}</strong>
    </div>
    <div class="sub">{{ subline }}</div>
    <div v-if="item.creator" class="by">{{ t("approvalsInbox.card.createdBy", { name: item.creator }) }}</div>

    <div class="meta">
      <span class="tag" :class="{ overdue }">{{ age }}</span>
      <span v-if="priorityLabel" class="tag prio">{{ priorityLabel }}</span>
      <span v-if="item.is_waiting && item.waiting_with" class="tag info">
        {{ t("approvalsInbox.card.with", { name: item.waiting_with }) }}
      </span>
      <span v-else-if="item.role_id" class="tag">{{ item.role_id }}</span>
      <span v-if="item.forwarded_by && !item.is_waiting" class="tag info">
        {{ t("approvalsInbox.card.forwardedBy", { name: item.forwarded_by }) }}
      </span>
    </div>

    <div v-if="greyed" class="why">{{ blocked }}</div>
  </div>
</template>

<style scoped>
.card-row {
  --bar: var(--border-strong);
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
  padding-block: 0.65rem;
  padding-inline: 0.85rem 0.8rem;
  background: var(--surface);
  border-radius: var(--radius);
  border-inline-start: 5px solid var(--bar);
  box-shadow: var(--shadow-sm);
  cursor: pointer;
  user-select: none;
  -webkit-user-select: none;
  -webkit-touch-callout: none;
  touch-action: pan-y;
  transition: transform var(--dur-fast) var(--ease), opacity var(--dur-fast) var(--ease);
}
.card-row:active { transform: scale(0.99); }
.card-row:focus-visible { outline: 2px solid var(--primary); outline-offset: 2px; }

.card-row[data-priority="critical"] { --bar: #7a1f24; }
.card-row[data-priority="high"] { --bar: var(--danger); }
.card-row[data-priority="medium"] { --bar: #f5a524; }
.card-row[data-priority="low"] { --bar: var(--success); }

/* Held by someone else: shown for the count, with nothing to decide. */
.card-row.waiting { opacity: 0.72; }
.card-row.greyed { opacity: 0.55; cursor: not-allowed; }
.card-row.selected { box-shadow: 0 0 0 2px var(--primary), var(--shadow-sm); }

.top {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 0.5rem;
}
/* Room for the tick box in selection mode. */
.card-row.selecting .top { padding-inline-end: 1.7rem; }
.title { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.amount { font-variant-numeric: tabular-nums; white-space: nowrap; }

.sub {
  color: var(--text-muted);
  font-size: var(--text-sm);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.by {
  color: var(--text-muted);
  font-size: var(--text-xs);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.meta { display: flex; flex-wrap: wrap; gap: 0.3rem; margin-top: 0.2rem; }
.tag {
  padding: 0.05rem 0.5rem;
  border-radius: var(--radius-pill);
  background: var(--surface-sunk);
  color: var(--text-muted);
  font-size: var(--text-xs);
  font-weight: 600;
}
.tag.overdue { background: var(--danger-soft); color: var(--danger); }
.tag.info { background: var(--info-soft); color: var(--info); }
.card-row[data-priority="critical"] .tag.prio { background: var(--danger-soft); color: #7a1f24; }
.card-row[data-priority="high"] .tag.prio { background: var(--danger-soft); color: var(--danger); }
.card-row[data-priority="medium"] .tag.prio { background: var(--warning-soft); color: var(--warning); }
.card-row[data-priority="low"] .tag.prio { background: var(--success-soft); color: var(--success); }

.tick {
  position: absolute;
  inset-block-start: 0.6rem;
  inset-inline-end: 0.65rem;
  width: 1.15rem;
  height: 1.15rem;
  border-radius: 0.35rem;
  border: 2px solid var(--text-faint);
  background: var(--surface);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: var(--primary-ink);
}
.tick.on { background: var(--primary); border-color: var(--primary); }

.why { margin-top: 0.15rem; font-size: var(--text-xs); color: var(--text-muted); }
</style>
