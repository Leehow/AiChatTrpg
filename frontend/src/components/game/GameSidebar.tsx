import type { MediaVoice } from "../../api/types";
import type { ParsedRuleset } from "../../lib/ruleset/types";
import type { BondNpcEnrichResponse, VoiceIntroResponse } from "../../api/sessions";
import type { CharacterUISchema } from "../character_ui/widgets";
import { useResizableWidth } from "../../hooks/useResizableWidth";
import { RulesPanel } from "./panels/RulesPanel";
import { CharacterPanel, type CharacterStats } from "./panels/CharacterPanel";
import { ModulePanel, type ModuleState } from "./panels/ModulePanel";
import { MemoryPanel, type MemoryItem } from "./panels/MemoryPanel";
import { NotebookPanel, type PlayerNote } from "./panels/NotebookPanel";
import { NpcPanel, type NpcEntry } from "./panels/NpcPanel";

interface Props {
  parsed: ParsedRuleset;
  character: CharacterStats;
  rawCard?: Record<string, unknown> | null;
  characterSchema?: CharacterUISchema | null;
  module: ModuleState;
  memories: MemoryItem[];
  notes?: PlayerNote[];
  npcs?: NpcEntry[];
  accent: string;
  collapsed: boolean;
  drawerMode: boolean;
  onClose: () => void;
  onEditRules: () => void;
  onTranslateCharacter?: () => void;
  translatingCharacter?: boolean;
  /** Voice picker plumbing — populated only when a dialogue TTS model
   *  is configured. The same voice catalogue is shared by the PC card
   *  and every NPC modal so we only fetch it once at the shell level. */
  voiceOptions?: MediaVoice[];
  voiceProvider?: string;
  voiceModel?: string;
  pcVoice?: string;
  onChangePcVoice?: (voice: string) => Promise<void>;
  onChangeNpcVoice?: (npcKey: string, voice: string) => Promise<void>;
  /** Synthesise (or replay cached) PC voice intro. The panel button
   *  awaits the response and plays the returned audio_url locally. */
  onPlayPcVoiceIntro?: (opts?: { force?: boolean }) => Promise<VoiceIntroResponse>;
  /** Same shape, scoped to a single NPC. */
  onPlayNpcVoiceIntro?: (
    npcKey: string,
    opts?: { force?: boolean },
  ) => Promise<VoiceIntroResponse>;
  /** Re-runs the auto voice assignment across NPCs. Resolves with the
   *  counts of rematched vs. skipped (locked) NPCs so the panel can
   *  surface a small status pill. */
  onRematchNpcVoices?: (opts?: { force?: boolean }) => Promise<{
    rematched: number;
    skipped_locked: number;
  }>;
  /** Fills missing rich profile fields on bond NPCs via the session-level
   *  enrichment endpoint. The shell only passes this when at least one
   *  bond NPC currently needs enrichment, so the panel can rely on its
   *  presence as a "show the action" gate. */
  onEnrichBondNpcs?: () => Promise<BondNpcEnrichResponse>;
  onOpenNotes?: () => void;
}

export function GameSidebar({
  parsed,
  character,
  rawCard,
  characterSchema,
  module,
  memories,
  notes,
  npcs,
  accent,
  collapsed,
  drawerMode,
  onClose,
  onEditRules,
  onTranslateCharacter,
  translatingCharacter,
  voiceOptions,
  voiceProvider,
  voiceModel,
  pcVoice,
  onChangePcVoice,
  onChangeNpcVoice,
  onPlayPcVoiceIntro,
  onPlayNpcVoiceIntro,
  onRematchNpcVoices,
  onEnrichBondNpcs,
  onOpenNotes,
}: Props) {
  const { width, isDragging, onResizeStart } = useResizableWidth({
    storageKey: "chatrpg.gameSidebarWidth",
    defaultWidth: 272,
    minWidth: 220,
    maxWidth: 560,
    edge: "right",
  });

  // Drawer mode (mobile) keeps a fixed width; only desktop layout uses
  // the resizable width so the slide-in animation stays predictable.
  //
  // NOTE: don't put `relative` in the always-applied class list. Tailwind's
  // generated CSS orders `.relative` AFTER `.absolute`, so adding both lets
  // `relative` win — which would silently turn the drawer into an inline
  // sidebar that pushes the chat area on mobile. Keep `relative` only when
  // we actually need it (desktop layout, where the resize handle anchors
  // off the sidebar).
  const cls = [
    "shrink-0 bg-surface flex flex-col overflow-hidden h-full",
    isDragging
      ? ""
      : "transition-[width,transform,border-color] duration-[250ms] ease-[cubic-bezier(0.4,0,0.2,1)]",
    drawerMode
      ? "absolute top-0 left-0 bottom-0 w-[272px] z-50 shadow-[4px_0_24px_var(--shadow-md)]"
      : "relative",
    !drawerMode && !collapsed ? "border-r border-border" : "",
    drawerMode ? "border-r border-border" : "",
    drawerMode && collapsed ? "-translate-x-full" : "",
    !drawerMode && collapsed ? "border-r-0" : "",
  ].join(" ");

  const inlineStyle: React.CSSProperties = drawerMode
    ? {}
    : { width: collapsed ? 0 : `${width}px` };

  return (
    <>
      {drawerMode && !collapsed && (
        <div
          className="absolute inset-0 bg-black/30 z-40"
          onClick={onClose}
        />
      )}
      <aside className={cls} style={inlineStyle}>
        <div className="flex-1 overflow-y-auto px-2.5 py-2.5 flex flex-col gap-1.5 min-h-0">
          <RulesPanel parsed={parsed} onEdit={onEditRules} />
          <CharacterPanel
            character={character}
            accent={accent}
            rawCard={rawCard}
            schema={characterSchema}
            onTranslate={onTranslateCharacter}
            translating={translatingCharacter}
            voiceOptions={voiceOptions}
            voiceProvider={voiceProvider}
            voiceModel={voiceModel}
            currentVoice={pcVoice}
            onChangeVoice={onChangePcVoice}
            onPlayVoiceIntro={onPlayPcVoiceIntro}
          />
          <NpcPanel
            npcs={npcs ?? []}
            voiceOptions={voiceOptions}
            voiceProvider={voiceProvider}
            voiceModel={voiceModel}
            onChangeNpcVoice={onChangeNpcVoice}
            onPlayNpcVoiceIntro={onPlayNpcVoiceIntro}
            onRematchNpcVoices={onRematchNpcVoices}
            onEnrichBondNpcs={onEnrichBondNpcs}
          />
          <ModulePanel mod={module} />
          <MemoryPanel memories={memories} />
          <NotebookPanel notes={notes ?? []} onOpen={onOpenNotes} />
        </div>
        {!drawerMode && !collapsed && (
          <div
            onMouseDown={onResizeStart}
            title="Drag to resize"
            className="absolute top-0 right-0 bottom-0 w-1.5 cursor-col-resize hover:bg-accent/40 active:bg-accent/60 transition-colors z-10"
          />
        )}
      </aside>
    </>
  );
}
