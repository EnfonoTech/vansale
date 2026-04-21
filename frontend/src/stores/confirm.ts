/**
 * Global confirm dialog queue.
 *
 * Replaces `window.confirm()` — the Capacitor WebView renders that as a
 * bare Chromium dialog that (a) ignores app theming, (b) looks jarring
 * on Android because it mimics the desktop Chrome UI rather than Android
 * Material, and (c) can be dismissed by the OS back gesture without
 * returning a value, which trips the "user confirmed" code path. The
 * `ConfirmModal` component reads from this store and renders an in-app,
 * themed, keyboard- and gesture-safe modal.
 *
 * Usage:
 *   const confirm = useConfirmStore();
 *   if (await confirm.ask({ title: "Delete draft?", danger: true })) {
 *     ...
 *   }
 */
import { defineStore } from "pinia";

export interface ConfirmOptions {
  title: string;
  message?: string;
  confirmText?: string;
  cancelText?: string;
  danger?: boolean;   // true → destructive styling on the confirm button
}

interface ConfirmState {
  open: boolean;
  options: ConfirmOptions;
  /** resolved with true on confirm, false on cancel/backdrop/esc */
  resolve: ((ok: boolean) => void) | null;
}

export const useConfirmStore = defineStore("confirm", {
  state: (): ConfirmState => ({
    open: false,
    options: { title: "" },
    resolve: null,
  }),
  actions: {
    /**
     * Show the modal. Returns a promise that resolves to `true` when the
     * user taps Confirm, `false` on cancel/backdrop/ESC.
     */
    ask(options: ConfirmOptions): Promise<boolean> {
      // If another dialog is already open, reject its pending promise
      // (callers treat reject as cancel) so we never leak promises.
      if (this.open && this.resolve) {
        this.resolve(false);
      }
      return new Promise<boolean>((resolve) => {
        this.options = options;
        this.open = true;
        this.resolve = resolve;
      });
    },
    _close(result: boolean) {
      const r = this.resolve;
      this.open = false;
      this.resolve = null;
      if (r) r(result);
    },
  },
});
