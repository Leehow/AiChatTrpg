import { useI18n } from "../../i18n";
import { TrpgMessage } from "./TrpgMessage";
import { WaitingHint } from "./WaitingHint";
import { PendingCheckCard } from "./PendingCheckCard";
import { PostprocessSteps } from "./PostprocessSteps";
import type { TrpgSpeakerProfile } from "../../utils/trpgDialogue";
import {
  openDebugTab,
  type BpSnapshot,
  type MessageSnapshot,
} from "../../lib/debugUiBus";
import { MessageTtsButton } from "./MessageTtsButton";
import type { TrpgHudCurrentTime } from "./trpgHudTypes";

export type ChatStyle = "bubbles" | "log";

export interface ChatMessage {
  id: string;
  role: "system" | "gm" | "user" | "dice";
  text?: string;
  type?: string;
  result?: number;
  dc?: number;
  time?: string;
  // ISO timestamp + scene snapshot — both filled by GameShell from MessageDTO.
  // Used by SceneTabs to bucket the timeline by scene; absent on legacy
  // messages, so SceneTabs reconstructs from [SET_SCENE] markers when needed.
  createdAt?: string;
  phase?: string;
  sceneKey?: string | null;
  sceneName?: string | null;
  currentTime?: TrpgHudCurrentTime | null;
  // GM-only: streaming `__THINKING__` events captured during the turn, then
  // persisted in metadata.thinking_steps so the player can re-open the chain
  // of thought after reload. Empty/missing for non-GM and legacy rows.
  thinkingSteps?: string[];
  // GM-only: per-message context snapshot (BP3 inputs at the moment this
  // GM reply was generated). Used by the "view context" button to open the
  // debug panel scoped to this exact turn instead of live state.
  bpSnapshot?: BpSnapshot;
  // GM-only: pending [CHECK] placeholders awaiting a player click.
  // Populated from `metadata.pending_checks`. The "投出" button card is
  // rendered for every entry where `resolved=false`. Cleared once all are
  // rolled (a follow-up GM message replaces this one as the latest).
  pendingChecks?: PendingCheckSummary[];
  metadata?: Record<string, unknown> | null;
}

export interface PendingCheckSummary {
  id: string;
  engine?: string;
  skill?: string;
  value?: number | null;
  difficulty?: string;
  target?: number | null;
  pool?: string;
  bonus?: number;
  penalty?: number;
  reason?: string;
  resolved?: boolean;
}

interface Props {
  msg: ChatMessage;
  sessionId?: string | null;
  chatStyle: ChatStyle;
  characterName: string;
  characterInitial: string;
  speakerProfiles?: Record<string, TrpgSpeakerProfile>;
  // Triggered when the player clicks "投出" on a pending check below this
  // GM message. Hooked up by GameShell to roll 3D dice first, then call
  // `streamIcTurnAPI` with `intent: "resolve"`.
  onResolvePending?: (pending: PendingCheckSummary) => void;
  // True while a resolve stream is in flight, so the button can show a
  // spinner / disabled state.
  resolvingPending?: boolean;
}

