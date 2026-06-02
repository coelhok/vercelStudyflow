from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    app_name: str = "StudyFlow PDF AI"
    app_env: str = "development"
    app_debug: bool = True
    log_level: str = "debug"  # debug | info | warning | error | silent

    # Local: sqlite:///./data/studyflow.db
    # Supabase/PostgreSQL: postgresql://postgres:senha@host:5432/postgres
    database_url: str = "sqlite:///./data/studyflow.db"

    jwt_secret: str = "change_me_in_production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24

    llm_provider: str = "mock"  # mock | gemini | openai | groq
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-1.5-flash"
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"

    supabase_url: str = ""
    supabase_service_key: str = ""
    supabase_anon_key: str = ""
    supabase_bucket: str = "documents"

    max_upload_size_mb: int = 15
    ocr_max_pages: int = 50
    ocr_languages: str = "por+eng"
    ocr_render_scale: float = 2.2

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()
