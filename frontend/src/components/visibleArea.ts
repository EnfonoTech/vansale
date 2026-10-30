/**
 * Position for a full-screen overlay that covers only the visible area: with
 * the phone keyboard up that is the part above it, so a picker's results are
 * never under the keyboard. Bind the returned style to the overlay while
 * `open` is true; without visualViewport the overlay's own CSS applies.
 */
import { computed, onBeforeUnmount, ref, watch, type Ref } from "vue";

export function useVisibleArea(open: Ref<boolean>) {
  const area = ref<{ top: number; height: number } | null>(null);
  const fit = () => {
    const vv = window.visualViewport;
    area.value = vv ? { top: vv.offsetTop, height: vv.height } : null;
  };
  const stop = () => {
    window.visualViewport?.removeEventListener("resize", fit);
    window.visualViewport?.removeEventListener("scroll", fit);
  };
  watch(
    open,
    (isOpen) => {
      const vv = window.visualViewport;
      if (!vv) return;
      if (isOpen) {
        fit();
        vv.addEventListener("resize", fit);
        vv.addEventListener("scroll", fit);
      } else {
        stop();
      }
    },
    { immediate: true },
  );
  onBeforeUnmount(stop);
  return computed(() =>
    area.value ? { top: `${area.value.top}px`, height: `${area.value.height}px` } : undefined,
  );
}
