<script setup lang="ts">
/**
 * Canvas-based signature pad. Outputs a PNG blob, stashed in IDB via
 * `storeSignature()` — returns a `signature:<uuid>` placeholder that
 * the drain engine resolves on upload.
 */
import { onMounted, ref } from "vue";
import { storeSignature } from "@/offline/signatures";

const emit = defineEmits<{ (e: "update:modelValue", v: string | null): void }>();
defineProps<{ modelValue?: string | null }>();

const canvas = ref<HTMLCanvasElement | null>(null);
const hasStrokes = ref(false);
let ctx: CanvasRenderingContext2D | null = null;
let drawing = false;
let lastX = 0;
let lastY = 0;

onMounted(() => {
  const el = canvas.value;
  if (!el) return;
  const rect = el.getBoundingClientRect();
  el.width = rect.width * window.devicePixelRatio;
  el.height = rect.height * window.devicePixelRatio;
  ctx = el.getContext("2d");
  if (!ctx) return;
  ctx.scale(window.devicePixelRatio, window.devicePixelRatio);
  ctx.lineWidth = 2;
  ctx.lineCap = "round";
  ctx.strokeStyle = "#0f172a";
});

function pos(ev: PointerEvent): [number, number] {
  const el = canvas.value!;
  const rect = el.getBoundingClientRect();
  return [ev.clientX - rect.left, ev.clientY - rect.top];
}

function start(ev: PointerEvent) {
  drawing = true;
  [lastX, lastY] = pos(ev);
  canvas.value?.setPointerCapture(ev.pointerId);
}

function move(ev: PointerEvent) {
  if (!drawing || !ctx) return;
  const [x, y] = pos(ev);
  ctx.beginPath();
  ctx.moveTo(lastX, lastY);
  ctx.lineTo(x, y);
  ctx.stroke();
  lastX = x;
  lastY = y;
  hasStrokes.value = true;
}

function end(ev: PointerEvent) {
  drawing = false;
  canvas.value?.releasePointerCapture(ev.pointerId);
}

function clear() {
  const el = canvas.value;
  if (!el || !ctx) return;
  ctx.clearRect(0, 0, el.width, el.height);
  hasStrokes.value = false;
  emit("update:modelValue", null);
}

async function save() {
  const el = canvas.value;
  if (!el) return;
  const blob = await new Promise<Blob | null>((res) => el.toBlob((b) => res(b), "image/png"));
  if (!blob) return;
  const placeholder = await storeSignature(blob);
  emit("update:modelValue", placeholder);
}
</script>

<template>
  <div class="signature-pad">
    <canvas
      ref="canvas"
      @pointerdown="start"
      @pointermove="move"
      @pointerup="end"
      @pointercancel="end"
      @pointerleave="end"
    />
    <div class="actions">
      <button type="button" class="ghost" @click="clear">Clear</button>
      <button type="button" :disabled="!hasStrokes" @click="save">Save signature</button>
    </div>
  </div>
</template>

<style scoped>
.signature-pad {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}
canvas {
  width: 100%;
  height: 12rem;
  touch-action: none;
  background: var(--surface);
  border: 1px solid rgba(15, 23, 42, 0.15);
  border-radius: var(--radius);
}
.actions {
  display: flex;
  gap: 0.5rem;
  justify-content: flex-end;
}
</style>
