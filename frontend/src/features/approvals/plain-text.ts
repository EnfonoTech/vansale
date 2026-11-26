/**
 * A server message as plain text. Frappe words some of its messages with
 * markup (`<b>`, `<br>`, lists) and writes entities (`&amp;`, `&#39;`); the
 * phone shows them as text, so what reaches the screen must not carry either.
 * Pure: no Vue, no DOM, no network.
 *
 * Tags are removed first and entities decoded after, in one pass, so an
 * escaped tag (`&lt;b&gt;`) comes out as the text it stood for and is never
 * read as markup. The result is only ever shown as text (`{{ }}`, never
 * `v-html`).
 */

/** Where a break in the markup is a break in the reading. */
const BREAKS = /<\s*(?:br\s*\/?|\/\s*(?:p|div|li|tr|h[1-6]|ul|ol|table|blockquote))\s*>/gi;
/** An opening, closing or comment tag: `<` must be followed by a letter, `/` or `!`, so "5 < 10" survives. */
const TAGS = /<\/?[a-zA-Z!][^>]*>/g;
const ENTITY = /&(#x[0-9a-fA-F]+|#\d+|[a-zA-Z]+);/g;

const NAMED: Record<string, string> = {
  amp: "&",
  lt: "<",
  gt: ">",
  quot: '"',
  apos: "'",
  nbsp: " ",
};

function decodeEntity(whole: string, body: string): string {
  if (body[0] === "#") {
    const code = body[1] === "x" || body[1] === "X" ? parseInt(body.slice(2), 16) : parseInt(body.slice(1), 10);
    const valid = Number.isInteger(code) && code > 0 && code <= 0x10ffff && !(code >= 0xd800 && code <= 0xdfff);
    if (!valid) return whole;
    return code === 0xa0 ? " " : String.fromCodePoint(code);
  }
  return NAMED[body.toLowerCase()] ?? whole;
}

export function plainText(input: string | null | undefined): string {
  if (!input) return "";
  return String(input)
    .replace(BREAKS, "\n")
    .replace(TAGS, "")
    .replace(ENTITY, decodeEntity)
    .replace(/[ \t ]+/g, " ")
    .split("\n")
    .map((line) => line.trim())
    .join("\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}
