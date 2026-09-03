import os
from dataclasses import dataclass, field
from typing import Optional
from dotenv import load_dotenv

load_dotenv()


def _get_env(key: str, default: Optional[str] = None) -> Optional[str]:
    return os.environ.get(key, default)


@dataclass
class AppConfig:
    SECRET_KEY: str = field(default_factory=lambda: os.environ.get("SECRET_KEY", "dev-secret-change-in-prod"))
    DEBUG: bool = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    HOST: str = os.environ.get("HOST", "0.0.0.0")
    PORT: int = int(os.environ.get("PORT", "5001"))
    CORS_ORIGINS: list = field(default_factory=lambda: os.environ.get("CORS_ORIGINS", "*").split(","))


@dataclass
class AudioConfig:
    SAMPLERATE: int = 16000
    CHANNELS: int = 1
    DTYPE: str = "float32"
    BLOCKSIZE: int = 5120
    MIN_VOLUME_THRESHOLD: float = 0.01
    PARTIAL_INTERVAL_SEC: float = 3.0


@dataclass
class WhisperConfig:
    MODEL_SIZE: str = os.environ.get("WHISPER_MODEL", "base")
    COMPUTE_TYPE: str = os.environ.get("WHISPER_COMPUTE", "int8")
    BEAM_SIZE: int = 5
    LANGUAGE: Optional[str] = None


@dataclass
class GeminiConfig:
    API_KEY: Optional[str] = field(default_factory=lambda: os.environ.get("GEMINI_API_KEY"))
    MODEL: str = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
    VIDEO_MODEL: str = os.environ.get("GEMINI_VIDEO_MODEL", "gemini-2.0-flash")
    TEXT_MODEL: str = os.environ.get("GEMINI_TEXT_MODEL", "gemini-2.0-flash")
    TIMEOUT_SEC: int = int(os.environ.get("GEMINI_TIMEOUT", "60"))
    MAX_RETRIES: int = 3


@dataclass
class StorageConfig:
    DB_PATH: str = os.environ.get("DB_PATH", "data/meetings.db")
    UPLOAD_DIR: str = os.environ.get("UPLOAD_DIR", "uploads_tmp")
    MAX_VIDEO_SIZE_MB: int = int(os.environ.get("MAX_VIDEO_SIZE_MB", "100"))
    ALLOWED_VIDEO_TYPES: list = field(default_factory=lambda: ["video/mp4", "video/webm", "video/quicktime", "video/x-msvideo"])


@dataclass
class Config:
    app: AppConfig = field(default_factory=AppConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    whisper: WhisperConfig = field(default_factory=WhisperConfig)
    gemini: GeminiConfig = field(default_factory=GeminiConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)


def get_config() -> Config:
    return Config()


config = get_config()
