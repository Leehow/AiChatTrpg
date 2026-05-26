import { useCallback, useEffect, useMemo, useState } from "react";
import { useI18n } from "../../i18n";
import { useIsMobile } from "../../hooks/useIsMobile";
import type { ParsedRuleset } from "../../lib/ruleset/types";
import { GameSidebar } from "./GameSidebar";
import { ChatArea } from "./ChatArea";
import { DiceModal } from "./DiceModal";
import { DiceBox3D } from "../dice/DiceBox3D";
import { CoinFlip } from "../dice/CoinFlip";
import { TrpgSceneHud } from "./TrpgSceneHud";
import { NotesOverlay } from "./panels/NotesOverlay";
import { buildBuckets, SceneTabs } from "./SceneTabs";
import type { ChatMessage } from "./Message";
import type { TrpgSceneHudSnapshot } from "./trpgHudTypes";
import type { ModuleState } from "./panels/ModulePanel";
import {
  getSessionAPI,
  translateCharacterAPI,
  translateNpcsAPI,
  type SessionDetailDTO,
} from "../../api/sessions";
import { filterDisplayedMessages } from "./gameShell/messageHelpers";
import {
  buildSpeakerProfiles,
  MEMORIES_DEFAULT,
  MODULE_DEFAULT,
  readCharacter,
} from "./gameShell/sessionHelpers";
import {
  deriveCharacterSchema,
  derivePcVoice,
  derivePlayerNotes,
  deriveSidebarNpcs,
} from "./gameShell/sidebarDerivations";
import { useGameMessages } from "./gameShell/useGameMessages";
import { useVoiceCatalogue } from "./gameShell/useVoiceCatalogue";

interface Props {
  sessionId: string;
  parsed: ParsedRuleset;
  theme: "warm" | "slate";
  sidebarOpen: boolean;
  onCloseSidebar: () => void;
  onOpenRulesetView: () => void;
}

