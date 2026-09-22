"""Local credential loading for the installed OpsHub launcher."""

import json
import os
from pathlib import Path

from dotenv import load_dotenv


_CREDENTIAL_KEYS = ("GROQ_API_KEY", "OPENROUTER_API_KEY", "LLM_PROVIDER")
DEFAULT_GATEWAY_URL = "https://opshub-woad.vercel.app/"


def gateway_url() -> str:
    """Use an explicit reviewer gateway, otherwise the deployed demo gateway."""
    return os.getenv("OPSHUB_GATEWAY_URL", "").strip() or DEFAULT_GATEWAY_URL


def user_config_path() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "OpsHub" / "config.env"


def load_configuration() -> set[str]:
    """Load environment, project .env, then user config without overriding earlier values.

    Return keys supplied before user config so a setup update can preserve them.
    """
    load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)
    protected = {key for key in _CREDENTIAL_KEYS if key in os.environ}
    load_dotenv(user_config_path(), override=False)
    if not os.getenv("LLM_PROVIDER") and os.getenv("GROQ_API_KEY"):
        os.environ["LLM_PROVIDER"] = (
            "fallback" if os.getenv("OPENROUTER_API_KEY") else "qwen"
        )
    return protected


def needs_setup() -> bool:
    provider = os.getenv("LLM_PROVIDER", "").lower()
    if provider == "mock":
        return False
    if provider == "nex" and os.getenv("OPENROUTER_API_KEY"):
        return False
    return not bool(os.getenv("GROQ_API_KEY"))


def save_credentials(groq_key: str, openrouter_key: str) -> Path:
    groq_key, openrouter_key = groq_key.strip(), openrouter_key.strip()
    if not groq_key:
        raise ValueError("Groq API Key is required.")
    if any(char in key for key in (groq_key, openrouter_key) for char in "\r\n\x00"):
        raise ValueError("API keys must be single-line values.")
    path = user_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    content = (
        f"GROQ_API_KEY={json.dumps(groq_key)}\n"
        f"OPENROUTER_API_KEY={json.dumps(openrouter_key)}\n"
        f"LLM_PROVIDER={'fallback' if openrouter_key else 'qwen'}\n"
    )
    temporary = path.with_suffix(".tmp")
    try:
        with temporary.open("w", encoding="utf-8") as file:
            file.write(content)
        if os.name != "nt":
            temporary.chmod(0o600)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def apply_saved_credentials(protected: set[str]) -> None:
    """Refresh this process after setup while retaining higher-priority settings."""
    from dotenv import dotenv_values

    values = dotenv_values(user_config_path())
    for key in _CREDENTIAL_KEYS:
        if key not in protected:
            value = values.get(key)
            if value:
                os.environ[key] = value
            else:
                os.environ.pop(key, None)
