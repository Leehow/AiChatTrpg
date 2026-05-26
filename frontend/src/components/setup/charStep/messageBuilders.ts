import type { CharacterDraftMessageDTO } from "../../../api/sessions";

const STREAMING_TIMESTAMP = "__streaming__";

function blankStreamingAssistant(): CharacterDraftMessageDTO {
  return {
    role: "assistant",
    content: "",
    created_at: STREAMING_TIMESTAMP,
    thinking_steps: [],
    metadata: { isStreaming: true },
  };
}

export function appendAssistantContent(
  prev: CharacterDraftMessageDTO[],
  content: string,
): CharacterDraftMessageDTO[] {
  if (!content) return prev;
  const last = prev[prev.length - 1];
  if (last?.role === "assistant" && last.created_at === STREAMING_TIMESTAMP) {
    return [
      ...prev.slice(0, -1),
      { ...last, content: `${last.content}${content}` },
    ];
  }
  return [
    ...prev,
    {
      role: "assistant",
      content,
      created_at: STREAMING_TIMESTAMP,
      thinking_steps: [],
      metadata: { isStreaming: true },
    },
  ];
}

export function appendAssistantThinking(
  prev: CharacterDraftMessageDTO[],
  step: string,
  options?: { replaceLast?: boolean },
): CharacterDraftMessageDTO[] {
  if (!step) return prev;
  const last = prev[prev.length - 1];
  const apply = (msg: CharacterDraftMessageDTO): CharacterDraftMessageDTO => {
    const current = msg.thinking_steps || [];
    const next =
      options?.replaceLast && current.length
        ? [...current.slice(0, -1), step]
        : [...current, step];
    return {
      ...msg,
      thinking_steps: next,
      metadata: { ...(msg.metadata || {}), isStreaming: true },
    };
  };
  if (last?.role === "assistant" && last.created_at === STREAMING_TIMESTAMP) {
    return [...prev.slice(0, -1), apply(last)];
  }
  return [...prev, apply(blankStreamingAssistant())];
}

export function mergeAssistantMetadata(
  prev: CharacterDraftMessageDTO[],
  metadata: Record<string, unknown>,
): CharacterDraftMessageDTO[] {
  if (!metadata || Object.keys(metadata).length === 0) return prev;
  const last = prev[prev.length - 1];
  const apply = (msg: CharacterDraftMessageDTO): CharacterDraftMessageDTO => ({
    ...msg,
    metadata: { ...(msg.metadata || {}), ...metadata, isStreaming: true },
  });
  if (last?.role === "assistant" && last.created_at === STREAMING_TIMESTAMP) {
    return [...prev.slice(0, -1), apply(last)];
  }
  return [...prev, apply(blankStreamingAssistant())];
}
