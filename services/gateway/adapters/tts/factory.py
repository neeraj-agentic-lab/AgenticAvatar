from .base import TTSAdapter


def create_tts_adapter(provider: str, **kwargs) -> TTSAdapter:
    if provider == "kokoro":
        from .kokoro import KokoroTTSAdapter
        return KokoroTTSAdapter(
            model_path=kwargs.get("model_path", "/models/kokoro/kokoro-v1_0.onnx"),
            voices_path=kwargs.get("voices_path", "/models/kokoro/voices-v1_0.bin"),
            voice=kwargs.get("voice", "af_heart"),
        )

    if provider == "mock":
        from .mock import MockTTSAdapter
        return MockTTSAdapter()

    if provider == "cartesia":
        from .cartesia import CartesiaTTSAdapter
        return CartesiaTTSAdapter(api_key=kwargs["api_key"])

    if provider == "elevenlabs":
        from .elevenlabs import ElevenLabsTTSAdapter
        return ElevenLabsTTSAdapter(api_key=kwargs["api_key"])

    if provider == "openai":
        from .openai import OpenAITTSAdapter
        return OpenAITTSAdapter(api_key=kwargs["api_key"])

    raise ValueError(
        f"Unknown TTS provider: '{provider}'. "
        f"Supported: cartesia, elevenlabs, openai"
    )
