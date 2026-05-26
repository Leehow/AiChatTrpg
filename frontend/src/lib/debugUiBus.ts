// Tiny module-level emitter for the right-rail debug panel. Used by
// chain-of-thought "view context" buttons to flip the panel to a tab
// without threading callbacks through SetupFlow → CharStep → CharStepUI.
//
// The bus also carries an optional `MessageSnapshot` so a "view context"
// click can scope the Context tab to the BP1/BP2/BP3 state that produced
// a specific GM message — instead of the live ruleset-wide snapshot.

export type DebugTab =
  | "context"
  | "ruleset"
  | "llm"
  | "ocr"
  | "module"
  | "users";

export interface BpSnapshot {
  source_phase?: string;
  // Cutoff message id — frontend filters messages with created_at <= the GM
  // message's created_at to reconstruct BP3.chat for the snapshot phase.
  // Null for the opening greeting (no preceding chat).
  chat_until_message_id: string | null;
  memory_state: Record<string, unknown>;
  narrative_summary: string;
  pc: Record<string, unknown> | null;
  draft_card: Record<string, unknown> | null;
  ready: boolean;
  dice_history: Array<Record<string, unknown>>;
  module_state?: Record<string, unknown>;
}

export interface MessageSnapshot {
  message_id: string;
  message_created_at: string;
  bp_snapshot?: BpSnapshot;
  message_metadata?: Record<string, unknown>;
}

type Listener = (
  tab: DebugTab,
  messageSnapshot?: MessageSnapshot,
) => void;
const listeners = new Set<Listener>();

export function openDebugTab(
  tab: DebugTab,
  messageSnapshot?: MessageSnapshot,
): void {
  listeners.forEach((fn) => fn(tab, messageSnapshot));
}

export function subscribeOpenDebugTab(fn: Listener): () => void {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
}