export function GameShell({
  sessionId,
  parsed,
  theme,
  sidebarOpen,
  onCloseSidebar,
  onOpenRulesetView,
}: Props) {
  const { t, locale: globalLocale } = useI18n();
  const [showDice, setShowDice] = useState(false);
  const [session, setSession] = useState<SessionDetailDTO | null>(null);
  const [translatingCharacter, setTranslatingCharacter] = useState(false);
  const [sceneHudSnapshot, setSceneHudSnapshot] =
    useState<TrpgSceneHudSnapshot | null>(null);
  const [notesOverlayOpen, setNotesOverlayOpen] = useState(false);
  useEffect(() => {
    setSceneHudSnapshot(null);
    setNotesOverlayOpen(false);
  }, [sessionId]);

  const refreshSession = useCallback(async () => {
    try {
      const detail = await getSessionAPI(sessionId);
      setSession(detail);
    } catch (err) {
      console.warn("[chatrpg] session refresh failed:", err);
    }
  }, [sessionId]);

  const isMobile = useIsMobile();
  const drawerMode = isMobile;
  const accent = theme === "slate" ? "#7B8FD9" : "#C66E4E";

  const {
    messages,
    hasMoreOlder,
    loadingOlder,
    loadError,
    activeSceneKey,
    resolvingPendingId,
    pendingRoll,
    setActiveSceneKey,
    setPendingRoll,
    loadOlder,
    sendMessage,
    startPendingRoll,
    handlePendingRollResult,
    handleDiceRoll,
  } = useGameMessages({
    sessionId,
    setSession,
    diceRollLabel: t("diceRoll"),
  });

  const {
    dialogueEntry,
    voiceOptions,
    handleChangePcVoice,
    handleChangeNpcVoice,
    handlePlayCharacterVoiceIntro,
    handlePlayNpcVoiceIntro,
    handleRematchNpcVoices,
    handleEnrichBondNpcs,
  } = useVoiceCatalogue({ sessionId, setSession, refreshSession });

  const character = readCharacter(session);
  const speakerProfiles = useMemo(
    () => buildSpeakerProfiles(session, character.name),
    [session, character.name],
  );
  const moduleState =
    (session?.module_state as ModuleState | undefined) ?? MODULE_DEFAULT;
  const busyPendingMessageId =
    resolvingPendingId ||
    (pendingRoll?.kind === "pending" ? pendingRoll.gmMessageId : null);

  const rawCard =
    session && session.character && typeof session.character === "object"
      ? (session.character as Record<string, unknown>)
      : null;

  // Target language for character translation follows the GLOBAL UI locale
  // (the top-right toggle in TopBar). Adding a new locale to
  // `i18n/messages.LOCALE_META` automatically teaches this button about it
  // — there's no per-panel language picker.
  const handleTranslateCharacter = useCallback(
    async () => {
      if (translatingCharacter) return;
      setTranslatingCharacter(true);
      try {
        // Translate the PC card and the NPC roster in parallel — both
        // are session-bound JSON, both should follow the global locale,
        // and there's no reason to make the player click twice. One
        // failure shouldn't sink the other; we surface the merged latest
        // detail (the second response wins, but each endpoint already
        // commits independently).
        const [pcDetail, npcDetail] = await Promise.allSettled([
          translateCharacterAPI(sessionId, globalLocale),
          translateNpcsAPI(sessionId, globalLocale),
        ]);
        if (npcDetail.status === "fulfilled") {
          setSession(npcDetail.value);
        } else if (pcDetail.status === "fulfilled") {
          setSession(pcDetail.value);
        }
        if (pcDetail.status === "rejected") {
          console.warn("[chatrpg] translate character failed:", pcDetail.reason);
        }
        if (npcDetail.status === "rejected") {
          console.warn("[chatrpg] translate NPCs failed:", npcDetail.reason);
        }
      } finally {
        setTranslatingCharacter(false);
      }
    },
    [sessionId, translatingCharacter, globalLocale],
  );

  const playerNotes = derivePlayerNotes(session);
  const sidebarNpcs = deriveSidebarNpcs(session);
  const pcVoice = derivePcVoice(session);
  const characterSchema = deriveCharacterSchema(parsed);
  const displayedMessages = useMemo(
    () =>
      filterDisplayedMessages(messages, activeSceneKey, {
        guide: t("sceneTabsCharacterCreation"),
        unnamed: t("sceneTabsUnnamed"),
        returnSeparator: (vars) => t("sceneTabsReturnSeparator", vars),
      }),
    [messages, activeSceneKey, t],
  );

  return (
    <>
      <GameSidebar
        parsed={parsed}
        character={character}
        rawCard={rawCard}
        characterSchema={characterSchema}
        module={moduleState}
        memories={MEMORIES_DEFAULT}
        notes={playerNotes}
        npcs={sidebarNpcs}
        accent={accent}
        collapsed={!sidebarOpen}
        drawerMode={drawerMode}
        onClose={onCloseSidebar}
        onEditRules={onOpenRulesetView}
        onTranslateCharacter={rawCard ? handleTranslateCharacter : undefined}
        translatingCharacter={translatingCharacter}
        voiceOptions={voiceOptions}
        voiceProvider={dialogueEntry?.provider}
        voiceModel={dialogueEntry?.model}
        pcVoice={pcVoice}
        onChangePcVoice={handleChangePcVoice}
        onChangeNpcVoice={handleChangeNpcVoice}
        onPlayPcVoiceIntro={handlePlayCharacterVoiceIntro}
        onPlayNpcVoiceIntro={handlePlayNpcVoiceIntro}
        onRematchNpcVoices={handleRematchNpcVoices}
        onEnrichBondNpcs={
          sidebarNpcs.some((n) => n.fromBond && n.needsBondEnrichment)
            ? handleEnrichBondNpcs
            : undefined
        }
        onOpenNotes={() => setNotesOverlayOpen(true)}
      />
      <div className="flex-1 flex flex-col min-w-0 relative">
        <SceneTabs
          messages={messages}
          activeKey={activeSceneKey}
          onSelect={(key) => {
            // Tapping the latest tab counts as "follow live" — store null so
            // future scene transitions automatically pull the view forward.
            const buckets = buildBuckets(messages, {
              guide: t("sceneTabsCharacterCreation"),
              unnamed: t("sceneTabsUnnamed"),
            });
            const latest = buckets[buckets.length - 1]?.key;
            setActiveSceneKey(key === latest ? null : key);
          }}
        />
        <ChatArea
          messages={
            loadError
              ? [
                  {
                    id: "load-err",
                    role: "system",
                    text: `Failed to load session: ${loadError}`,
                  } as ChatMessage,
                ]
              : displayedMessages
          }
          sessionId={sessionId}
          chatStyle="bubbles"
          characterName={character.name}
          characterInitial={character.name[0] ?? "?"}
          speakerProfiles={speakerProfiles}
          onSend={sendMessage}
          onOpenDice={() => setShowDice(true)}
          hasMoreOlder={hasMoreOlder}
          loadingOlder={loadingOlder}
          onLoadOlder={loadOlder}
          tabKey={activeSceneKey ?? "__live__"}
          onResolvePending={startPendingRoll}
          resolvingPendingId={busyPendingMessageId}
          sceneHudLive={activeSceneKey === null}
          onSceneHudSnapshotChange={setSceneHudSnapshot}
        />
        {sessionId && session && (
          <TrpgSceneHud
            sessionId={sessionId}
            module={(session.module_state as Record<string, unknown>) || {}}
            snapshot={sceneHudSnapshot}
            onChanged={refreshSession}
          />
        )}
      </div>
      {sessionId && (
        <NotesOverlay
          sessionId={sessionId}
          open={notesOverlayOpen}
          initialNotes={playerNotes}
          onClose={() => setNotesOverlayOpen(false)}
          onChanged={refreshSession}
        />
      )}
      {showDice && (
        <DiceModal
          onClose={() => setShowDice(false)}
          onPick={(diceType) => {
            setShowDice(false);
            setPendingRoll({ kind: "free", diceType, notation: `1${diceType}` });
          }}
        />
      )}
      <DiceBox3D
        visible={
          pendingRoll !== null &&
          !(pendingRoll.kind === "free" && pendingRoll.diceType === "d2")
        }
        notation={pendingRoll?.notation ?? "1d20"}
        onResult={(r) => {
          if (!pendingRoll) return;
          if (pendingRoll.kind === "pending") {
            void handlePendingRollResult(pendingRoll, r);
          } else {
            void handleDiceRoll(pendingRoll.diceType, r.total);
          }
        }}
        onClose={() => setPendingRoll(null)}
      />
      <CoinFlip
        visible={pendingRoll?.kind === "free" && pendingRoll.diceType === "d2"}
        onResult={(v) => {
          if (pendingRoll?.kind === "free") {
            void handleDiceRoll(pendingRoll.diceType, v);
          }
        }}
        onClose={() => setPendingRoll(null)}
      />
    </>
  );
}
