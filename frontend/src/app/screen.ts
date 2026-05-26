import type { SetupStateDTO } from "../api/sessions";
import type { ParsedRuleset } from "../lib/ruleset/types";

export type Screen =
  | { kind: "setup"; sessionId: string; initial: SetupStateDTO }
  | { kind: "game"; sessionId: string; ruleset: ParsedRuleset }
  | { kind: "preview"; rulesetId: string; from: "setup" | "game" }
  | { kind: "editor"; draftId: string };

export const EMPTY_SETUP_STATE: SetupStateDTO = {
  step: 0,
  ruleset_id: null,
  module_id: null,
  module_title: null,
  completed: false,
};
