<script setup lang="ts">
/**
 * The sheet that forwards an approval to another person for their input.
 * The people listed are only those who can read the document (forwarding
 * does not share it, and someone who cannot open it could not answer), found
 * by a debounced search. The approver may add a note and ask for the answer
 * to come back ("return to me after their input") instead of handing the
 * decision over.
 *
 * Emits `done` with the person's name after the forward went through (the
 * screen reloads the inbox and says so); `refused` with the server's own
 * words when it said no; `close` when the approver backs out. A call that did
 * not get through keeps the sheet open with a line saying so.
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import * as api from "@/api/approvals";
import type { ForwardTarget } from "@/api/approvals";
import { useOnline } from "@/app/online";
import { initials } from "@/features/approvals/detail-display";
import { failureOf } from "@/features/approvals/detail-failure";
import Icon from "./Icon.vue";

const props = defineProps<{
  doctype: string;
  name: string;
  /** The user's open approval on the document (`Detail.action_id`). */
  actionId: string;
}>();
const emit = defineEmits<{
  (e: "close"): void;
  (e: "done", person: string): void;
  (e: "refused", message: string): void;
}>();

const { t } = useI18n();
const online = useOnline();

/** How long typing must pause before the search runs. */
const DEBOUNCE_MS = 300;

const text = ref("");
const people = ref<ForwardTarget[]>([]);
const loading = ref(false);
/** A search has answered at least once, so "nobody" can be said. */
const answered = ref(false);
const searchProblem = ref("");
const selected = ref<ForwardTarget | null>(null);
const note = ref("");
const returnToMe = ref(false);
const sending = ref(false);
const problem = ref("");

const canSend = computed(() => selected.value !== null && online.value && !sending.value);

let timer: ReturnType<typeof setTimeout> | undefined;
/** Only the latest search may land; an older answer is dropped. */
let seq = 0;

function failureText(error: unknown): string {
  const failure = failureOf(error);
  if (failure.kind === "network") return t("approvalsDetail.errors.network");
  return failure.message || t("approvalsDetail.errors.generic");
}

async function search() {
  const mine = ++seq;
  if (!online.value) {
    loading.value = false;
    searchProblem.value = t("approvalsDetail.forward.offline");
    return;
  }
  loading.value = true;
  searchProblem.value = "";
  try {
    const found = await api.forwardTargets(props.doctype, props.name, text.value.trim());
    if (mine !== seq) return;
    people.value = found;
    answered.value = true;
  } catch (error) {
    if (mine !== seq) return;
    searchProblem.value = failureText(error);
  } finally {
    if (mine === seq) loading.value = false;
  }
}

watch(text, () => {
  clearTimeout(timer);
  timer = setTimeout(() => void search(), DEBOUNCE_MS);
});
// Back online: the list that could not load can now.
watch(online, (now) => {
  if (now && (searchProblem.value || !answered.value)) void search();
});

function choose(person: ForwardTarget) {
  selected.value = selected.value?.user === person.user ? null : person;
}

async function submit() {
  if (!canSend.value || !selected.value) return;
  const person = selected.value;
  sending.value = true;
  problem.value = "";
  try {
    await api.forward(props.actionId, person.user, note.value.trim(), returnToMe.value);
    emit("done", person.full_name || person.user);
  } catch (error) {
    const failure = failureOf(error);
    if (failure.kind === "server") emit("refused", failure.message);
    else problem.value = failureText(error);
  } finally {
    sending.value = false;
  }
}

function close() {
  if (!sending.value) emit("close");
}

function onKey(event: KeyboardEvent) {
  if (event.key === "Escape") close();
}

const searchBox = ref<HTMLInputElement | null>(null);

onMounted(() => {
  window.addEventListener("keydown", onKey);
  document.body.style.overflow = "hidden";
  void search();
  void nextTick(() => searchBox.value?.focus({ preventScroll: true }));
});
onBeforeUnmount(() => {
  clearTimeout(timer);
  seq++;
  window.removeEventListener("keydown", onKey);
  document.body.style.overflow = "";
});
</script>

