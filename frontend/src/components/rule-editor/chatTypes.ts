// Shared types for the chat panes (main editor + dice agent).

export interface ChatTurn {
  id: string;
  role: "user" | "assistant" | "tool";
  text?: string;
  toolCalls?: ChatToolCall[];
  toolCallId?: string;
  toolName?: string;
  toolResult?: Record<string, unknown>;
}

export interface ChatToolCall {
  callId: string;
  toolName: string;
  argsBuf: string;
  result?: Record<string, unknown>;
  editId?: string | null;
  status: "running" | "ok" | "error";
}
