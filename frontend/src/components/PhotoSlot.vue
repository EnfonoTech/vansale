<script setup lang="ts">
/**
 * Drop-in photo input that:
 *  - Opens the device camera via `capture="environment"` on mobile.
 *  - Stores the captured blob via `capturePhoto()` — NEVER starts a
 *    background upload (ONE-uploader rule; `frappe-vue-pwa` §4.3).
 *  - Shows a thumbnail when the placeholder still points at a real
 *    blob. Auto-CLEARS the slot if the IDB record is gone, forcing
 *    the user to retake rather than saving against a dead reference
 *    (§4.7).
 */
import { onMounted, ref, watch } from "vue";
import { capturePhoto, resolvePreview } from "@/offline/photos";

const props = defineProps<{ modelValue?: string | null; label?: string }>();
const emit = defineEmits<{ (e: "update:modelValue", v: string | null): void }>();

const thumb = ref<string | undefined>(undefined);
const error = ref("");
const busy = ref(false);
const input = ref<HTMLInputElement | null>(null);

async function sync() {
  error.value = "";
  if (!props.modelValue) {
    thumb.value = undefined;
    return;
  }
  if (props.modelValue.startsWith("photo:")) {
    const preview = await resolvePreview(props.modelValue);
    if (!preview) {
      error.value = "Photo missing — tap to retake";
      emit("update:modelValue", null);
      return;
    }
    thumb.value = preview;
    return;
  }
  thumb.value = props.modelValue;
}

onMounted(sync);
watch(() => props.modelValue, sync);

async function onPick(e: Event) {
  const target = e.target as HTMLInputElement;
  const file = target.files?.[0];
  if (!file) return;
  busy.value = true;
  try {
    const { url, thumb: t } = await capturePhoto(file, file.name);
    thumb.value = t ?? URL.createObjectURL(file);
    emit("update:modelValue", url);
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err);
  } finally {
    busy.value = false;
    if (target) target.value = "";
  }
}
</script>

<template>
  <div class="photo-slot">
    <label v-if="label" class="muted">{{ label }}</label>
    <button type="button" class="picker" @click="input?.click()" :disabled="busy">
      <img v-if="thumb" :src="thumb" alt="" />
      <span v-else class="placeholder">Tap to capture</span>
    </button>
    <p v-if="error" class="error">{{ error }}</p>
    <input
      ref="input"
      type="file"
      accept="image/*"
      capture="environment"
      style="display: none"
      @change="onPick"
    />
  </div>
</template>

<style scoped>
.photo-slot {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}
.picker {
  padding: 0;
  width: 7rem;
  height: 7rem;
  border-radius: var(--radius);
  border: 2px dashed rgba(15, 23, 42, 0.2);
  background: var(--surface);
  color: var(--text-muted);
  overflow: hidden;
}
.picker img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.placeholder {
  font-size: 0.75rem;
}
</style>