<template>
  <Teleport to="body">
    <div class="overlay" @click.self="close">
      <div class="sheet" role="dialog" aria-modal="true" aria-labelledby="forward-title">
        <div class="grip" aria-hidden="true" />
        <header class="head">
          <h3 id="forward-title">{{ t("approvalsDetail.forward.title") }}</h3>
          <p class="muted small">
            {{ t("approvalsDetail.forward.intro") }}
            <span class="doc ltr">{{ name }}</span>
          </p>
        </header>

        <label class="search">
          <Icon name="search" :size="18" />
          <input
            ref="searchBox"
            v-model="text"
            type="search"
            autocomplete="off"
            autocapitalize="off"
            enterkeyhint="search"
            :placeholder="t('approvalsDetail.forward.search')"
            :aria-label="t('approvalsDetail.forward.search')"
          />
        </label>

        <div class="people" role="radiogroup" :aria-label="t('approvalsDetail.forward.people')" :aria-busy="loading">
          <p v-if="selected && !people.some((p) => p.user === selected?.user)" class="chosen">
            <Icon name="check" :size="16" />
            {{ t("approvalsDetail.forward.chosen", { name: selected.full_name || selected.user }) }}
          </p>
          <template v-if="people.length">
            <button
              v-for="person in people"
              :key="person.user"
              type="button"
              class="person"
              role="radio"
              :aria-checked="selected?.user === person.user"
              :data-on="selected?.user === person.user"
              @click="choose(person)"
            >
              <span class="avatar" aria-hidden="true">{{ initials(person.full_name || person.user) }}</span>
              <span class="who">
                <strong>{{ person.full_name || person.user }}</strong>
                <span class="muted xsmall">{{ person.role }}</span>
              </span>
              <Icon v-if="selected?.user === person.user" name="check" :size="18" />
            </button>
          </template>
          <div v-else-if="loading" class="skeletons" aria-hidden="true">
            <div class="skeleton" /><div class="skeleton" /><div class="skeleton" />
          </div>
          <p v-else-if="searchProblem" class="note" data-tone="danger" role="alert">
            {{ searchProblem }}
            <button v-if="online" type="button" class="link" @click="search">{{ t("approvalsDetail.retry") }}</button>
          </p>
          <p v-else-if="answered" class="note">
            {{ text.trim() ? t("approvalsDetail.forward.noMatch", { text: text.trim() }) : t("approvalsDetail.forward.nobody") }}
          </p>
        </div>

        <div class="field">
          <label for="forward-note" class="label">{{ t("approvalsDetail.forward.note") }}</label>
          <textarea id="forward-note" v-model="note" rows="2" :disabled="sending" />
        </div>

        <label class="switch-row">
          <span class="switch-text">
            <strong>{{ t("approvalsDetail.forward.returnToMe") }}</strong>
            <span class="muted xsmall">
              {{ returnToMe ? t("approvalsDetail.forward.returnOn") : t("approvalsDetail.forward.returnOff") }}
            </span>
          </span>
          <input v-model="returnToMe" type="checkbox" role="switch" class="switch" :disabled="sending" />
        </label>

        <p class="hint connection" :data-tone="online ? 'muted' : 'danger'">
          <Icon :name="online ? 'wifi' : 'wifi-off'" :size="14" />
          {{ online ? t("approvalsDetail.sheet.needsConnection") : t("approvalsDetail.sheet.offline") }}
        </p>
        <p v-if="problem" class="hint" data-tone="danger" role="alert">{{ problem }}</p>

        <div class="buttons">
          <button type="button" class="cancel" :disabled="sending" @click="close">{{ t("approvalsDetail.sheet.cancel") }}</button>
          <button type="button" class="confirm" :disabled="!canSend" @click="submit">
            {{
              sending
                ? t("approvalsDetail.forward.sending")
                : selected
                  ? t("approvalsDetail.forward.forwardTo", { name: selected.full_name || selected.user })
                  : t("approvalsDetail.forward.pick")
            }}
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
  max-height: 92dvh;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 0.8rem;
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
.head h3 {
  margin: 0 0 0.2rem;
  font-size: var(--text-lg);
}
.head p {
  margin: 0;
}
.doc {
  font-family: var(--font-mono, ui-monospace), monospace;
  font-weight: 600;
  color: var(--text);
}
.ltr {
  direction: ltr;
  unicode-bidi: isolate;
}

