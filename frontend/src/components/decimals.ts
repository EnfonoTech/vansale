/**
 * `v-decimals="n"` on a number input: typing past `n` decimals is cut off
 * (rates keep Sales Invoice Item.rate's precision, amounts the currency
 * precision), so the screen never holds more than ERPNext will store.
 *
 * Runs in the capture phase, ahead of v-model's own input listener, so the
 * model only ever sees the trimmed value.
 */
import type { Directive } from "vue";

type El = HTMLInputElement & { _decimals?: number };

function trim(el: El) {
  const p = el._decimals;
  if (p == null) return;
  const m = el.value.match(/^(-?\d*)\.(\d*)$/);
  if (m && m[2].length > p) el.value = p > 0 ? `${m[1]}.${m[2].slice(0, p)}` : m[1];
}

export const vDecimals: Directive<El, number> = {
  created(el, binding) {
    el._decimals = binding.value;
    el.addEventListener("input", () => trim(el), true);
  },
  beforeUpdate(el, binding) {
    el._decimals = binding.value;
  },
};
