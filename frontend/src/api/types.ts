// Hand-written type mirrors. Reset to scaffolding — only health + admin types
// exist while the TRPG runtime is being redesigned from scratch.

export interface Health {
  ok: boolean;
  single_user_id: string;
  configured_providers: string[];
  all_providers: string[];
  default_provider: string;
  default_model: string;
}

export interface AdminProvider {
  provider: string;
  api_key: string;
  api_key_set: boolean;
  base_url: string;
  models: string[];
  default_model: string;
  env_has_key: boolean;
}

export interface AdminProviderUpdate {
  api_key?: string | null;
  base_url?: string | null;
  models: string[];
}

export interface LLMProviderInfo {
  provider: string;
  label: string;
  kind: "openai_compat" | "native" | "mock";
  default_base_url: string;
  default_model: string;
  saved_api_key: boolean;
  saved_base_url: string;
  saved_model: string;
}

export interface LLMTestRequest {
  provider: string;
  model: string;
  api_key: string;
  base_url: string;
  prompt: string;
  temperature?: number | null;
}

export interface LLMTestResponse {
  text: string;
  provider: string;
  model: string;
  total_ms: number;
  first_token_ms: number | null;
  chars: number;
  chars_per_second: number;
  finish_reason: string | null;
  error: string | null;
}

export interface ListModelsRequest {
  provider: string;
  api_key: string;
  base_url: string;
}

export interface ListModelsResponse {
  provider: string;
  models: string[];
  error: string | null;
}

export interface PoolEntry {
  provider: string;
  model: string;
}

export type PoolRole =
  | "default"
  | "fast"
  | "dialogue"
  | "avatar"
  | "illustration"
  | "narration";

export interface PoolView {
  entries: PoolEntry[];
  default_index: number;
  default: PoolEntry | null;
  fast_index: number;
  fast: PoolEntry | null;
  dialogue_index: number;
  dialogue: PoolEntry | null;
  avatar_index: number;
  avatar: PoolEntry | null;
  illustration_index: number;
  illustration: PoolEntry | null;
  narration_index: number;
  narration: PoolEntry | null;
}

export interface PoolAddRequest {
  provider: string;
  model: string;
  api_key: string;
  base_url: string;
}

export interface MediaVoice {
  id: string;
  name: string;
  gender: string;
  description: string;
  languages: string[];
  source: string;
  raw: Record<string, unknown>;
}

export interface MediaVoiceListResponse {
  provider: string;
  model: string;
  voices: MediaVoice[];
  source: string;
  live: boolean;
  error: string;
}

export interface MediaTtsRequest {
  provider: string;
  model: string;
  text: string;
  voice?: string;
  audio_format?: string;
  instructions?: string;
  language?: string;
}

export interface MediaTtsResponse {
  provider: string;
  model: string;
  audio_data_uri: string;
  audio_url: string;
  mime_type: string;
  format: string;
  usage: Record<string, unknown>;
}

export interface NarrationVoiceSetting {
  provider: string;
  model: string;
  voice: string;
}

export interface MediaSettings {
  narration_voice: NarrationVoiceSetting | null;
}

// ---------------------------------------------------------------------------
// OCR — MinerU local + cloud
// ---------------------------------------------------------------------------

export interface OCRProviderInfo {
  provider: string;
  label: string;
  api_key_set: boolean;
  env_has_key: boolean;
  active?: boolean;
  config: Record<string, unknown>;
}

export interface OCRProviderUpdate {
  api_key?: string;
  base_url?: string;
  cli?: string;
  backend?: string;
  lang?: string;
  model_version?: string;
  no_formula?: boolean;
  no_table?: boolean;
  enabled?: boolean;
}

export interface OCRHealthResponse {
  provider: string;
  ok: boolean;
  detail: Record<string, unknown>;
}

export interface TOCEntry {
  title: string;
  level: number;
  anchor: string;
  /** 1-based inclusive markdown line range; 0 = unknown. */
  line_start: number;
  line_end: number;
}

export interface ModuleSection {
  title?: string;
  type?: string;
  summary?: string;
  start_line?: number;
  end_line?: number;
  line_start?: number;
  line_end?: number;
}

export interface ModulePlayableUnit {
  title?: string;
  kind?: string;
  summary?: string;
  start_line?: number;
  end_line?: number;
  line_start?: number;
  line_end?: number;
  section_indexes?: number[];
}

export interface ModuleGlobalRef {
  title?: string;
  kind?: string;
  summary?: string;
  start_line?: number;
  end_line?: number;
  line_start?: number;
  line_end?: number;
}

export interface ModuleSemanticStructure {
  type?: string;
  title?: string;
  connection?: string;
  sections?: ModuleSection[];
  playable_units?: ModulePlayableUnit[];
  global_refs?: ModuleGlobalRef[];
  [key: string]: unknown;
}

export interface ModuleAppendixEntry {
  name?: string;
  category?: string;
  type?: string;
  brief?: string;
  stats_summary?: string;
  line?: number;
}

export interface ModuleAppendixIndex {
  categories?: Array<{ name?: string; count?: number }>;
  entries?: ModuleAppendixEntry[];
  [key: string]: unknown;
}

export interface ModuleSemanticStep {
  stage?: string;
  status?: string;
  summary?: string;
  output?: Record<string, unknown>;
}

export type ModuleSourceFormat =
  | "pdf"
  | "docx"
  | "pptx"
  | "xlsx"
  | "image"
  | "markdown"
  | "text";

export interface ModuleParseResponse {
  id: string;
  owner_id: string;
  is_shared: boolean;
  filename: string;
  source_format: ModuleSourceFormat;
  backend: string;
  markdown: string;
  page_count: number;
  images_dropped: number;
  duration_seconds: number;
  toc: TOCEntry[];
  toc_source: "llm" | "heuristic";
  semantic_status: "pending" | "running" | "done" | "error";
  semantic_error: string;
  semantic_structure: ModuleSemanticStructure;
  semantic_steps: ModuleSemanticStep[];
  briefing_md: string;
  appendix_index: ModuleAppendixIndex;
  created_at?: string;
}

export interface ModuleSummary {
  id: string;
  owner_id: string;
  is_shared: boolean;
  filename: string;
  source_format: string;
  backend: string;
  page_count: number;
  chars: number;
  toc_entries: number;
  toc_source: string;
  created_at: string;
  updated_at: string;
}

export interface OCRTestResponse {
  provider: string;
  ok: boolean;
  duration_seconds: number;
  page_count: number;
  markdown_preview: string;
  markdown_length: number;
  image_count: number;
  error: string | null;
}
