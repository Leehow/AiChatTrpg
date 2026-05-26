// Dice rule design agent chat — fully persisted alongside the main
// rule editor agent. On mount we hydrate `turns` + the OpenAI-format
// `historyRef` from `ruleset_draft_messages` rows with `kind="dice"`,
// so reload/refresh leaves the chat intact. The compiled spec also
// lives in `draft.parsed_v6.dice_ir` (data of record); the chat is
// the human-readable trail of how it got there.

import { useEffect, useRef, useState } from "react";
import { useI18n } from "../../i18n";
import {
  listDraftMessagesAPI,
  streamDiceAgentMessage,
  type DiceAgentEvent,
  type DraftDetailDTO,
  type DraftMessageDTO,
} from "../../api/ruleset-drafts";
import { ChatComposer } from "../ChatComposer";
import { ChatMessage } from "./ChatMessage";
import { ToolCallCard } from "./ToolCallCard";
import type { ChatTurn } from "./chatTypes";

interface Props {
  draft: DraftDetailDTO;
  onDiceStateChanged: () => void;
}

export function DiceChatPane({ draft, onDiceStateChanged }: Props) {
  const { t } = useI18n();
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [composer, setComposer] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  // OpenAI-format history persisted across turns in component state.
  const historyRef = useRef<Array<Record<string, unknown>>>([]);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [turns]);

  // Hydrate the dice transcript from DB on mount. We rebuild both the
  // visible `turns` list and the OpenAI `historyRef` so the next call
  // to streamDiceAgentMessage sees the full prior context. Each
  // assistant message is one ChatTurn that absorbs subsequent tool
  // results into its toolCalls list (mirroring the live event flow).
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const rows: DraftMessageDTO[] =
          await listDraftMessagesAPI(draft.id, 0, "dice");
        if (cancelled) return;
        const turnsOut: ChatTurn[] = [];
        const history: Array<Record<string, unknown>> = [];
        let currentAssistant: ChatTurn | null = null;
        for (const row of rows) {
          const msg = row.content || {};
          history.push(msg as Record<string, unknown>);
          if (row.role === "user") {
            currentAssistant = null;
            turnsOut.push({
              id: row.id,
              role: "user",
              text: String(
                (msg as Record<string, unknown>).content ?? "",
              ),
            });
          } else if (row.role === "assistant") {
            const text = String(
              (msg as Record<string, unknown>).content ?? "",
            );
            const tcs = Array.isArray(
              (msg as Record<string, unknown>).tool_calls,
            )
              ? ((msg as Record<string, unknown>).tool_calls as Array<
                  Record<string, unknown>
                >)
              : [];
            const turn: ChatTurn = {
              id: row.id,
              role: "assistant",
              text,
              toolCalls: tcs.map((tc) => ({
                callId: String(tc.id ?? ""),
                toolName: String(
                  ((tc.function as Record<string, unknown>) || {}).name ?? "",
                ),
                argsBuf: String(
                  ((tc.function as Record<string, unknown>) || {})
                    .arguments ?? "",
                ),
                status: "ok",
              })),
            };
            currentAssistant = turn;
            turnsOut.push(turn);
          } else if (row.role === "tool") {
            const callId = String(
              (msg as Record<string, unknown>).tool_call_id ?? "",
            );
            const raw = (msg as Record<string, unknown>).content;
            let parsed: Record<string, unknown> | undefined;
            if (typeof raw === "string") {
              try {
                const j = JSON.parse(raw);
                parsed = j && typeof j === "object" ? j : undefined;
              } catch {
                parsed = undefined;
              }
            } else if (raw && typeof raw === "object") {
              parsed = raw as Record<string, unknown>;
            }
            if (currentAssistant?.toolCalls) {
              currentAssistant.toolCalls = currentAssistant.toolCalls.map(
                (c) =>
                  c.callId === callId
                    ? { ...c, result: parsed, status: "ok" as const }
                    : c,
              );
            }
          }
        }
        setTurns(turnsOut);
        historyRef.current = history;
      } catch (err) {
        console.warn("[chatrpg] dice transcript hydrate failed:", err);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [draft.id]);

  // Identity passthrough — see MainChatPane for the rationale.
  const resolveLocalId = (localId: string) => localId;

  const submit = async () => {
    const text = composer.trim();
    if (!text || streaming) return;
    setComposer("");
    setStreaming(true);
    setError(null);

    const localId = `tmp_asst_${Date.now()}`;
    setTurns((prev) => [
      ...prev,
      { id: `tmp_user_${Date.now()}`, role: "user", text },
      { id: localId, role: "assistant", text: "", toolCalls: [] },
    ]);

    // Build current history snapshot to send (excludes the just-added
    // pending user/assistant placeholder turns).
    const history = [...historyRef.current];

    try {
      await streamDiceAgentMessage(draft.id, text, history, {
        onEvent: (ev) => handleEvent(ev, localId, text),
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setStreaming(false);
    }
  };

  const handleEvent = (
    ev: DiceAgentEvent, localId: string, userText: string,
  ) => {
    if (ev.type === "user_message_saved") {
      // Push the user msg to history.
      historyRef.current.push({ role: "user", content: userText });
    } else if (ev.type === "message_started") {
      // Each agent iteration emits message_started with a fresh id;
      // we collapse them into a single visible turn (no rename).
    } else if (ev.type === "text_delta") {
      setTurns((prev) =>
        prev.map((tt) =>
          tt.id === resolveLocalId(localId)
            ? { ...tt, text: (tt.text || "") + ev.delta }
            : tt,
        ),
      );
    } else if (ev.type === "tool_call_started") {
      setTurns((prev) =>
        prev.map((tt) =>
          tt.id === resolveLocalId(localId)
            ? {
                ...tt,
                toolCalls: [
                  ...(tt.toolCalls || []),
                  {
                    callId: ev.call_id,
                    toolName: ev.tool_name,
                    argsBuf: "",
                    status: "running",
                  },
                ],
              }
            : tt,
        ),
      );
    } else if (ev.type === "tool_call_delta") {
      setTurns((prev) =>
        prev.map((tt) =>
          tt.id === resolveLocalId(localId)
            ? {
                ...tt,
                toolCalls: (tt.toolCalls || []).map((c) =>
                  c.callId === ev.call_id
                    ? { ...c, argsBuf: c.argsBuf + ev.args_delta }
                    : c,
                ),
              }
            : tt,
        ),
      );
    } else if (ev.type === "tool_result") {
      const isError = ev.result && (ev.result as { error?: boolean }).error;
      setTurns((prev) =>
        prev.map((tt) =>
          tt.id === resolveLocalId(localId)
            ? {
                ...tt,
                toolCalls: (tt.toolCalls || []).map((c) =>
                  c.callId === ev.call_id
                    ? {
                        ...c,
                        result: ev.result,
                        editId: ev.edit_id ?? null,
                        status: isError ? "error" : "ok",
                      }
                    : c,
                ),
              }
            : tt,
        ),
      );
    } else if (ev.type === "dice_state_changed") {
      onDiceStateChanged();
    } else if (ev.type === "message_completed") {
      // Append assistant turn to OpenAI history. The agent itself
      // emits the assembled assistant content + tool_calls in this
      // event via its `text` and `tool_calls` fields.
      const text = (ev as { text?: string }).text || "";
      const toolCalls = (ev as { tool_calls?: unknown }).tool_calls;
      const asstMsg: Record<string, unknown> = { role: "assistant" };
      asstMsg.content = text || null;
      if (Array.isArray(toolCalls) && toolCalls.length > 0) {
        asstMsg.tool_calls = toolCalls;
      }
      historyRef.current.push(asstMsg);
    } else if (ev.type === "turn_done") {
      if (ev.stop_reason === "error" && ev.error) {
        setError(ev.error);
      } else if (ev.stop_reason === "max_iters") {
        setError(t("draftAgentMaxIters"));
      }
    }
    // Append tool result to history alongside its tool_call_id.
    if (ev.type === "tool_result") {
      historyRef.current.push({
        role: "tool",
        tool_call_id: ev.call_id,
        content: JSON.stringify(ev.result),
      });
    }
  };

  return (
    <div className="flex flex-col h-full bg-bg overflow-hidden">
      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto p-4 flex flex-col gap-3"
      >
        {turns.length === 0 && !streaming && (
          <CompiledSummary draft={draft} />
        )}
        {turns
          .filter((tt) => tt.role !== "tool")
          .map((tt) => (
            <div key={tt.id} className="flex flex-col gap-2">
              <ChatMessage role={tt.role} text={tt.text} />
              {tt.toolCalls?.map((tc) => (
                <ToolCallCard key={tc.callId} call={tc} />
              ))}
            </div>
          ))}
        {streaming && (
          <div className="text-[11px] text-text-3 italic">
            {t("diceAgentStreaming")}
          </div>
        )}
      </div>
      <div className="shrink-0 bg-bg pt-2">
        {error && (
          <div className="mx-4 mb-2 text-[11px] text-[var(--accent-text)] bg-accent-dim border border-border rounded p-2">
            {error}
          </div>
        )}
        <ChatComposer
          value={composer}
          onChange={setComposer}
          onSubmit={() => void submit()}
          placeholder={t("diceAgentComposerPlaceholder")}
          disabled={streaming}
          sending={streaming}
          sendTitle={streaming ? t("diceAgentStreaming") : t("draftAgentSend")}
        />
      </div>
    </div>
  );
}


interface CompiledSpec {
  procedure_id: string;
  name?: string;
  validation?: { ok?: boolean };
}

function extractCompiledSpecs(draft: DraftDetailDTO): CompiledSpec[] {
  const v6 = (draft.parsed_v6 ?? {}) as Record<string, unknown>;
  const dir = (v6.dice_ir as Record<string, unknown> | undefined) ?? {};
  const pkg = (dir.package as Record<string, unknown> | undefined) ?? {};
  const compiled =
    (pkg.compiled as Record<string, unknown> | undefined) ?? {};
  const specs = compiled.check_specs;
  if (!Array.isArray(specs)) return [];
  return specs.filter(
    (s): s is CompiledSpec =>
      typeof s === "object" && s !== null && "procedure_id" in s,
  );
}

function CompiledSummary({ draft }: { draft: DraftDetailDTO }) {
  const { t } = useI18n();
  const specs = extractCompiledSpecs(draft);
  if (specs.length === 0) {
    return (
      <div className="text-[12px] text-text-3 leading-relaxed text-center my-8 px-6">
        {t("diceAgentEmpty")}
      </div>
    );
  }
  return (
    <div className="rounded-2xl border border-border bg-surface p-4 mt-2">
      <div className="text-[11px] font-semibold tracking-[0.08em] uppercase text-text-3 mb-3">
        {t("diceAgentSummaryTitle", { n: specs.length })}
      </div>
      <ul className="flex flex-col gap-1.5">
        {specs.map((s) => {
          const ok = s.validation?.ok !== false;
          return (
            <li
              key={s.procedure_id}
              className="flex items-center gap-2 text-[12px] font-mono px-2 py-1 rounded bg-surface-2"
            >
              <span
                className={[
                  "w-2 h-2 rounded-full shrink-0",
                  ok ? "bg-green-500" : "bg-red-500",
                ].join(" ")}
                aria-hidden="true"
              />
              <span className="font-semibold">{s.procedure_id}</span>
              {s.name && (
                <span className="text-text-3 truncate">· {s.name}</span>
              )}
            </li>
          );
        })}
      </ul>
      <div className="text-[11px] text-text-3 mt-3 leading-relaxed">
        {t("diceAgentSummaryHint")}
      </div>
    </div>
  );
}
