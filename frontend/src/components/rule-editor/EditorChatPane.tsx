// Tab-content switcher for the rule editor. The actual tab buttons,
// LIVE badge, and RuleDesignPanel live in EditorDesignSidebar; this
// component just renders the chat surface for the currently selected
// agent. EditorShell owns the activeTab state.

import type { DraftDetailDTO } from "../../api/ruleset-drafts";
import { DiceChatPane } from "./DiceChatPane";
import type { TabId } from "./EditorDesignSidebar";
import { MainChatPane } from "./MainChatPane";

interface Props {
  draft: DraftDetailDTO;
  activeTab: TabId;
  onParsedChange: (parsed: Record<string, unknown>) => void;
  onEditApplied: () => void;
  onUndoEdit: (editId: string) => void;
  onDiceStateChanged: () => void;
  onDesignStateChanged: (ev: {
    design_phase: string;
    blueprint_id?: string;
  }) => void;
  onValidationReport: (report: Record<string, unknown>) => void;
}

export function EditorChatPane({
  draft,
  activeTab,
  onParsedChange,
  onEditApplied,
  onUndoEdit,
  onDiceStateChanged,
  onDesignStateChanged,
  onValidationReport,
}: Props) {
  return (
    <div className="flex flex-col h-full bg-bg overflow-hidden">
      {activeTab === "main" ? (
        <MainChatPane
          draft={draft}
          onParsedChange={onParsedChange}
          onEditApplied={onEditApplied}
          onUndoEdit={onUndoEdit}
          onDesignStateChanged={onDesignStateChanged}
          onValidationReport={onValidationReport}
          onDiceStateChanged={onDiceStateChanged}
        />
      ) : (
        <DiceChatPane
          draft={draft}
          onDiceStateChanged={onDiceStateChanged}
        />
      )}
    </div>
  );
}
