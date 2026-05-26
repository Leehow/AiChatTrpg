/**
 * Primitive types matching backend `agents/trpg/character_ui/widgets.py`.
 * Keep in sync — the LLM emits these shapes, the backend validates type
 * names against the catalog, and the renderer dispatches on `type`.
 *
 * Path scoping: every `*_path` prop resolves against the current scope.
 * The `list` primitive iterates `source_path` and pushes each entry as
 * the new scope for its `item_template` subtree.
 */

export type BarColor = "red" | "blue" | "green" | "amber" | "purple" | "teal";
export type TextSize = "xs" | "sm" | "md" | "lg";
export type TextEmphasis = "normal" | "bold" | "muted" | "accent";
export type GridGap = "tight" | "normal" | "loose";
export type CardTone = "default" | "subtle";
export type ImageAspect = "square" | "portrait" | "landscape";
export type SortOrder = "asc" | "desc";

export interface SectionPrimitive {
  type: "section";
  title?: string;
  children: Primitive[];
}

export interface TextPrimitive {
  type: "text";
  /** Bind to a card path (preferred). */
  value_path?: string;
  /** Literal text — no path resolution. */
  text?: string;
  /** Small caption shown before/above the value. */
  label?: string;
  /** Path-resolved label. Convenient inside list templates. */
  label_path?: string;
  size?: TextSize;
  emphasis?: TextEmphasis;
  /** When true, render inline rather than as a block. */
  inline?: boolean;
}

export interface BarPrimitive {
  type: "bar";
  label: string;
  current_path: string;
  max_path: string;
  color?: BarColor;
}

export interface GridPrimitive {
  type: "grid";
  columns: number;
  gap?: GridGap;
  children: Primitive[];
}

export interface ListPrimitive {
  type: "list";
  source_path: string;
  item_template: Primitive;
  /** When source resolves to an array of objects, group rows by this
   *  RELATIVE field. Each group renders its label as a small heading. */
  group_by?: string;
  /** RELATIVE field to sort entries by. Use `__key__` for object sources. */
  sort_by?: string;
  sort_order?: SortOrder;
  /** Fallback shown when the source resolves to empty. Omit to hide. */
  empty_text?: string;
}

export interface CardPrimitive {
  type: "card";
  tone?: CardTone;
  children: Primitive[];
}

export interface ImagePrimitive {
  type: "image";
  src_path: string;
  alt_path?: string;
  aspect?: ImageAspect;
}

export interface TagsPrimitive {
  type: "tags";
  source_path: string;
}

// --------------------------------------------------------------------------
// Compound primitives — opinionated shortcuts for the common patterns. The
// LLM is told to prefer these over hand-composing the same shape from atoms,
// because hand-composed lists tend to dump every field as inline labels and
// produce visually noisy layouts.
// --------------------------------------------------------------------------

export interface AttributeGridPrimitive {
  type: "attributeGrid";
  key: string;
  title?: string;
  source_path: string;
  columns?: number;
  value_field?: string;
  modifier_field?: string;
}

export interface SkillTablePrimitive {
  type: "skillTable";
  key: string;
  title?: string;
  source_path: string;
  name_field?: string;
  value_field?: string;
  category_field?: string;
}

export interface WeaponTablePrimitive {
  type: "weaponTable";
  key: string;
  title?: string;
  source_path: string;
  name_field?: string;
  skill_field?: string;
  damage_field?: string;
}

export interface FeatureListPrimitive {
  type: "featureList";
  key: string;
  title?: string;
  source_path: string;
  name_field?: string;
  description_field?: string;
}

export type CompoundPrimitive =
  | AttributeGridPrimitive
  | SkillTablePrimitive
  | WeaponTablePrimitive
  | FeatureListPrimitive;

export type Primitive =
  | SectionPrimitive
  | TextPrimitive
  | BarPrimitive
  | GridPrimitive
  | ListPrimitive
  | CardPrimitive
  | ImagePrimitive
  | TagsPrimitive
  | CompoundPrimitive;

export interface CharacterUISchema {
  system: string;
  title_path?: string | null;
  subtitle_path?: string | null;
  tree: Primitive;
}

/** Wrapping artifact returned by the backend compiler. */
export interface CharacterUIArtifact {
  schema_version?: string;
  saved_at?: string;
  model?: string;
  package?: CharacterUISchema;
  auto_compiled?: boolean;
  status?: "compiling" | "failed";
  started_at?: string;
  failed_at?: string;
  error?: string;
}

/** Schema version this frontend understands. Older versions are rejected
 *  so the user prompts a recompile.
 *  v1: flat widgets[] list (chatlab-style)
 *  v2: primitive tree, atoms only
 *  v3: primitive tree + compound primitives (current) */
export const SCHEMA_VERSION = "ruleset_character_ui_compiler_artifact_v3";
