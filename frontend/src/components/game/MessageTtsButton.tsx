import { useI18n } from "../../i18n";
import { useMessageTts } from "../../hooks/useMessageTts";

interface Props {
  sessionId?: string | null;
  messageId: string;
  text: string;
}

export function MessageTtsButton({ sessionId, messageId, text }: Props) {
  const { t } = useI18n();
  const tts = useMessageTts({
    sessionId: sessionId ?? null,
    messageId,
    text,
    enabled: true,
  });
  const title = tts.error
    ? `${t("messageTtsError")}: ${tts.error}`
    : tts.busy
      ? t("messageTtsStop")
      : t("messageTtsPlay");
  const busy = tts.status === "loading" || tts.status === "streaming";
  return (
    <button
      type="button"
      onClick={tts.toggle}
      title={title}
      aria-label={title}
      className={[
        "ml-auto inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full border transition-all",
        "border-border bg-surface text-text-3 hover:border-accent hover:text-accent active:scale-95",
        tts.playing ? "border-accent text-accent bg-accent-dim" : "",
        tts.status === "error" ? "border-red-300 text-red-500" : "",
        busy ? "opacity-80" : "",
      ].filter(Boolean).join(" ")}
    >
      {tts.busy ? <StopIcon spinning={busy} /> : <SpeakerIcon />}
    </button>
  );
}

function SpeakerIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5" />
      <path d="M15.5 8.5a5 5 0 0 1 0 7" />
      <path d="M18.5 5.5a9 9 0 0 1 0 13" />
    </svg>
  );
}

function StopIcon({ spinning }: { spinning?: boolean }) {
  return (
    <svg className={spinning ? "animate-spin" : ""} width="12" height="12" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <rect x="7" y="7" width="10" height="10" rx="1.5" />
    </svg>
  );
}
