// Main rule-editor agent chat (persisted history). The dice agent has
// its own pane (DiceChatPane). EditorChatPane hosts both as tabs.

import { useEffect, useRef, useState } from "react";
import { useI18n } from "../../i18n";
import {
  listDraftMessagesAPI,
  streamDraftAgentMessage,
  type AgentEvent,
  type DraftDetailDTO,
  type DraftMessageDTO,
} from "../../api/ruleset-drafts";
import { ChatComposer } from "../ChatComposer";
import { ChatMessage } from "./ChatMessage";
import { ToolCallCard } from "./ToolCallCard";
import type { ChatTurn } from "./chatTypes";

interface Props {
  draft: DraftDetailDTO;
  onParsedChange: (parsed: Record<string, unknown>) => void;
  onEditApplied: () => void;
  onUndoEdit: (editId: string) => void;
  // Live updates from P0.6 design-state SSE events. The panel re-reads
  // the draft after the parent applies these.
  onDesignStateChanged: (ev: {
    design_phase: string;
    blueprint_id?: string;
  }) => void;
  onValidationReport: (report: Record<string, unknown>) => void;
  // Fired when the main agent's `request_dice_compile` lands a
  // procedure through the dice single-writer boundary. Parent reloads
  // the draft so the dice preview reflects the new dice_ir entry --
  // same callback the dice tab uses.
  onDiceStateChanged: () => void;
}

