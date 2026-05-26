from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent


class ProviderConfig(BaseSettings):
    api_key: str = ""
    base_url: str = ""
    default_model: str = ""

    def is_configured(self) -> bool:
        return bool(self.api_key)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    host: str = "127.0.0.1"
    port: int = 8013
    log_level: str = "INFO"
    debug: bool = False

    database_url: str = "postgresql+asyncpg://chatrpg:chatrpg@127.0.0.1:54318/chatrpg"

    single_user_id: str = "local"
    single_user_name: str = "Player"

    # Auth: credentials live in a JSON file at repo root (or override path).
    # Each entry is {id, username, password, display_name}. Plain passwords
    # are intentional for the open-source single-user default — commercial
    # forks should swap in bcrypt + a DB-backed user store.
    auth_file: str = str(REPO_ROOT / "auth.json")
    # Token signing key. Override in .env for production.
    jwt_secret: str = "chatrpg-dev-secret-change-me"
    jwt_algorithm: str = "HS256"
    jwt_ttl_hours: int = 24 * 30
    password_hash_iterations: int = 210_000

    # Hosted test-platform registration. Keep disabled by default so the
    # open-source local install remains operator-created unless explicitly
    # configured. When enabled, invite codes are required by default.
    registration_enabled: bool = False
    registration_invite_required: bool = True
    registration_invite_codes: str = ""
    registration_invite_max_uses: int = 1

    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_default_model: str = "gpt-4o"

    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    deepseek_default_model: str = "deepseek-chat"

    kimi_api_key: str = ""
    kimi_base_url: str = "https://api.moonshot.cn/v1"
    kimi_default_model: str = "moonshot-v1-32k"

    glm_api_key: str = ""
    glm_base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    glm_default_model: str = "glm-4-plus"

    doubao_api_key: str = ""
    doubao_base_url: str = "https://ark.cn-beijing.volces.com/api/v3"
    doubao_default_model: str = ""

    qwen_api_key: str = ""
    qwen_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    qwen_default_model: str = "qwen-plus"

    grok_api_key: str = ""
    grok_base_url: str = "https://api.x.ai/v1"
    grok_default_model: str = "grok-2"

    minimax_api_key: str = ""
    minimax_base_url: str = "https://api.minimax.chat/v1"
    minimax_default_model: str = "abab6.5s-chat"

    # Generic OpenAI-compatible — user supplies any base_url and model.
    openai_compat_api_key: str = ""
    openai_compat_base_url: str = ""
    openai_compat_default_model: str = ""

    gemini_api_key: str = ""
    gemini_default_model: str = "gemini-2.5-pro"

    claude_api_key: str = ""
    claude_default_model: str = "claude-sonnet-4-6"

    trpg_default_provider: str = "openai"
    trpg_default_model: str = "gpt-4o"
    trpg_memory_compress_threshold: int = 20

    # Codex relay — local OpenAI-compatible endpoint backed by ChatGPT Pro.
    # Used by the dice-IR compiler unless a different provider is selected.
    codex_relay_base_url: str = "http://127.0.0.1:18888/v1"
    codex_relay_api_key: str = "codex-relay-local"  # relay ignores key
    codex_relay_default_model: str = "gpt-5.5"

    # Default model for the dice-IR compiler. The compiler accepts any
    # OpenAI-compatible chat-completions model; codex-relay's gpt-5.5 is
    # the V1 default because it's the strongest reasoning model we have
    # available locally without hitting external APIs.
    dice_ir_compiler_model: str = "gpt-5.5"

    # Timeouts (seconds) for the long-running dice IR compiler calls. The
    # extract pass routinely takes >2 min on full rulebooks.
    trpg_llm_connect_timeout_seconds: float = 30.0
    trpg_llm_read_timeout_seconds: float = 600.0
    trpg_llm_write_timeout_seconds: float = 60.0
    trpg_llm_pool_timeout_seconds: float = 30.0

    frontend_url: str = "http://localhost:3013"

    # ------------------------------------------------------------------
    # OCR / document extraction
    # ------------------------------------------------------------------
    # Two backends, both produce the same MinerU output (markdown +
    # middle.json + content_list.json). UI overrides live in
    # backend/data/ocr_config.json on top of these env defaults.
    #
    # Local: invokes the `mineru` CLI. Per-call subprocess — slow first
    # invocation (model load) but zero coupling to chatrpg's venv.
    mineru_local_enabled: bool = True
    mineru_local_cli: str = "mineru"               # path or name on PATH
    mineru_local_backend: str = "auto"             # auto / vlm-mlx / vlm-transformers / pipeline
    mineru_local_lang: str = ""                    # blank = auto-detect
    mineru_local_no_formula: bool = False
    mineru_local_no_table: bool = False
    mineru_local_timeout_seconds: int = 7200       # 2 h cap per file

    # Cloud: mineru.net hosted API. Async — submit task, poll, download.
    mineru_cloud_api_key: str = ""
    mineru_cloud_base_url: str = "https://mineru.net/api/v4"
    mineru_cloud_model_version: str = "vlm"        # vlm / pipeline / MinerU-HTML
    mineru_cloud_poll_interval_seconds: float = 3.0
    mineru_cloud_poll_timeout_seconds: int = 1800

    @field_validator("debug", mode="before")
    @classmethod
    def normalize_debug_flag(cls, value):
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"release", "prod", "production"}:
                return False
            if lowered in {"dev", "development"}:
                return True
        return value

    @model_validator(mode="after")
    def require_postgres_database_url(self) -> "Settings":
        if not self.database_url.startswith("postgresql+asyncpg://"):
            raise ValueError("DATABASE_URL must use postgresql+asyncpg://")
        return self

    def configured_providers(self) -> list[str]:
        result: list[str] = []
        for name in (
            "openai",
            "deepseek",
            "kimi",
            "glm",
            "doubao",
            "qwen",
            "grok",
            "minimax",
            "openai_compat",
            "gemini",
            "claude",
        ):
            if getattr(self, f"{name}_api_key"):
                result.append(name)
        return result

    def provider_config(self, name: str) -> dict:
        return {
            "api_key": getattr(self, f"{name}_api_key", ""),
            "base_url": getattr(self, f"{name}_base_url", ""),
            "default_model": getattr(self, f"{name}_default_model", ""),
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
