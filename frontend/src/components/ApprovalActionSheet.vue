<script setup lang="ts">
/**
 * The sheet that confirms one approval action. It asks only for what the
 * action still needs: a comment (always for a return for correction, and when
 * the transition requires one), an attachment (when it requires one and the
 * document has none) and a priority. Confirm stays off until `canConfirm`
 * says nothing is missing, and while the phone is offline.
 *
 * It does the whole job: the picked file is attached first (once, even if
 * Confirm is tapped again after a failure), then the action is applied
 * through the store, which reloads the inbox. Approvals are never queued.
 *
 * Emits `done` after success; `refused` with the server's own words when the
 * server said no to the decision (the screen shows it and reloads the
 * document); `unconfirmed` when the decision was sent and no answer came back
 * (it may have gone through: the screen says so and reloads the document, so
 * Confirm is never offered again blindly); `close` when the approver backs
 * out. A refused FILE keeps the sheet open with the server's words and the
 * typed comment, and a call that did not get through at all keeps it open
 * with a line saying so, so nothing typed is lost.
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import * as api from "@/api/approvals";
import type { ActionSpec } from "@/api/approvals";
import { useOnline } from "@/app/online";
import { FILE_ACCEPT, attachmentName, checkAttachment, readAttachment, sizeLabel } from "@/features/approvals/detail-attach";
import { PRIORITIES, normalizePriority } from "@/features/approvals/detail-display";
import { failureOf, sheetOutcome } from "@/features/approvals/detail-failure";
import { canConfirm } from "@/features/approvals/rules";
import { useApprovalsStore } from "@/stores/approvals";
import Icon from "./Icon.vue";

const props = defineProps<{
  doctype: string;
  name: string;
  spec: ActionSpec;
  /** The document already has a file attached. */
  hasAttachment: boolean;
  /** The document's workflow state when it was opened: the server refuses if it has moved on. */
  expectedState: string;
}>();
const emit = defineEmits<{
  (e: "close"): void;
  (e: "done"): void;
  (e: "refused", message: string): void;
  (e: "unconfirmed"): void;
}>();

const { t } = useI18n();
const store = useApprovalsStore();
const online = useOnline();

// What is asked is fixed when the sheet opens: a field must not vanish once it is filled.
const asked = canConfirm(props.spec, { comment: "", hasAttachment: props.hasAttachment, addedAttachment: false }).missing;
const commentRequired = asked.includes("comment");
const attachmentRequired = asked.includes("attachment");
const advice = props.spec.recommend_only;
// The state the approver reviewed, fixed when the sheet opens: a reload of the
// document behind the sheet must not quietly replace what they agreed to.
const reviewedState = props.expectedState;

const comment = ref("");
const noteOpen = ref(false);
const priority = ref<string>(normalizePriority(props.spec.priority));
const picked = ref<File | null>(null);
/** The name shown for it (and sent), fixed when it was picked. */
const pickedName = ref("");
/** The picked file reached the document (do not send it twice). */
const uploaded = ref(false);
const stage = ref<"idle" | "attaching" | "applying">("idle");
const problem = ref("");
const attachProblem = ref("");

const busy = computed(() => stage.value !== "idle");
const showComment = computed(() => commentRequired || advice || noteOpen.value);
const check = computed(() =>
  canConfirm(props.spec, {
    comment: comment.value,
    hasAttachment: props.hasAttachment,
    addedAttachment: picked.value !== null || uploaded.value,
  }),
);
const canSubmit = computed(() => check.value.ok && online.value && !busy.value);

