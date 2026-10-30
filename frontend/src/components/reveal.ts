/**
 * `@focus="revealOnFocus"` on a search box that sits mid-page: on a touch
 * screen the keyboard covers the lower half, so the results under the box
 * were hidden. Once the keyboard is up, the box is scrolled to just under
 * the top bar so its results show above the keyboard.
 */
const KEYBOARD_DELAY_MS = 350;

export function revealOnFocus(e: FocusEvent): void {
  if (!window.matchMedia?.("(pointer: coarse)").matches) return;
  const el = e.target as HTMLElement;
  window.setTimeout(() => {
    if (document.activeElement !== el) return;
    const bar = parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--top-bar-height")) || 3.25;
    const rem = parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;
    const top = el.getBoundingClientRect().top + window.scrollY - bar * rem - 8;
    window.scrollTo({ top: Math.max(top, 0), behavior: "smooth" });
  }, KEYBOARD_DELAY_MS);
}
