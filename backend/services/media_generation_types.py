"""Shared dataclasses, exceptions, and small defaults for the media layer.

Kept dependency-free so other media_generation_* modules and the facade can
import these without risking circular references.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


DEFAULT_IMAGE_SIZE = "1024x1024"
DEFAULT_AVATAR_IMAGE_SIZE = "1024x1024"
DEFAULT_AUDIO_FORMAT = "mp3"


class MediaGenerationError(RuntimeError):
    """Base error raised by media adapters."""


class UnsupportedMediaCapability(MediaGenerationError):
    """Raised when a provider/model has no requested media capability."""


@dataclass(frozen=True)
class MediaModelRuntime:
    provider: str
    model: str
    api_key: str = ""
    base_url: str = ""


@dataclass(frozen=True)
class ProviderMediaCapability:
    provider: str
    image: bool
    tts: bool
    image_endpoint: str = ""
    tts_endpoint: str = ""
    image_models_hint: list[str] = field(default_factory=list)
    tts_models_hint: list[str] = field(default_factory=list)
    voices: list[str] = field(default_factory=list)
    docs: list[str] = field(default_factory=list)
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "image": self.image,
            "tts": self.tts,
            "image_endpoint": self.image_endpoint,
            "tts_endpoint": self.tts_endpoint,
            "image_models_hint": list(self.image_models_hint),
            "tts_models_hint": list(self.tts_models_hint),
            "voices": list(self.voices),
            "docs": list(self.docs),
            "notes": self.notes,
        }


@dataclass(frozen=True)
class GeneratedImage:
    data_uri: str = ""
    url: str = ""
    mime_type: str = "image/png"

    @property
    def reference(self) -> str:
        return self.data_uri or self.url


@dataclass(frozen=True)
class ImageGenerationResult:
    provider: str
    model: str
    images: list[GeneratedImage]
    raw_provider: str = ""

    @property
    def primary_reference(self) -> str:
        return self.images[0].reference if self.images else ""


@dataclass(frozen=True)
class SpeechSynthesisResult:
    provider: str
    model: str
    audio_data_uri: str = ""
    audio_url: str = ""
    mime_type: str = "audio/mpeg"
    format: str = DEFAULT_AUDIO_FORMAT
    usage: dict[str, Any] = field(default_factory=dict)

    @property
    def reference(self) -> str:
        return self.audio_data_uri or self.audio_url


@dataclass(frozen=True)
class VoiceInfo:
    id: str
    name: str = ""
    gender: str = ""
    description: str = ""
    languages: list[str] = field(default_factory=list)
    source: str = "catalog"
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "gender": self.gender,
            "description": self.description,
            "languages": list(self.languages),
            "source": self.source,
            "raw": dict(self.raw),
        }


@dataclass(frozen=True)
class VoiceListResult:
    provider: str
    model: str
    voices: list[VoiceInfo]
    source: str = "catalog"
    live: bool = False
    error: str = ""
