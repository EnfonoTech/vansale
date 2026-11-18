/**
 * Client mirror of the server's approval rules
 * (`vansale/steelforce/approvals_rules.py`): what the approver must still give
 * before an action can go, and which actions a batch can share. Permission
 * Manager stays the owner of who may do what; the server checks every one of
 * these again on apply, so this only tells the approver early.
 *
 * Pure: no Vue, no Pinia.
 */
import type { ActionFlag, ActionSpec, ApprovalItem } from "@/api/approvals";

export type Missing = "comment" | "attachment";

export interface ConfirmInput {
  comment: string;
  /** The document already has a file attached. */
  hasAttachment: boolean;
  /** The approver attached one just now, from this screen. */
  addedAttachment: boolean;
}

/** Whether `spec` may be confirmed with what has been given, and what is still missing. */
export function canConfirm(spec: ActionSpec, input: ConfirmInput): { ok: boolean; missing: Missing[] } {
  // Advice is not a decision: nothing is required of it.
  if (spec.recommend_only) return { ok: true, missing: [] };

  const missing: Missing[] = [];
  if ((spec.require_comment || spec.is_return_for_correction) && !input.comment.trim()) {
    missing.push("comment");
  }
  if (spec.require_attachment && !input.hasAttachment && !input.addedAttachment) {
    missing.push("attachment");
  }
  return { ok: missing.length === 0, missing };
}

/** i18n key of the reason a mixed selection cannot be decided together. */
export const BULK_MIXED_TYPES = "approvals.bulk.mixedTypes";

/**
 * The actions a selection can be decided with in one go: those every item
 * offers, less any that needs an attachment (a file belongs to one document).
 * A comment required by any item is required of the shared action.
 *
 * `reason` is an i18n key (pass it through `t()`), set when the items are not
 * all of one document type; the actions are then empty.
 */
export function bulkShared(items: ApprovalItem[]): { actions: ActionFlag[]; reason: string | null } {
  if (!items.length) return { actions: [], reason: null };
  if (new Set(items.map((item) => item.doctype)).size > 1) {
    return { actions: [], reason: BULK_MIXED_TYPES };
  }

  const actions: ActionFlag[] = [];
  for (const first of items[0].available_actions) {
    const same = items.map((item) => item.available_actions.find((flag) => flag.action === first.action));
    if (same.some((flag) => !flag)) continue;
    const flags = same as ActionFlag[];
    if (flags.some((flag) => flag.require_attachment)) continue;
    actions.push({
      action: first.action,
      require_comment: flags.some((flag) => flag.require_comment),
      require_attachment: false,
      is_return_for_correction: flags.some((flag) => flag.is_return_for_correction),
    });
  }
  return { actions, reason: null };
}
