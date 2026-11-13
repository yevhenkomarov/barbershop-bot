from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bot_token: str = ""
    database_url: str = "postgresql+asyncpg://barber:barber@localhost:5432/barber"
    admin_login: str = "admin"
    admin_password: str = ""
    admin_secret_key: str = "change-me"
    admin_https_only: bool = False
    admin_telegram: str = ""

    shop_name: str = "Барбершоп"
    shop_address: str = "Ізюм, Поворотка"
    shop_hours: str = "Щодня 09:00–19:00"
    shop_phone: str = "+380 00 000 00 00"
    shop_instagram: str = ""
    shop_lat: float = 49.1245
    shop_lon: float = 37.1511

    timezone: str = "Europe/Kyiv"
    booking_days_ahead: int = 14
    slot_step_min: int = 30
    min_lead_min: int = 30
    cancel_deadline_hours: int = 3
    reminder_poll_seconds: int = 30

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @property
    def admin_usernames(self) -> set[str]:
        return {
            x.strip().lstrip("@").lower()
            for x in self.admin_telegram.split(",")
            if x.strip() and not x.strip().isdigit()
        }

    @property
    def admin_ids(self) -> set[int]:
        return {int(x.strip()) for x in self.admin_telegram.split(",") if x.strip().isdigit()}

    @property
    def map_url(self) -> str:
        return f"https://www.google.com/maps/search/?api=1&query={self.shop_lat},{self.shop_lon}"

    @property
    def route_url(self) -> str:
        return f"https://www.google.com/maps/dir/?api=1&destination={self.shop_lat},{self.shop_lon}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
