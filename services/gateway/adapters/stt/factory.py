from .base import STTAdapter


def create_stt_adapter(provider: str, **kwargs) -> STTAdapter:
    if provider == "deepgram":
        from .deepgram import DeepgramSTTAdapter
        return DeepgramSTTAdapter(api_key=kwargs["api_key"])

    raise ValueError(
        f"Unknown STT provider: '{provider}'. "
        f"Supported: deepgram"
    )
