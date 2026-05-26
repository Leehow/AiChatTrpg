// Character-creation draft, SSE event shape, and stream handler interface.
// Lives in its own module so character.ts (API wrappers) and
// character-stream.ts (SSE helper) can both depend on it without a cycle.

export interface CharacterDraftMessageDTO {
  id?: string;
  role: "user" | "assistant";
  content: string;
  created_at?: string;
  thinking_steps?: string[];
  metadata?: Record<string, unknown> | null;
}

export interface CharacterDraftDTO {
  messages: CharacterDraftMessageDTO[];
  character: Record<string, unknown> | null;
  ready: boolean;
  assistant?: string | null;
  pool_id?: string | null;
}

export type CharacterStreamEvent =
  | { type: "thinking"; content: string; replace_last?: boolean }
  | { type: "metadata"; metadata: Record<string, unknown> }
  | { type: "content"; content?: string; delta?: string }
  | { type: "done"; result: CharacterDraftDTO }
  | { type: "error"; content?: string; message?: string };

export interface CharacterStreamHandlers {
  onThinking?: (content: string, options?: { replaceLast?: boolean }) => void;
  onMetadata?: (metadata: Record<string, unknown>) => void;
  onContent?: (content: string) => void;
}
