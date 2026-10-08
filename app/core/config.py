# SPDX-License-Identifier: AGPL-3.0-only
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CONDUCTOR_")
    database_url: str = "sqlite:///data/conductor.db"
    admin_token: SecretStr | None = None
    proxmox_url: str | None = None
    proxmox_token: SecretStr | None = None
    proxmox_ca_file: str | None = None
    proxmox_token_file: str | None = None

settings = Settings()
