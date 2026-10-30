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
import { useSessionStore } from "@/stores/session";

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

/**
 * Yes / No before posting an invoice, return, payment or refund, when
 * Vansale Settings "Ask Yes / No before submitting" is on. `details` are the
 * summary lines (customer, amount, payment); empty ones are skipped.
 * Resolves true to go ahead — at once when the setting is off.
 */
export function confirmSubmit(
  title: string,
  details: Array<string | false | null | undefined>,
  yesText = "Yes, submit",
): Promise<boolean> {
  if (!useSessionStore().confirmSubmit) return Promise.resolve(true);
  return useConfirmStore().ask({
    title,
    message: details.filter(Boolean).join("\n"),
    confirmText: yesText,
    cancelText: "No",
  });
}

/** "SAR 12.50" for a confirmation summary; just the amount without a currency. */
export function withCurrency(amount: string): string {
  const cur = useSessionStore().currency;
  return cur ? `${cur} ${amount}` : amount;
}
