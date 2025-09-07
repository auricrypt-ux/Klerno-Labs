import os
from pydantic import BaseSettings

class Settings(BaseSettings):
    admin_email: str = os.getenv("ADMIN_EMAIL", "klerno@outlook.com")
    demo_mode: bool = os.getenv("DEMO_MODE", "false").lower() == "true"

def get_settings() -> Settings:
    return Settings()