export function MainChatPane({
  draft,
  onParsedChange,
  onEditApplied,
  onUndoEdit,
  onDesignStateChanged,
  onValidationReport,
  onDiceStateChanged,
}: Props) {
  const { t } = useI18n();
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [composer, setComposer] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Load message history on mount / draft change.
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const msgs = await listDraftMessagesAPI(draft.id);
        if (cancelled) return;
        setTurns(messagesToTurns(msgs));
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : String(e));
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [draft.id]);

  // Auto-scroll on new content.
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [turns]);

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

    try {
      await streamDraftAgentMessage(draft.id, text, {
        onEvent: (ev) => handleAgentEvent(ev, localId),
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setStreaming(false);
    }
  };

  const handleAgentEvent = (ev: AgentEvent, localId: string) => {
    if (ev.type === "user_message_saved") {
      setTurns((prev) => {
        const out = [...prev];
        for (let i = out.length - 1; i >= 0; i--) {
          if (out[i].role === "user" && out[i].id.startsWith("tmp_user_")) {
            out[i] = { ...out[i], id: ev.message_id };
            break;
          }
        }
        return out;
      });
    } else if (ev.type === "message_started" || ev.type === "message_completed") {
      // Each agent iteration emits its own message_started, but
      // visually we want all iterations of a single user→agent turn to
      // collapse into one card. Don't rename the turn id; just leave
      // the temp localId in place so subsequent setTurns lookups
      // always find the same turn.
      // (Persisted history reload uses the DB-backed message ids
      // directly, so the temp ids only matter for the streaming pass.)
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
    } else if (ev.type === "edit_applied") {
      onParsedChange(ev.parsed_v6_after);
      onEditApplied();
    } else if (ev.type === "design_state_changed") {
      onDesignStateChanged({
        design_phase: ev.design_phase,
        blueprint_id: ev.blueprint_id,
      });
    } else if (ev.type === "validation_report") {
      onValidationReport(ev.validation_report);
    } else if (ev.type === "dice_state_changed") {
      // Main-agent dice bridge persisted into parsed_v6.dice_ir;
      // re-fetch the draft so the dice preview shows the new
      // procedure -- same callback the dice tab uses.
      onDiceStateChanged();
    } else if (ev.type === "dice_compile_progress") {
      // Additive progress event; nothing to render yet (the generic
      // tool_call_started / tool_result cards already surface this
      // turn's tool activity). Left as a typed branch so future UI
      // can wire in without changing the contract.
    } else if (ev.type === "turn_done") {
      if (ev.stop_reason === "error" && ev.error) {
        setError(ev.error);
      } else if (ev.stop_reason === "max_iters") {
        setError(t("draftAgentMaxIters"));
      }
    }
  };

  // Identity passthrough — the visible turn keeps its temporary id for
  // the lifetime of the stream so multi-iteration agent turns
  // (message_started fires once per iter) all land on the same card.
  const resolveLocalId = (localId: string) => localId;

  return (
    <div className="flex flex-col h-full bg-bg overflow-hidden">
      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto p-4 flex flex-col gap-3"
      >
        {turns.length === 0 && !streaming && (
          <div className="text-[12px] text-text-3 leading-relaxed text-center my-8 px-6">
            {t("draftAgentEmpty")}
          </div>
        )}
        {turns
          .filter((tt) => tt.role !== "tool")
          .map((tt) => (
            <ChatMessageWithToolCalls
              key={tt.id}
              turn={tt}
              onUndoEdit={onUndoEdit}
            />
          ))}
        {streaming && (
          <div className="text-[11px] text-text-3 italic">{t("draftAgentStreaming")}</div>
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
          placeholder={t("draftAgentComposerPlaceholder")}
          disabled={streaming}
          sending={streaming}
          sendTitle={streaming ? t("draftAgentStreaming") : t("draftAgentSend")}
        />
      </div>
    </div>
  );
}

function ChatMessageWithToolCalls({
  turn,
  onUndoEdit,
}: {
  turn: ChatTurn;
  onUndoEdit: (editId: string) => void;
}) {
  return (
    <div className="flex flex-col gap-2">
      <ChatMessage role={turn.role} text={turn.text} />
      {turn.toolCalls?.map((tc) => (
        <ToolCallCard key={tc.callId} call={tc} onUndo={onUndoEdit} />
      ))}
    </div>
  );
}

function messagesToTurns(rows: DraftMessageDTO[]): ChatTurn[] {
  const turns: ChatTurn[] = [];
  let currentAssistant: ChatTurn | null = null;

  for (const row of rows) {
    if (row.role === "user") {
      currentAssistant = null;
      turns.push(messageToTurn(row));
      continue;
    }
    if (row.role === "assistant") {
      const turn = messageToTurn(row);
      currentAssistant = turn;
      turns.push(turn);
      continue;
    }
    if (row.role === "tool") {
      const tool = parseToolMessage(row);
      if (!currentAssistant?.toolCalls) continue;
      currentAssistant.toolCalls = currentAssistant.toolCalls.map((call) =>
        call.callId === tool.callId
          ? {
              ...call,
              result: tool.result,
              editId: tool.editId,
              status: tool.isError ? "error" : "ok",
            }
          : call,
      );
    }
  }

  return turns;
}

function messageToTurn(m: DraftMessageDTO): ChatTurn {
  if (m.role === "assistant") {
    const c = m.content as {
      text?: string;
      tool_calls?: Array<{
        id: string;
        function: { name: string; arguments: string };
      }>;
    };
    return {
      id: m.id,
      role: "assistant",
      text: c.text,
      toolCalls: (c.tool_calls || []).map((tc) => ({
        callId: tc.id,
        toolName: tc.function.name,
        argsBuf: tc.function.arguments,
        status: "ok" as const,
      })),
    };
  }
  const c = m.content as { text?: string };
  return { id: m.id, role: "user", text: c.text };
}

function parseToolMessage(m: DraftMessageDTO): {
  callId: string;
  result: Record<string, unknown>;
  editId: string | null;
  isError: boolean;
} {
  const c = m.content as {
    tool_call_id?: string;
    content?: string;
  };
  let result: Record<string, unknown> = {};
  try {
    result = c.content ? JSON.parse(c.content) : {};
  } catch {
    result = { raw: c.content };
  }
  const editId =
    typeof result.edit_id === "string" ? result.edit_id : null;
  return {
    callId: String(c.tool_call_id || ""),
    result,
    editId,
    isError: Boolean((result as { error?: boolean }).error),
  };
}
