from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    api_key: str
    database_url: str
    jwt_secret_key: str
    jwt_refresh_key: str
    model_config = SettingsConfigDict(env_file=".env")