const actionLabel = computed(() =>
  advice ? t("approvalsDetail.recommend", { action: props.spec.action }) : props.spec.action,
);
const confirmLabel = computed(() => {
  if (stage.value === "attaching") return t("approvalsDetail.sheet.attaching");
  if (stage.value === "applying") return t("approvalsDetail.sheet.applying");
  return advice
    ? t("approvalsDetail.sheet.sendRecommendation")
    : t("approvalsDetail.sheet.confirm", { action: props.spec.action });
});
const commentLabel = computed(() => {
  if (advice) return t("approvalsDetail.sheet.adviceLabel");
  if (commentRequired) {
    return props.spec.is_return_for_correction
      ? t("approvalsDetail.sheet.reasonLabel")
      : t("approvalsDetail.sheet.commentLabel");
  }
  return t("approvalsDetail.sheet.noteLabel");
});
const commentHint = computed(() => {
  if (advice) return t("approvalsDetail.sheet.adviceHint");
  if (!commentRequired) return "";
  return props.spec.is_return_for_correction
    ? t("approvalsDetail.sheet.reasonHint")
    : t("approvalsDetail.sheet.commentHint");
});
const commentMissing = computed(() => check.value.missing.includes("comment"));

const commentBox = ref<HTMLTextAreaElement | null>(null);
const cameraInput = ref<HTMLInputElement | null>(null);
const fileInput = ref<HTMLInputElement | null>(null);

function openNote() {
  noteOpen.value = true;
  void nextTick(() => commentBox.value?.focus());
}

function onPick(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = "";
  if (!file) return;
  const bad = checkAttachment(file);
  if (bad) {
    attachProblem.value = t(`approvalsDetail.attach.${bad}`);
    return;
  }
  attachProblem.value = "";
  picked.value = file;
  pickedName.value = attachmentName(file);
  uploaded.value = false;
}

function removePicked() {
  picked.value = null;
  uploaded.value = false;
}

/** The sentence for a failure that is not a server refusal. */
function failureText(error: unknown): string {
  if (error instanceof Error && error.message === "tooLarge") return t("approvalsDetail.attach.tooLarge");
  const failure = failureOf(error);
  if (failure.kind === "network") return t("approvalsDetail.errors.network");
  return failure.message || t("approvalsDetail.errors.generic");
}

async function submit() {
  if (!canSubmit.value) return;
  problem.value = "";
  try {
    if (picked.value && !uploaded.value) {
      stage.value = "attaching";
      try {
        const file = await readAttachment(picked.value, pickedName.value);
        await api.attach(props.doctype, props.name, file.filename, file.base64);
        uploaded.value = true;
      } catch (error) {
        const outcome = sheetOutcome("attach", error);
        if (outcome.kind === "file") {
          // The server refused the FILE: stay open with what was typed, drop the file
          // that was refused and say why, so another can be chosen.
          attachProblem.value = outcome.message;
          picked.value = null;
          uploaded.value = false;
        } else {
          problem.value = failureText(error);
        }
        return;
      }
    }
    stage.value = "applying";
    try {
      // A recommendation has no priority to choose: send none, the server applies the default.
      await store.apply(
        props.doctype,
        props.name,
        props.spec.action,
        comment.value.trim(),
        advice ? "" : priority.value,
        reviewedState,
      );
    } catch (error) {
      const outcome = sheetOutcome("apply", error);
      if (outcome.kind === "refused") emit("refused", outcome.message);
      // Sent, and no answer: it may have gone through. Never offer Confirm again as if it had not.
      else if (outcome.kind === "unconfirmed") emit("unconfirmed");
      else problem.value = failureText(error);
      return;
    }
    emit("done");
  } finally {
    stage.value = "idle";
  }
}

function close() {
  if (!busy.value) emit("close");
}

function onKey(event: KeyboardEvent) {
  if (event.key === "Escape") close();
}

onMounted(() => {
  window.addEventListener("keydown", onKey);
  document.body.style.overflow = "hidden";
  if (commentRequired) void nextTick(() => commentBox.value?.focus());
});
onBeforeUnmount(() => {
  window.removeEventListener("keydown", onKey);
  document.body.style.overflow = "";
});
</script>

