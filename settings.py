from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    DB_USER: str = "user"
    DB_PASSWORD: str = "password"
    DB_NAME: str = "booking_db"
    DB_HOST: str = "127.0.0.1"
    DB_PORT: int = 5435

    @property
    def database_url(self) -> str:
        return f"postgresql+asyncpg://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"

    redis_url: str = "redis://localhost:6379/0"


settings = Settings()