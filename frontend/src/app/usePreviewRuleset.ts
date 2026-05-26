import {
  useEffect,
  useState,
  type Dispatch,
  type SetStateAction,
} from "react";
import { dtoToParsed, getRulesetAPI } from "../lib/ruleset/api";
import type { ParsedRuleset } from "../lib/ruleset/types";
import type { Screen } from "./screen";

export function usePreviewRuleset(
  screen: Screen
): [ParsedRuleset | null, Dispatch<SetStateAction<ParsedRuleset | null>>] {
  const [previewRuleset, setPreviewRuleset] = useState<ParsedRuleset | null>(
    null
  );

  // Fetch the preview ruleset whenever we land on a preview screen.
  useEffect(() => {
    if (screen.kind !== "preview") {
      setPreviewRuleset(null);
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        const dto = await getRulesetAPI(screen.rulesetId);
        if (!cancelled) setPreviewRuleset(dtoToParsed(dto));
      } catch {
        if (!cancelled) setPreviewRuleset(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [screen]);

  // Poll the preview ruleset every 5s while dice_ir is the "compiling"
  // stub. Stops when status flips to compiled or failed, or when the
  // screen changes.
  useEffect(() => {
    if (screen.kind !== "preview") return;
    if (previewRuleset?.dice_ir?.status !== "compiling") return;
    const rulesetId = screen.rulesetId;
    let cancelled = false;
    const handle = window.setInterval(async () => {
      if (cancelled) return;
      try {
        const dto = await getRulesetAPI(rulesetId);
        if (cancelled) return;
        const parsed = dtoToParsed(dto);
        setPreviewRuleset(parsed);
        if (parsed.dice_ir?.status !== "compiling") {
          window.clearInterval(handle);
        }
      } catch (err) {
        console.warn("[chatrpg] dice_ir preview poll failed:", err);
      }
    }, 5000);
    return () => {
      cancelled = true;
      window.clearInterval(handle);
    };
  }, [screen, previewRuleset?.dice_ir?.status]);

  return [previewRuleset, setPreviewRuleset];
}
