import { useCallback, useEffect, useState } from "react";
import { api } from "../../../api/client";
import {
  enrichBondNpcsAPI,
  rematchNpcVoicesAPI,
  setCharacterVoiceAPI,
  setNpcVoiceAPI,
  synthesizeCharacterVoiceIntroAPI,
  synthesizeNpcVoiceIntroAPI,
  type BondNpcEnrichResponse,
  type SessionDetailDTO,
  type VoiceIntroResponse,
} from "../../../api/sessions";
import type { MediaVoice, PoolEntry } from "../../../api/types";

interface VoiceCatalogueArgs {
  sessionId: string;
  setSession: (detail: SessionDetailDTO) => void;
  refreshSession: () => Promise<void> | void;
}

interface VoiceCatalogue {
  dialogueEntry: PoolEntry | null;
  voiceOptions: MediaVoice[];
  handleChangePcVoice: (voice: string) => Promise<void>;
  handleChangeNpcVoice: (npcKey: string, voice: string) => Promise<void>;
  handlePlayCharacterVoiceIntro: (
    opts?: { force?: boolean },
  ) => Promise<VoiceIntroResponse>;
  handlePlayNpcVoiceIntro: (
    npcKey: string,
    opts?: { force?: boolean },
  ) => Promise<VoiceIntroResponse>;
  handleRematchNpcVoices: (
    opts?: { force?: boolean },
  ) => Promise<{ rematched: number; skipped_locked: number }>;
  handleEnrichBondNpcs: () => Promise<BondNpcEnrichResponse>;
}

// Dialogue TTS catalogue — fetched once per shell mount. Both the PC
// card and the NPC modal pick voices from this list, so we share it
// through props instead of having each panel call the API.
export function useVoiceCatalogue({
  sessionId,
  setSession,
  refreshSession,
}: VoiceCatalogueArgs): VoiceCatalogue {
  const [dialogueEntry, setDialogueEntry] = useState<PoolEntry | null>(null);
  const [voiceOptions, setVoiceOptions] = useState<MediaVoice[]>([]);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const pool = await api.getModelPool();
        if (cancelled) return;
        const entry = pool.dialogue;
        setDialogueEntry(entry);
        if (!entry) {
          setVoiceOptions([]);
          return;
        }
        const list = await api.listMediaVoices(entry, true);
        if (cancelled) return;
        setVoiceOptions(list.voices ?? []);
      } catch (err) {
        if (cancelled) return;
        console.warn("[chatrpg] voice catalogue load failed:", err);
        setVoiceOptions([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const handleChangePcVoice = useCallback(
    async (voice: string) => {
      const detail = await setCharacterVoiceAPI(sessionId, {
        voice,
        provider: dialogueEntry?.provider ?? "",
        model: dialogueEntry?.model ?? "",
      });
      setSession(detail);
    },
    [sessionId, dialogueEntry, setSession],
  );

  const handleChangeNpcVoice = useCallback(
    async (npcKey: string, voice: string) => {
      const detail = await setNpcVoiceAPI(sessionId, npcKey, {
        voice,
        provider: dialogueEntry?.provider ?? "",
        model: dialogueEntry?.model ?? "",
      });
      setSession(detail);
    },
    [sessionId, dialogueEntry, setSession],
  );

  const handlePlayCharacterVoiceIntro = useCallback(
    async (opts?: { force?: boolean }): Promise<VoiceIntroResponse> => {
      const result = await synthesizeCharacterVoiceIntroAPI(sessionId, {
        force: opts?.force,
      });
      // Re-pull the session so the cached intro text/url that the
      // backend just stamped onto the character JSON shows up the next
      // time the panel reads from `session`.
      void refreshSession();
      return result;
    },
    [sessionId, refreshSession],
  );

  const handlePlayNpcVoiceIntro = useCallback(
    async (
      npcKey: string,
      opts?: { force?: boolean },
    ): Promise<VoiceIntroResponse> => {
      const result = await synthesizeNpcVoiceIntroAPI(sessionId, npcKey, {
        force: opts?.force,
      });
      void refreshSession();
      return result;
    },
    [sessionId, refreshSession],
  );

  const handleRematchNpcVoices = useCallback(
    async (opts?: { force?: boolean }) => {
      const result = await rematchNpcVoicesAPI(sessionId, {
        skip_locked: !opts?.force,
        force: opts?.force,
      });
      setSession(result.session);
      return { rematched: result.rematched, skipped_locked: result.skipped_locked };
    },
    [sessionId, setSession],
  );

  const handleEnrichBondNpcs = useCallback(
    async (): Promise<BondNpcEnrichResponse> => {
      const result = await enrichBondNpcsAPI(sessionId, { force: false });
      setSession(result.session);
      return result;
    },
    [sessionId, setSession],
  );

  return {
    dialogueEntry,
    voiceOptions,
    handleChangePcVoice,
    handleChangeNpcVoice,
    handlePlayCharacterVoiceIntro,
    handlePlayNpcVoiceIntro,
    handleRematchNpcVoices,
    handleEnrichBondNpcs,
  };
}