export function Message({
  msg, sessionId, chatStyle, characterName, characterInitial, speakerProfiles,
  onResolvePending, resolvingPending,
}: Props) {
  const { t } = useI18n();
  const canReadTts =
    msg.role === "gm"
    && Boolean(sessionId)
    && !msg.id.startsWith("tmp-")
    && Boolean((msg.text || "").trim());
  const modelLabel = formatModelLabel(msg.metadata);
  const stampLine =
    msg.role === "gm"
      ? [msg.time, modelLabel].filter(Boolean).join(" · ")
      : msg.time || "";

  if (msg.role === "system") {
    return (
      <div className="text-center text-[11px] text-text-3 italic py-1">
        {msg.text}
      </div>
    );
  }
  if (msg.role === "dice") {
    return (
      <div className="flex justify-center py-0.5">
        <div className="inline-flex items-center gap-2 bg-accent-dim border border-border rounded-full px-3.5 py-1.5 text-[13px] text-[var(--accent-text)] font-medium">
          🎲 {msg.type}
          <span className="text-[17px] font-bold text-accent">{msg.result}</span>
          {msg.dc != null && msg.dc > 0 && (
            <span className="text-[11px]">vs {msg.dc}</span>
          )}
        </div>
      </div>
    );
  }

  const isUser = msg.role === "user";
  if (chatStyle === "log") {
    return (
      <div
        className={[
          "text-sm leading-[1.7] py-1.5 border-b border-border last:border-0",
        ].join(" ")}
      >
        <span
          className={[
            "font-semibold mr-2",
            isUser ? "text-text-2" : "text-accent",
          ].join(" ")}
        >
          [{isUser ? characterName : "GM"}]
        </span>
        <TrpgMessage
          text={msg.text || ""}
          speakerProfiles={speakerProfiles}
          className="inline-block align-top"
        />
        {stampLine && (
          <span className="text-[11px] text-text-3 ml-2">{stampLine}</span>
        )}
        {canReadTts && (
          <MessageTtsButton
            sessionId={sessionId}
            messageId={msg.id}
            text={msg.text || ""}
          />
        )}
      </div>
    );
  }

  // GM messages: avatar + name as a thin header row, then full-width prose
  // with no bubble background. Lets the narration breathe — TRPG GM blocks
  // are often long and reading them inside a constrained bubble feels
  // claustrophobic.
  if (!isUser) {
    const steps = msg.thinkingSteps ?? [];
    return (
      <div className="flex flex-col w-full self-start gap-1.5">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-full shrink-0 flex items-center justify-center text-[11px] font-bold bg-accent-dim text-[var(--accent-text)]">
            GM
          </div>
          <span className="text-[11px] font-semibold text-text-3">
            {t("messageGmName")}
          </span>
        </div>
        {steps.length > 0 && (
          <details className="border-l border-border pl-3 mb-1">
            <summary className="cursor-pointer select-none list-none flex items-center gap-2 py-1 text-[10px] font-mono uppercase tracking-widest text-text-3">
              <span className="w-0.5 h-4 bg-accent inline-block" />
              <span className="flex-1">
                Chain of Thought ({steps.length})
              </span>
              <button
                type="button"
                onClick={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  // Snapshot is optional — when the GM reply pre-dates the
                  // bp_snapshot rollout (or the backend hasn't started
                  // persisting it for in-game turns yet), the panel falls
                  // back to live mode. Either way the button stays visible
                  // so debugging is one click away.
                  const snapshot: MessageSnapshot | undefined =
                    msg.id && msg.createdAt
                      ? {
                          message_id: msg.id,
                          message_created_at: msg.createdAt,
                          bp_snapshot: msg.bpSnapshot,
                          message_metadata: msg.metadata ?? undefined,
                        }
                      : undefined;
                  openDebugTab("context", snapshot);
                }}
                className="text-accent hover:opacity-80 normal-case tracking-normal font-sans"
              >
                {t("debugCtxOpenInPanel")}
              </button>
            </summary>
            <div className="mt-2 space-y-1 font-mono text-[11px] leading-relaxed text-text-3 whitespace-pre-wrap">
              {steps.map((step, idx) => (
                <div
                  key={`${idx}-${step.slice(0, 16)}`}
                  className="grid grid-cols-[24px_1fr] gap-2"
                >
                  <span className="text-right text-text-3">
                    {String(idx + 1).padStart(2, "0")}
                  </span>
                  <span>{step}</span>
                </div>
              ))}
            </div>
          </details>
        )}
        <div className="text-text">
          {msg.id.startsWith("tmp-") && !(msg.text || "").trim() ? (
            <WaitingHint />
          ) : (
            <TrpgMessage
              text={msg.text || ""}
              speakerProfiles={speakerProfiles}
              streaming={msg.id.startsWith("tmp-")}
            />
          )}
        </div>
        {msg.pendingChecks && onResolvePending
          ? msg.pendingChecks
              .filter((p) => !p.resolved)
              .map((pending) => (
                <PendingCheckCard
                  key={pending.id}
                  pending={pending}
                  busy={resolvingPending}
                  onResolve={onResolvePending}
                />
              ))
          : null}
        {(stampLine || canReadTts) && (
          <div className="flex items-center justify-between gap-3 min-h-6">
            <div className="text-[10px] text-text-3">{stampLine}</div>
            {canReadTts && (
              <MessageTtsButton
                sessionId={sessionId}
                messageId={msg.id}
                text={msg.text || ""}
              />
            )}
          </div>
        )}
        {!msg.id.startsWith("tmp-") && sessionId ? (
          <PostprocessSteps sessionId={sessionId} messageId={msg.id} />
        ) : null}
      </div>
    );
  }

  // Player messages keep the bubble — short replies look right in a chip
  // shape, and the right-aligned bubble visually distinguishes "you said".
  return (
    <div className="flex gap-2.5 w-full max-w-[75%] self-end flex-row-reverse">
      <div className="w-7 h-7 rounded-full shrink-0 flex items-center justify-center text-[11px] font-bold mt-0.5 bg-user-bubble text-user-text">
        {characterInitial}
      </div>
      <div className="min-w-0 flex-1 flex flex-col items-end">
        <div className="text-[11px] font-semibold text-text-3 mb-1">
          {characterName}
        </div>
        <div className="px-4 py-2.5 rounded-2xl rounded-tr-sm shadow-sm bg-user-bubble text-user-text border border-black/5 dark:border-white/5 w-full">
          <TrpgMessage text={msg.text || ""} speakerProfiles={speakerProfiles} />
        </div>
        {stampLine && (
          <div className="text-[10px] text-text-3 mt-1">{stampLine}</div>
        )}
      </div>
    </div>
  );
}

function formatModelLabel(meta: Record<string, unknown> | null | undefined): string {
  if (!meta || typeof meta !== "object") return "";
  const provider = typeof meta.provider === "string" ? meta.provider : "";
  const model = typeof meta.model === "string" ? meta.model : "";
  if (provider && model) return `${provider} / ${model}`;
  return provider || model || "";
}
