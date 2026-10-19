from pydantic_settings import SettingsConfigDict


def _group_config() -> SettingsConfigDict:
    return SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
    )


def _empty_as_none(value: object) -> object:
    if value == "":
        return None
    return value


def _strip_slash(value: str) -> str:
    return value.rstrip("/")
