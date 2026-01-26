from dataclasses import dataclass
import os

@dataclass(frozen=True)
class Settings:
    env: str
    log_level: str

def get_settings() -> Settings:
    return Settings(
        env=os.getenv("ENV", "dev"),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
    )
