from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "local"
    dry_run: bool = True
    task_always_eager: bool = False

    redis_url: str = "redis://redis:6379/0"
    celery_broker_url: str = "redis://redis:6379/0"
    celery_result_backend: str = "redis://redis:6379/1"

    llm_provider: str = ""
    llm_api_key: str = ""
    llm_model: str = ""

    jira_base_url: str = ""
    jira_project_key: str = "SRE"
    jira_api_token: str = ""
    jira_user_email: str = ""

    github_token: str = ""
    github_owner: str = ""
    github_repo: str = ""
    github_base_branch: str = "main"

    max_memory_limit_gi: float = Field(default=4.0, gt=0)
    dedupe_ttl_seconds: int = Field(default=300, gt=0)
    correlation_ttl_seconds: int = Field(default=3600, gt=0)


@lru_cache
def get_settings() -> Settings:
    return Settings()

