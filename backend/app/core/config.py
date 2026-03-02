from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    APP_NAME: str = "MediaSync115"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True
    
    NULLBR_APP_ID: str = "ZWGOwxIrh"
    NULLBR_API_KEY: str = "rIxTz7XHDEHBcP9lGpeVAgs0I7Evg6wc"
    NULLBR_BASE_URL: str = "https://api.nullbr.com/"

    TMDB_API_KEY: Optional[str] = None
    TMDB_BASE_URL: str = "https://api.themoviedb.org/3"
    TMDB_IMAGE_BASE_URL: str = "https://image.tmdb.org/t/p/w500"
    TMDB_LANGUAGE: str = "zh-CN"
    TMDB_REGION: str = "CN"
    
    PAN115_COOKIE: Optional[str] = None
    HDHIVE_COOKIE: Optional[str] = None
    HDHIVE_BASE_URL: str = "https://hdhive.com/"

    PANSOU_BASE_URL: str = "http://192.168.10.139:8088/"
    TG_API_ID: Optional[str] = None
    TG_API_HASH: Optional[str] = None
    TG_PHONE: Optional[str] = None
    TG_SESSION: Optional[str] = None
    TG_PROXY: Optional[str] = None
    TG_CHANNEL_USERNAMES: str = ""
    TG_SEARCH_DAYS: int = 30
    TG_MAX_MESSAGES_PER_CHANNEL: int = 200
    
    EMBY_URL: str = "http://192.168.2.139:8096/"
    EMBY_API_KEY: str = "355c5a7a4cae4966a3c0b40042bbde36"
    
    DATABASE_URL: str = "sqlite+aiosqlite:///./data/mediasync.db"
    
    CORS_ORIGINS: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
        extra="ignore",
    )


settings = Settings()
