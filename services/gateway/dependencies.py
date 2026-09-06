from functools import lru_cache

from config import settings
from adapters.agentforce.auth import SalesforceAuth
from adapters.conversation.factory import create_conversation_adapter
from adapters.conversation.base import ConversationAdapter
from adapters.tts.factory import create_tts_adapter
from adapters.tts.base import TTSAdapter
from avatar_client import AvatarWorkerClient


@lru_cache
def get_salesforce_auth() -> SalesforceAuth:
    return SalesforceAuth(
        login_url=settings.salesforce_login_url,
        client_id=settings.salesforce_client_id,
        client_secret=settings.salesforce_client_secret,
    )


@lru_cache
def get_conversation_adapter() -> ConversationAdapter:
    return create_conversation_adapter(
        mode=settings.conversation_mode,
        auth=get_salesforce_auth(),
        instance_url=settings.salesforce_instance_url,
        agent_id=settings.salesforce_agent_id,
        api_version=settings.salesforce_agent_api_version,
        stt_provider=settings.stt_provider,
        stt_api_key=settings.deepgram_api_key,
    )


@lru_cache
def get_tts_adapter() -> TTSAdapter:
    return create_tts_adapter(
        settings.tts_provider,
        api_key=settings.cartesia_api_key,
        model_path=settings.kokoro_model_path,
        voices_path=settings.kokoro_voices_path,
        voice=settings.kokoro_voice,
    )


def get_avatar_client() -> AvatarWorkerClient:
    # New client per call — gRPC channel caches internally; don't cache broken connections
    return AvatarWorkerClient(target=settings.avatar_worker_target)
