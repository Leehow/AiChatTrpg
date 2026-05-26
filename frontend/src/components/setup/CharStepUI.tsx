import { useI18n } from "../../i18n";
import type { ReactNode } from "react";
import type { CharacterPoolItemDTO } from "../../api/characters";
import type {
  AdventureStartOptionsDTO,
  CharacterDraftMessageDTO,
} from "../../api/sessions";
import { TrpgMessage } from "../game/TrpgMessage";
import { MessageTtsButton } from "../game/MessageTtsButton";
import { WaitingHint } from "../game/WaitingHint";
import {
  openDebugTab,
  type BpSnapshot,
  type MessageSnapshot,
} from "../../lib/debugUiBus";

type Translate = ReturnType<typeof useI18n>["t"];

function formatDraftTime(iso?: string): string {
  if (!iso || iso === "__streaming__") return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  return `${y}-${m}-${day} ${hh}:${mm}`;
}

function formatModelLabel(meta: Record<string, unknown> | null | undefined): string {
  if (!meta || typeof meta !== "object") return "";
  const provider = typeof meta.provider === "string" ? meta.provider : "";
  const model = typeof meta.model === "string" ? meta.model : "";
  if (provider && model) return `${provider} / ${model}`;
  return provider || model || "";
}

// Pull a per-message bp_snapshot out of the message metadata so the right-rail
// debug panel can scope its Context tab to the GM turn the user clicked. If
// the message predates the snapshot rollout (no metadata.bp_snapshot, no id,
// no created_at) we return undefined and the panel falls back to live mode.
function _messageSnapshotFor(
  msg: CharacterDraftMessageDTO,
): MessageSnapshot | undefined {
  const meta = msg.metadata;
  if (!meta || typeof meta !== "object") return undefined;
  const raw = (meta as Record<string, unknown>).bp_snapshot;
  if (!raw || typeof raw !== "object") return undefined;
  const id = msg.id;
  const createdAt = msg.created_at;
  if (!id || !createdAt) return undefined;
  return {
    message_id: id,
    message_created_at: createdAt,
    bp_snapshot: raw as BpSnapshot,
    message_metadata: meta as Record<string, unknown>,
  };
}

export function EntryChooser({
  onCreate,
  onImport,
  onPool,
}: {
  onCreate: () => void;
  onImport: () => void;
  onPool: () => void;
}) {
  const { t } = useI18n();
  const cards = [
    { key: "create", title: t("setupCharEntryCreate"), desc: t("setupCharEntryCreateDesc"), onClick: onCreate },
    { key: "import", title: t("setupCharEntryImport"), desc: t("setupCharEntryImportDesc"), onClick: onImport },
    { key: "pool", title: t("setupCharEntryPool"), desc: t("setupCharEntryPoolDesc"), onClick: onPool },
  ];
  return (
    <div>
      <p className="text-sm text-text-3 mb-3">{t("setupCharEntryHint")}</p>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        {cards.map((card) => (
          <button
            key={card.key}
            type="button"
            onClick={card.onClick}
            className="text-left bg-surface border border-border hover:border-accent hover:bg-surface-2 rounded-xl px-4 py-5 transition flex flex-col gap-2 min-h-[140px]"
          >
            <div className="text-sm font-semibold text-text">{card.title}</div>
            <div className="text-xs text-text-3 leading-relaxed">{card.desc}</div>
          </button>
        ))}
      </div>
    </div>
  );
}