<template>
  <Teleport to="body">
    <div class="overlay" @click.self="close">
      <div class="sheet" role="dialog" aria-modal="true" aria-labelledby="action-sheet-title">
        <div class="grip" aria-hidden="true" />
        <header class="head">
          <h3 id="action-sheet-title">{{ actionLabel }}</h3>
          <span class="doc ltr">{{ name }}</span>
        </header>

        <div v-if="showComment" class="field">
          <label for="action-comment" class="label">
            {{ commentLabel }}
            <span v-if="commentRequired" class="req">{{ t("approvalsDetail.sheet.required") }}</span>
          </label>
          <textarea
            id="action-comment"
            ref="commentBox"
            v-model="comment"
            rows="3"
            :class="{ invalid: commentMissing }"
            :aria-required="commentRequired"
            :disabled="busy"
          />
          <p v-if="commentHint" class="hint" :data-tone="commentMissing ? 'danger' : 'muted'">{{ commentHint }}</p>
        </div>
        <button v-else-if="!advice" type="button" class="link" :disabled="busy" @click="openNote">
          <Icon name="plus" :size="16" /> {{ t("approvalsDetail.sheet.addNote") }}
        </button>

        <div v-if="attachmentRequired" class="field">
          <span class="label">
            {{ t("approvalsDetail.sheet.attachment") }}
            <span class="req">{{ t("approvalsDetail.sheet.required") }}</span>
          </span>
          <div v-if="picked" class="picked">
            <Icon name="invoice" :size="18" />
            <div class="picked-name">
              <strong class="ltr">{{ pickedName }}</strong>
              <span class="muted xsmall">
                {{ sizeLabel(picked.size) }}<template v-if="uploaded"> · {{ t("approvalsDetail.sheet.attached") }}</template>
              </span>
            </div>
            <button v-if="!uploaded" type="button" class="icon" :disabled="busy" :aria-label="t('approvalsDetail.sheet.removeFile')" @click="removePicked">
              <Icon name="x" :size="16" />
            </button>
          </div>
          <div v-else class="attach-row" :data-tone="check.missing.includes('attachment') ? 'danger' : 'muted'">
            <span>{{ t("approvalsDetail.sheet.attachmentHint") }}</span>
            <span class="attach-buttons">
              <button type="button" class="pick" :disabled="busy" @click="cameraInput?.click()">{{ t("approvalsDetail.sheet.camera") }}</button>
              <button type="button" class="pick" :disabled="busy" @click="fileInput?.click()">{{ t("approvalsDetail.sheet.file") }}</button>
            </span>
          </div>
          <p v-if="attachProblem" class="hint" data-tone="danger">{{ attachProblem }}</p>
          <input ref="cameraInput" type="file" accept="image/*" capture="environment" hidden @change="onPick" />
          <input ref="fileInput" type="file" :accept="FILE_ACCEPT" hidden @change="onPick" />
        </div>

        <div v-if="!advice" class="field">
          <span class="label" id="action-priority">{{ t("approvalsDetail.sheet.priority") }}</span>
          <div class="seg" role="radiogroup" aria-labelledby="action-priority">
            <button
              v-for="level in PRIORITIES"
              :key="level"
              type="button"
              role="radio"
              :aria-checked="priority === level"
              :data-on="priority === level"
              :disabled="busy"
              @click="priority = level"
            >
              {{ t(`approvalsDetail.priority.${level}`) }}
            </button>
          </div>
        </div>

        <p class="hint connection" :data-tone="online ? 'muted' : 'danger'">
          <Icon :name="online ? 'wifi' : 'wifi-off'" :size="14" />
          {{ online ? t("approvalsDetail.sheet.needsConnection") : t("approvalsDetail.sheet.offline") }}
        </p>
        <p v-if="problem" class="hint" data-tone="danger" role="alert">{{ problem }}</p>

        <div class="buttons">
          <button type="button" class="cancel" :disabled="busy" @click="close">{{ t("approvalsDetail.sheet.cancel") }}</button>
          <button type="button" class="confirm" :data-tone="spec.tone" :disabled="!canSubmit" @click="submit">
            {{ confirmLabel }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.overlay {
  position: fixed;
  inset: 0;
  z-index: 60;
  display: flex;
  align-items: flex-end;
  justify-content: center;
  background: color-mix(in srgb, black 50%, transparent);
  animation: fade var(--dur) var(--ease);
}
.sheet {
  width: 100%;
  max-width: var(--max-content);
  max-height: 90dvh;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 0.85rem;
  padding: 0.6rem 1rem calc(1rem + var(--safe-bottom));
  background: var(--surface);
  border-radius: var(--radius-lg) var(--radius-lg) 0 0;
  box-shadow: 0 -8px 28px rgba(15, 23, 42, 0.22);
  animation: rise var(--dur) var(--ease);
}
.grip {
  align-self: center;
  width: 2.5rem;
  height: 0.28rem;
  border-radius: var(--radius-pill);
  background: var(--border-strong);
}
.head {
  display: flex;
  flex-direction: column;
  gap: 0.1rem;
}
.head h3 {
  margin: 0;
  font-size: var(--text-lg);
}
.doc {
  font-family: var(--font-mono, ui-monospace), monospace;
  font-size: var(--text-xs);
  color: var(--text-muted);
}
.ltr {
  direction: ltr;
  unicode-bidi: isolate;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
}
.label {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-size: var(--text-xs);
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--text-muted);
}
.req {
  padding: 0.05rem 0.4rem;
  border-radius: var(--radius-pill);
  background: var(--danger-soft);
  color: var(--danger);
  font-size: var(--text-xs);
  letter-spacing: 0;
  text-transform: none;
}
textarea {
  min-height: 4.5rem;
  resize: vertical;
}
textarea.invalid {
  border-color: var(--danger);
}
.hint {
  margin: 0;
  font-size: var(--text-xs);
  color: var(--text-muted);
}
.hint[data-tone="danger"] {
  color: var(--danger);
}
.connection {
  display: flex;
  align-items: center;
  gap: 0.35rem;
}

