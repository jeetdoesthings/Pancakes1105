import os
from dotenv import load_dotenv

_APP_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_APP_DIR)
load_dotenv(os.path.join(_PROJECT_ROOT, ".env"))


class Settings:
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    LLM_MODEL_NAME: str = os.getenv("LLM_MODEL_NAME", "deepseek-chat")
    PRIMARY_MODEL: str = os.getenv("PRIMARY_MODEL", os.getenv("LLM_MODEL_NAME", "deepseek-chat"))
    FAST_MODEL: str = os.getenv("FAST_MODEL", "llama-3.3-70b-versatile")
    ESTIMATOR_MODEL: str = os.getenv("ESTIMATOR_MODEL", "llama-3.1-8b-instant")
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    GROQ_BASE_URL: str = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
    DEEPSEEK_API_KEY: str = os.getenv("DEEPSEEK_API_KEY", "")
    DEEPSEEK_BASE_URL: str = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
    APP_HOST: str = os.getenv("APP_HOST", "0.0.0.0")
    APP_PORT: int = int(os.getenv("APP_PORT", "8000"))
    # Default false — enable explicitly for local development
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"
    # Upload / RFP size guards (bytes / characters)
    MAX_UPLOAD_BYTES: int = int(os.getenv("MAX_UPLOAD_BYTES", str(15 * 1024 * 1024)))
    MAX_RFP_TEXT_CHARS: int = int(os.getenv("MAX_RFP_TEXT_CHARS", "2000000"))

    # Paths
    BASE_DIR: str = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    DATA_DIR: str = os.path.join(BASE_DIR, "data")
    STATIC_DIR: str = os.path.join(BASE_DIR, "static")
    TEMPLATES_DIR: str = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
    OUTPUT_DIR: str = os.path.join(BASE_DIR, "output")

    # DeepSeek token limits (deepseek-chat model)
    DEEPSEEK_MAX_CONTEXT: int = 64_000   # 64K context window
    DEEPSEEK_MAX_OUTPUT: int = 8_000     # 8K max output tokens

    # Company defaults
    COMPANY_NAME: str = os.getenv("COMPANY_NAME", "Ering Solutions")
    DEFAULT_CURRENCY: str = os.getenv("DEFAULT_CURRENCY", "INR")
    DEFAULT_CLIENT_PROFILE: str = os.getenv("DEFAULT_CLIENT_PROFILE", "private_enterprise")


settings = Settings()

# Ensure output dir exists
os.makedirs(settings.OUTPUT_DIR, exist_ok=True)
