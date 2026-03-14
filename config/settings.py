"""
Configuration settings for the Scraply AI Agent system.
All settings are loaded from environment variables.
"""

import os
from dataclasses import dataclass
from typing import Optional
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


@dataclass
class DatabaseConfig:
    """PostgreSQL database configuration (read-only)."""
    host: str
    port: int
    database: str
    user: str
    password: str

    @classmethod
    def from_env(cls) -> "DatabaseConfig":
        return cls(
            host=os.getenv("DB_HOST", "localhost"),
            port=int(os.getenv("DB_PORT", "5432")),
            database=os.getenv("DB_NAME", "scraply"),
            user=os.getenv("DB_USER", "scraply_readonly"),
            password=os.getenv("DB_PASSWORD", ""),
        )

    @property
    def connection_string(self) -> str:
        return f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}"


@dataclass
class RedisConfig:
    """Redis configuration for queue operations."""
    host: str
    port: int
    password: Optional[str]
    ssl: bool

    @classmethod
    def from_env(cls) -> "RedisConfig":
        return cls(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=int(os.getenv("REDIS_PORT", "6379")),
            password=os.getenv("REDIS_PASSWORD") or None,
            ssl=os.getenv("REDIS_SSL", "false").lower() == "true",
        )


@dataclass
class APIConfig:
    """REST API configuration for backend communication."""
    base_url: str
    access_key: str
    secret_key: str
    timeout: int  # seconds

    @classmethod
    def from_env(cls) -> "APIConfig":
        return cls(
            base_url=os.getenv("API_BASE_URL", "http://localhost:8080"),
            access_key=os.getenv("AGENT_ACCESS_KEY", ""),
            secret_key=os.getenv("AGENT_SECRET_KEY", ""),
            timeout=int(os.getenv("API_TIMEOUT", "30")),
        )


@dataclass
class LLMConfig:
    """LLM configuration for Groq."""
    api_key: str
    model: str
    temperature: float
    max_tokens: int

    @classmethod
    def from_env(cls) -> "LLMConfig":
        return cls(
            api_key=os.getenv("GROQ_API_KEY", ""),
            model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
            temperature=float(os.getenv("LLM_TEMPERATURE", "0.1")),
            max_tokens=int(os.getenv("LLM_MAX_TOKENS", "2048")),
        )


@dataclass
class VisionConfig:
    """Vision model configuration for image analysis with provider fallback."""
    enabled: bool
    api_key: str
    model: str
    groq_model: str
    max_image_size_mb: float

    @classmethod
    def from_env(cls) -> "VisionConfig":
        return cls(
            enabled=os.getenv("VISION_ENABLED", "true").lower() == "true",
            api_key=os.getenv("GOOGLE_API_KEY", ""),
            model=os.getenv("VISION_MODEL", "gemini-2.0-flash"),
            groq_model=os.getenv("GROQ_VISION_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct"),
            max_image_size_mb=float(os.getenv("VISION_MAX_IMAGE_SIZE_MB", "4.0")),
        )


@dataclass
class AgentConfig:
    """Agent-specific configuration."""
    agent_id: str
    poll_interval: float  # seconds
    retry_attempts: int
    retry_delay: float  # seconds
    duplicate_distance_km: float  # km for nearby detection
    duplicate_time_hours: int  # hours for recent time window
    max_concurrent_tasks: int

    @classmethod
    def from_env(cls) -> "AgentConfig":
        return cls(
            agent_id=os.getenv("AGENT_ID", ""),
            poll_interval=float(os.getenv("POLL_INTERVAL", "5.0")),
            retry_attempts=int(os.getenv("RETRY_ATTEMPTS", "3")),
            retry_delay=float(os.getenv("RETRY_DELAY", "2.0")),
            duplicate_distance_km=float(os.getenv("DUPLICATE_DISTANCE_KM", "0.5")),
            duplicate_time_hours=int(os.getenv("DUPLICATE_TIME_HOURS", "24")),
            max_concurrent_tasks=int(os.getenv("MAX_CONCURRENT_TASKS", "5")),
        )


class Settings:
    """Central settings container."""

    def __init__(self):
        self.database = DatabaseConfig.from_env()
        self.redis = RedisConfig.from_env()
        self.api = APIConfig.from_env()
        self.llm = LLMConfig.from_env()
        self.vision = VisionConfig.from_env()
        self.agent = AgentConfig.from_env()

    def validate(self) -> list[str]:
        """Validate all required settings are present."""
        errors = []

        if not self.llm.api_key:
            errors.append("GROQ_API_KEY is required")
        if not self.api.access_key:
            errors.append("AGENT_ACCESS_KEY is required")
        if not self.api.secret_key:
            errors.append("AGENT_SECRET_KEY is required")
        if not self.agent.agent_id:
            errors.append("AGENT_ID is required")
        if not self.database.password:
            errors.append("DB_PASSWORD is required")
        if self.vision.enabled and not self.vision.api_key and not self.llm.api_key:
            errors.append("Either GOOGLE_API_KEY or GROQ_API_KEY is required when VISION_ENABLED=true")

        return errors


# Global settings instance
settings = Settings()
