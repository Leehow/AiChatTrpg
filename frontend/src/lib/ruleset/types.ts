// V6 ruleset JSON shape parsed from rule_parser_v6 output.
// Only the fields we surface in the UI are typed; unknown fields pass through
// untouched in the raw artifact so future tools can still read them.

export interface V6FileRef {
  file_id: string;
  filename: string;
  enabled?: boolean;
  size?: number;
  missing?: boolean;
}

export interface V6Companion {
  filename: string;
  content: string;
  world_mode?: string;
}

export interface V6RulePackage {
  package_id: string;
  filename?: string;
  content: string;
  raw?: string;
  excerpt_stats?: Record<string, unknown>;
  error?: string;
}

export interface V6ParameterFamilyEntry {
  // Each family has its own entry shape — keep loose here.
  [key: string]: unknown;
}

export interface V6ParameterFamily {
  family_id: string;
  filename?: string;
  json?: {
    book_id?: string;
    family_id?: string;
    title?: string;
    should_remain_markdown?: boolean;
    schema_used?: Record<string, unknown>;
    entries?: V6ParameterFamilyEntry[];
  };
  content?: string;
  raw?: string;
  should_remain_markdown?: boolean;
  error?: string;
}

export interface V6CharacterSheet {
  template_filename?: string;
  template_content?: string;
  template_json?: Record<string, unknown>;
  guide_filename?: string;
  guide_content?: string;
  error?: string;
}

export interface V6DiscoveryManifest {
  book_id?: string;
  book_title?: string;
  world_mode?: string;
  detailed_rule_packages?: Array<{ package_id: string; filename?: string }>;
  parameter_families?: Array<{ family_id: string; filename?: string }>;
  character_sheet_package?: {
    present: boolean;
    summary?: string;
    template_file?: string;
    guide_file?: string;
  };
  aliases?: unknown[];
}

export interface V6Stats {
  plain_chars?: number;
  total_lines?: number;
  packages_count?: number;
  families_count?: number;
  character_sheet_present?: boolean;
}

// The raw artifact: everything we receive from the upload, kept verbatim.
export interface V6RawArtifact {
  version: number;
  book_id: string;
  book_title: string;
  world_mode: string;
  output_language?: string;
  model?: string;
  parsed_at?: string;
  files?: V6FileRef[];
  core_rules: string;
  companion?: V6Companion;
  discovery_manifest?: V6DiscoveryManifest;
  rule_packages?: V6RulePackage[];
  parameter_families?: V6ParameterFamily[];
  character_sheet?: V6CharacterSheet;
  final_manifest?: V6DiscoveryManifest;
  stats?: V6Stats;
  // Dice IR may live in three locations depending on the producer:
  //   - top-level `dice_ir` (preferred — chatrpg fixtures + chatlab serialize_v6)
  //   - `parse_artifacts.v6.dice_ir` (post-stage-8 chatlab DB shape)
  //   - `parse_artifacts.dice_ir_compiler` (legacy chatlab top-level key)
  dice_ir?: DiceIRArtifact;
  parse_artifacts?: {
    v6?: { dice_ir?: DiceIRArtifact; [key: string]: unknown };
    dice_ir_compiler?: DiceIRArtifact;
    [key: string]: unknown;
  };
  [key: string]: unknown;
}

// Compiled dice IR artifact, or an in-flight / failed stub written by the
// auto-compile background task. The `status` field disambiguates:
//   - undefined  → fully compiled (legacy + chatlab/chatrpg compiled output)
//   - "compiling" → background task running; package is absent
//   - "failed"    → background task hit an error; check `error` field
export interface DiceIRArtifact {
  schema_version?: string;
  status?: "compiling" | "failed";
  started_at?: string;
  failed_at?: string;
  error?: string;
  saved_at?: string;
  model?: string;
  output_language?: string;
  auto_compiled?: boolean;
  house_rules?: unknown;
  applied_check_spec?: {
    procedure_id?: string;
    engine?: string;
    source?: string;
    applied_at?: string;
  };
  package?: {
    schema_version?: string;
    compiled?: {
      schema_version?: string;
      check_specs?: Array<{
        procedure_id: string;
        name?: string;
        primary_family?: string;
        check_spec?: Record<string, unknown>;
        validation?: { ok: boolean; sample_count?: number; errors?: string[] };
      }>;
      unsupported_procedures?: unknown[];
      default_procedure_id?: string;
      overall_ok?: boolean;
    };
  };
}

// The 4-section parsed view consumed by the UI.
export interface ParsedRuleset {
  meta: {
    book_id: string;
    book_title: string;
    world_mode: string;
    output_language?: string;
    parsed_at?: string;
    model?: string;
    stats?: V6Stats;
  };
  core: {
    rules_markdown: string;
    companion?: { filename: string; content: string };
  };
  scenarios: V6RulePackage[];
  parameters: V6ParameterFamily[];
  character_sheet?: V6CharacterSheet;
  dice_ir: DiceIRArtifact | null;
  check_spec: Record<string, unknown> | null;
  /** Backend-compiled character UI schema artifact. Same compiling/failed
   *  stub pattern as `dice_ir`. The `package` field carries the widget tree.
   */
  character_ui: Record<string, unknown> | null;
  raw: V6RawArtifact;
}

export class V6ParseError extends Error {
  constructor(message: string, public readonly field?: string) {
    super(message);
    this.name = "V6ParseError";
  }
}
