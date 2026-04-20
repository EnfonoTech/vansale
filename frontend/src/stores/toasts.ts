import { defineStore } from "pinia";

export type ToastTone = "info" | "success" | "warning" | "danger";
export interface Toast {
  id: number;
  message: string;
  tone: ToastTone;
  timeoutId?: ReturnType<typeof setTimeout>;
}

let nextId = 1;

export const useToastStore = defineStore("toasts", {
  state: () => ({ items: [] as Toast[] }),
  actions: {
    show(message: string, tone: ToastTone = "info", durationMs = 3000) {
      const id = nextId++;
      const toast: Toast = { id, message, tone };
      if (durationMs > 0) {
        toast.timeoutId = setTimeout(() => this.dismiss(id), durationMs);
      }
      this.items.push(toast);
    },
    success(message: string, durationMs = 2500) { this.show(message, "success", durationMs); },
    error(message: string, durationMs = 4500) { this.show(message, "danger", durationMs); },
    warn(message: string, durationMs = 3500) { this.show(message, "warning", durationMs); },
    info(message: string, durationMs = 2500) { this.show(message, "info", durationMs); },
    dismiss(id: number) {
      const idx = this.items.findIndex((t) => t.id === id);
      if (idx < 0) return;
      const [t] = this.items.splice(idx, 1);
      if (t.timeoutId) clearTimeout(t.timeoutId);
    },
  },
});