.search {
  position: relative;
  display: block;
  color: var(--text-faint);
}
.search svg {
  position: absolute;
  inset-inline-start: 0.7rem;
  top: 50%;
  transform: translateY(-50%);
  pointer-events: none;
}
.search input {
  padding-inline-start: 2.3rem;
}

.people {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
  max-height: 14rem;
  overflow-y: auto;
  padding: 0.15rem;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface-muted);
}
.person {
  display: flex;
  align-items: center;
  gap: 0.65rem;
  padding: 0.5rem 0.6rem;
  min-height: 3rem;
  justify-content: flex-start;
  text-align: start;
  background: var(--surface);
  color: var(--text);
  border: 1px solid transparent;
  font-weight: 500;
}
.person[data-on="true"] {
  border-color: var(--primary);
  background: var(--primary-soft);
}
.person > svg {
  margin-inline-start: auto;
  color: var(--primary);
}
.avatar {
  width: 2rem;
  height: 2rem;
  flex-shrink: 0;
  display: grid;
  place-items: center;
  border-radius: var(--radius-pill);
  background: var(--primary-soft-strong);
  color: var(--primary);
  font-size: var(--text-xs);
  font-weight: 700;
}
.who {
  display: flex;
  flex-direction: column;
  min-width: 0;
  line-height: 1.25;
}
.who strong {
  font-size: var(--text-sm);
  overflow: hidden;
  text-overflow: ellipsis;
}
.chosen {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  margin: 0;
  padding: 0.4rem 0.6rem;
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--primary);
}
.note {
  margin: 0;
  padding: 0.75rem;
  font-size: var(--text-sm);
  color: var(--text-muted);
  text-align: center;
}
.note[data-tone="danger"] {
  color: var(--danger);
}
.skeletons {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
}
.skeletons .skeleton {
  height: 3rem;
  border-radius: var(--radius-sm);
}
.link {
  background: transparent;
  color: var(--primary);
  padding: 0.2rem 0.4rem;
  min-height: 2rem;
  font-size: var(--text-sm);
}

.field {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
}
.label {
  font-size: var(--text-xs);
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--text-muted);
}
textarea {
  resize: vertical;
}

.switch-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 0.4rem 0;
  cursor: pointer;
}
.switch-text {
  display: flex;
  flex-direction: column;
  font-size: var(--text-sm);
}
.switch {
  appearance: none;
  -webkit-appearance: none;
  flex-shrink: 0;
  position: relative;
  width: 2.6rem;
  height: 1.5rem;
  padding: 0;
  border: none;
  border-radius: var(--radius-pill);
  background: var(--border-strong);
  transition: background var(--dur-fast) var(--ease);
}
.switch::after {
  content: "";
  position: absolute;
  inset-block-start: 0.18rem;
  inset-inline-start: 0.18rem;
  width: 1.14rem;
  height: 1.14rem;
  border-radius: 50%;
  background: #fff;
  box-shadow: var(--shadow-sm);
  transition: inset-inline-start var(--dur-fast) var(--ease);
}
.switch:checked {
  background: var(--primary);
}
.switch:checked::after {
  inset-inline-start: 1.28rem;
}
.switch:focus-visible {
  box-shadow: 0 0 0 3px var(--primary-soft-strong);
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

.buttons {
  display: grid;
  grid-template-columns: 1fr 1.6fr;
  gap: 0.6rem;
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