export function PoolModal({
  items,
  loading,
  onClose,
  onPick,
  onRefresh,
}: {
  items: CharacterPoolItemDTO[];
  loading: boolean;
  onClose: () => void;
  onPick: (item: CharacterPoolItemDTO) => void;
  onRefresh: () => void;
}) {
  const { t } = useI18n();
  return (
    <div
      className="fixed inset-0 bg-black/45 z-[300] flex items-center justify-center p-5 anim-fade-in"
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div className="bg-surface border border-border rounded-2xl p-6 w-[480px] max-w-full max-h-[80vh] overflow-y-auto shadow-[0_24px_64px_var(--shadow-md)]">
        <div className="flex items-center justify-between mb-4">
          <div className="text-base font-semibold">
            {t("setupCharPoolModalTitle")}
          </div>
          <button
            type="button"
            onClick={onRefresh}
            disabled={loading}
            className="text-xs text-accent hover:opacity-80 disabled:opacity-40"
          >
            {t("setupCharPoolRefresh")}
          </button>
        </div>
        {loading ? (
          <div className="text-xs text-text-3 py-8 text-center">{t("setupCharPoolLoading")}</div>
        ) : items.length === 0 ? (
          <div className="text-xs text-text-3 py-8 text-center">{t("setupCharPoolEmpty")}</div>
        ) : (
          <div className="divide-y divide-border border-y border-border">
            {items.map((item) => (
              <button
                key={item.id}
                type="button"
                onClick={() => onPick(item)}
                className="w-full text-left py-3 px-1 hover:bg-surface-2 transition"
              >
                <div className="text-sm font-semibold text-text truncate">
                  {item.name || t("setupCharFallbackName")}
                </div>
                <div className="text-[11px] text-text-3 mt-1 truncate">
                  {sourceLabel(item.source, t)} · {item.ruleset_title}
                </div>
              </button>
            ))}
          </div>
        )}
        <div className="mt-4 flex justify-end">
          <button
            type="button"
            onClick={onClose}
            className="px-3 py-2 rounded-lg border border-border text-xs text-text-2 hover:bg-surface-2 transition"
          >
            {t("setupCharPoolModalClose")}
          </button>
        </div>
      </div>
    </div>
  );
}

export function SetupChatMessage({
  msg,
  sessionId,
}: {
  msg: CharacterDraftMessageDTO;
  sessionId?: string | null;
}) {
  const { t } = useI18n();
  const mine = msg.role === "user";
  const thinkingSteps = msg.thinking_steps || [];
  const time = formatDraftTime(msg.created_at);
  const modelLabel = formatModelLabel(msg.metadata);
  const stampLine = [time, modelLabel].filter(Boolean).join(" · ");
  if (!mine) {
    const canReadTts =
      Boolean(sessionId)
      && Boolean(msg.id)
      && msg.created_at !== "__streaming__"
      && Boolean((msg.content || "").trim());
    return (
      <div className="grid grid-cols-[28px_1fr] gap-3 py-2">
        <div className="flex flex-col items-center pt-1">
          <div className="w-7 h-7 rounded-full bg-accent-dim text-[var(--accent-text)] flex items-center justify-center text-[11px] font-bold">
            GM
          </div>
        </div>
        <div className="min-w-0">
          {thinkingSteps.length > 0 && (
            <details
              className="mb-3 border-l border-border pl-3"
              open={msg.created_at === "__streaming__"}
            >
              <summary className="cursor-pointer select-none list-none flex items-center gap-2 py-1 text-[10px] font-mono uppercase tracking-widest text-text-3">
                <span className="w-0.5 h-4 bg-accent inline-block" />
                <span className="flex-1">
                  Chain of Thought ({thinkingSteps.length})
                </span>
                <button
                  type="button"
                  onClick={(e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    openDebugTab("context", _messageSnapshotFor(msg));
                  }}
                  className="text-accent hover:opacity-80 normal-case tracking-normal font-sans"
                >
                  {t("debugCtxOpenInPanel")}
                </button>
              </summary>
              <div className="mt-2 space-y-1 font-mono text-[11px] leading-relaxed text-text-3 whitespace-pre-wrap">
                {thinkingSteps.map((step, idx) => (
                  <div key={`${idx}-${step.slice(0, 16)}`} className="grid grid-cols-[24px_1fr] gap-2">
                    <span className="text-right text-text-3">
                      {String(idx + 1).padStart(2, "0")}
                    </span>
                    <span>{step}</span>
                  </div>
                ))}
              </div>
            </details>
          )}
          {msg.created_at === "__streaming__" && !(msg.content || "").trim() ? (
            <WaitingHint />
          ) : (
            <TrpgMessage
              text={msg.content}
              forceTrpg={false}
              streaming={msg.created_at === "__streaming__"}
            />
          )}
          {(stampLine || canReadTts) && (
            <div className="flex items-center justify-between gap-3 min-h-6 mt-1">
              <div className="text-[10px] text-text-3">{stampLine}</div>
              {canReadTts && (
                <MessageTtsButton
                  sessionId={sessionId}
                  messageId={msg.id!}
                  text={msg.content || ""}
                />
              )}
            </div>
          )}
        </div>
      </div>
    );
  }
  const userLabel = t("setupCharUserLabel");
  const userInitial = (userLabel || "·").trim().charAt(0).toUpperCase();
  return (
    <div className="flex gap-2.5 max-w-[75%] self-end flex-row-reverse py-1 ml-auto">
      <div className="w-7 h-7 rounded-full shrink-0 flex items-center justify-center text-[11px] font-bold mt-0.5 bg-user-bubble text-user-text">
        {userInitial}
      </div>
      <div className="min-w-0 flex flex-col items-end">
        <div className="px-4 py-2.5 rounded-2xl rounded-tr-sm shadow-sm bg-user-bubble text-user-text border border-black/5 dark:border-white/5">
          <TrpgMessage text={msg.content} forceTrpg={false} />
        </div>
        {stampLine && <div className="text-[10px] text-text-3 mt-1">{stampLine}</div>}
      </div>
    </div>
  );
}

