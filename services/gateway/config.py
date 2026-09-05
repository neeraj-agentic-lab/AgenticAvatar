from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_env: str = "development"

    # Salesforce
    salesforce_login_url: str = "https://login.salesforce.com"
    salesforce_instance_url: str = ""
    salesforce_client_id: str = ""
    salesforce_client_secret: str = ""
    salesforce_agent_id: str = ""
    salesforce_agent_api_version: str = "v1"

    # Conversation mode: "standard" (STT + Agentforce) or "agentforce_voice"
    conversation_mode: str = "standard"
    salesforce_instance_url: str = ""

    # STT — used only when conversation_mode=standard
    stt_provider: str = "deepgram"
    deepgram_api_key: str = ""

    # TTS
    tts_provider: str = "kokoro"
    # Cartesia
    cartesia_api_key: str = ""
    cartesia_voice_id: str = ""
    cartesia_model_id: str = "sonic-english"
    # Kokoro (local, no API key needed)
    kokoro_model_path: str = "/models/kokoro/kokoro-v1_0.onnx"   # symlink to kokoro-v1.0.onnx
    kokoro_voices_path: str = "/models/kokoro/voices-v1_0.bin"   # symlink to voices-v1.0.bin
    kokoro_voice: str = "af_heart"

    # LiveKit
    livekit_url: str = "ws://localhost:7880"          # internal URL (service-to-service)
    livekit_public_url: str = "ws://localhost:7880"   # browser-facing URL
    livekit_api_key: str = "devkey"
    livekit_api_secret: str = "devsecret"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Avatar worker
    avatar_worker_target: str = "localhost:50051"
    mock_mode: bool = True

    class Config:
        env_file = ".env"


settings = Settings()
