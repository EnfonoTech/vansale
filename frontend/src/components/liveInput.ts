/**
 * Search boxes read their text on every keystroke with
 * `:value="x" @input="x = inputValue($event)"` instead of `v-model`.
 *
 * Android keyboards (Gboard) hold the word being typed as an IME
 * "composition" for their suggestions, and `v-model` skips updates until the
 * composition ends — at the space — so typing "h" filtered nothing until
 * "home " was typed.
 */
export function inputValue(e: Event): string {
  return (e.target as HTMLInputElement).value;
}