export function ReadyCallout({
  generating,
  onGenerate,
}: {
  generating: boolean;
  onGenerate: () => void;
}) {
  const { t } = useI18n();
  return (
    <div className="rounded-xl border border-accent bg-accent-dim p-4">
      <div className="text-sm font-semibold text-[var(--accent-text)] mb-1">
        {t("setupCharReadyTitle")}
      </div>
      <div className="text-xs text-text-2 leading-relaxed mb-3">
        {t("setupCharReadyBody")}
      </div>
      <button
        type="button"
        onClick={onGenerate}
        disabled={generating}
        className="px-4 py-2 rounded-lg bg-accent text-white text-sm font-medium hover:opacity-90 disabled:opacity-40 disabled:cursor-not-allowed transition"
      >
        {generating ? t("setupCharGenerating") : t("setupCharGenerateCard")}
      </button>
    </div>
  );
}

export function CharacterDraftCard({
  character,
  title,
  generating,
  confirming,
  confirmDisabled,
  extra,
  onGenerate,
  onConfirm,
}: {
  character: Record<string, unknown>;
  title: string;
  generating: boolean;
  confirming: boolean;
  confirmDisabled?: boolean;
  extra?: ReactNode;
  onGenerate: () => void;
  onConfirm: () => void;
}) {
  const { t } = useI18n();
  return (
    <aside className="bg-surface border border-border rounded-xl p-5">
      <div className="text-xs text-accent font-semibold mb-1">
        {t("setupCharGeneratedTitle")}
      </div>
      <div className="text-lg font-semibold text-text mb-3 break-words">
        {title || t("setupCharFallbackName")}
      </div>
      <details className="mb-4">
        <summary className="cursor-pointer text-xs text-text-3 hover:text-text">
          {t("setupCharJsonPreview")}
        </summary>
        <pre className="mt-2 max-h-[260px] overflow-auto rounded-lg bg-surface-2 border border-border p-3 text-[11px] leading-relaxed text-text-2 whitespace-pre-wrap">
          {JSON.stringify(character, null, 2)}
        </pre>
      </details>
      {extra}
      <div className="flex flex-col sm:flex-row gap-2">
        <button
          type="button"
          onClick={onGenerate}
          disabled={generating || confirming}
          className="flex-1 px-3 py-2.5 rounded-xl border border-border text-text-2 text-sm font-medium hover:bg-surface-2 disabled:opacity-40 disabled:cursor-not-allowed transition"
        >
          {generating ? t("setupCharGenerating") : t("setupCharRegenerateCard")}
        </button>
        <button
          type="button"
          onClick={onConfirm}
          disabled={confirming || generating || confirmDisabled}
          className="flex-1 px-3 py-3 rounded-xl bg-accent text-white text-sm font-medium hover:opacity-90 active:scale-[0.98] disabled:opacity-40 disabled:cursor-not-allowed transition"
        >
          {confirming ? t("setupCharConfirming") : t("setupCharConfirmEnter")} →
        </button>
      </div>
    </aside>
  );
}

