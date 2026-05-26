// One transcript bubble. User on the right, assistant on the left.

interface Props {
  role: "user" | "assistant" | "tool";
  text?: string;
}

export function ChatMessage({ role, text }: Props) {
  if (role === "tool" || !text) return null;

  if (role === "user") {
    return (
      <div className="self-end max-w-[80%] bg-accent-dim border border-accent/40 rounded-2xl rounded-tr-sm px-3 py-2">
        <div className="text-[13px] whitespace-pre-wrap leading-relaxed">{text}</div>
      </div>
    );
  }

  return (
    <div className="self-start max-w-[90%]">
      <div className="text-[10px] uppercase tracking-[0.08em] text-text-3 mb-1">
        Agent
      </div>
      <div className="text-[13px] whitespace-pre-wrap leading-relaxed text-text">
        {text}
      </div>
    </div>
  );
}