.link {
  align-self: flex-start;
  background: transparent;
  color: var(--primary);
  padding: 0.3rem 0.1rem;
  min-height: 2.25rem;
  font-size: var(--text-sm);
}

.attach-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.6rem;
  padding: 0.55rem 0.7rem;
  border: 1px dashed var(--border-strong);
  border-radius: var(--radius);
  font-size: var(--text-sm);
  color: var(--text-muted);
}
.attach-row[data-tone="danger"] {
  border-color: var(--danger);
}
.attach-buttons {
  display: inline-flex;
  gap: 0.4rem;
  flex-shrink: 0;
}
.pick {
  background: var(--primary-soft);
  color: var(--primary);
  padding: 0.35rem 0.7rem;
  min-height: 2.25rem;
  font-size: var(--text-sm);
}
.picked {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  padding: 0.55rem 0.7rem;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius);
  background: var(--surface-muted);
}
.picked-name {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}
.picked-name strong {
  font-size: var(--text-sm);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.icon {
  background: var(--surface-sunk);
  color: var(--text);
  padding: 0.3rem;
  min-height: 2rem;
  width: 2rem;
  border-radius: var(--radius-pill);
}

.seg {
  display: flex;
  padding: 0.2rem;
  gap: 0.15rem;
  background: var(--surface-sunk);
  border-radius: var(--radius);
}
.seg button {
  flex: 1;
  min-height: 2.35rem;
  padding: 0.3rem 0.2rem;
  background: transparent;
  color: var(--text-muted);
  font-size: var(--text-sm);
  font-weight: 500;
  border-radius: var(--radius-sm);
}
.seg button[data-on="true"] {
  background: var(--surface);
  color: var(--text);
  font-weight: 700;
  box-shadow: var(--shadow-sm);
}

.buttons {
  display: grid;
  grid-template-columns: 1fr 1.6fr;
  gap: 0.6rem;
  margin-top: 0.15rem;
}
.cancel {
  background: var(--surface-sunk);
  color: var(--text);
  min-height: 3rem;
}
.confirm {
  min-height: 3rem;
  background: var(--primary);
  color: var(--primary-ink);
}
.confirm[data-tone="approve"] {
  background: var(--success);
}
.confirm[data-tone="reject"] {
  background: var(--danger);
}
.confirm:disabled {
  background: var(--surface-sunk);
  color: var(--text-faint);
  opacity: 1;
}

@keyframes fade {
  from { opacity: 0; }
}
@keyframes rise {
  from { transform: translateY(1.5rem); opacity: 0.6; }
}
@media (prefers-reduced-motion: reduce) {
  .overlay, .sheet { animation: none; }
}
</style>