export function AdventureStartSelector({
  options,
  loading,
  selectedIndex,
  disabled,
  onSelect,
}: {
  options: AdventureStartOptionsDTO | null;
  loading: boolean;
  selectedIndex: number | null;
  disabled: boolean;
  onSelect: (index: number) => void;
}) {
  const { t } = useI18n();
  if (loading) {
    return (
      <div className="border-t border-border pt-4 mb-4 text-xs text-text-3">
        {t("setupStartLoading")}
      </div>
    );
  }
  if (!options || !options.has_module) {
    return null;
  }
  const units = options.units || [];
  const waiting = options.semantic_status === "pending" || options.semantic_status === "running";
  return (
    <div className="border-t border-border pt-4 mb-4">
      <div className="flex items-center justify-between gap-3 mb-2">
        <div>
          <div className="text-xs font-semibold text-text">
            {t("setupStartTitle")}
          </div>
          <div className="text-[11px] text-text-3 mt-0.5">
            {kindSentence(options.anchor_type, t)}
          </div>
        </div>
        {options.module_title && (
          <div className="shrink-0 max-w-[36%] truncate text-[10px] text-text-3">
            {options.module_title}
          </div>
        )}
      </div>

      {waiting ? (
        <div className="rounded-lg border border-border bg-surface-2 px-3 py-2 text-[11px] text-text-3">
          {t("setupStartParsing")}
        </div>
      ) : units.length === 0 ? (
        <div className="rounded-lg border border-border bg-surface-2 px-3 py-2 text-[11px] text-text-3">
          {t("setupStartNoUnits")}
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          {units.map((unit) => {
            const active = selectedIndex === unit.index;
            return (
              <button
                key={`${unit.index}-${unit.unit_id || unit.title}`}
                type="button"
                disabled={disabled}
                onClick={() => onSelect(unit.index)}
                className={[
                  "text-left rounded-lg border px-3 py-2.5 transition min-h-[86px]",
                  active
                    ? "border-accent bg-accent-dim"
                    : "border-border bg-surface-2 hover:border-border-2",
                  disabled ? "opacity-60 cursor-not-allowed" : "",
                ].join(" ")}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[10px] uppercase tracking-[0.06em] text-accent font-semibold">
                    {kindLabel(unit.kind, t)}
                  </span>
                  {active && (
                    <span className="text-[10px] text-accent font-semibold">
                      {t("setupStartSelected")}
                    </span>
                  )}
                </div>
                <div className="mt-1 text-sm font-semibold text-text line-clamp-2">
                  {unit.title}
                </div>
                {unit.summary && (
                  <div className="mt-1 text-[11px] leading-snug text-text-3 line-clamp-2">
                    {unit.summary}
                  </div>
                )}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

export function Dot({ delay }: { delay: number }) {
  return (
    <div
      className="w-2 h-2 rounded-full bg-accent"
      style={{
        animation: "chatrpg-dot-bounce 1.2s infinite",
        animationDelay: `${delay}s`,
      }}
    />
  );
}

function kindLabel(kind: string, t: Translate): string {
  if (kind === "location") return t("setupStartKindLocation");
  if (kind === "mission" || kind === "task") return t("setupStartKindMission");
  if (kind === "scene") return t("setupStartKindScene");
  return t("setupStartKindChapter");
}

function kindSentence(kind: string, t: Translate): string {
  if (kind === "location") return t("setupStartChooseLocation");
  if (kind === "mission" || kind === "task") return t("setupStartChooseMission");
  return t("setupStartChooseChapter");
}

export function extractCharacterTitle(character: Record<string, unknown>): string {
  const identity = asRecord(character.identity);
  return (
    stringValue(character.display_name) ||
    stringValue(character.name) ||
    stringValue(character.character_name) ||
    stringValue(identity.display_name) ||
    stringValue(identity.name) ||
    stringValue(identity.character_name) ||
    stringValue(identity.full_name) ||
    ""
  );
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function stringValue(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function sourceLabel(source: string, t: Translate): string {
  if (source === "uploaded") return t("setupCharSourceUploaded");
  if (source === "selected") return t("setupCharSourceSelected");
  if (source === "manual") return t("setupCharSourceManual");
  if (source === "confirmed") return t("setupCharSourceConfirmed");
  return t("setupCharSourceGenerated");
}
