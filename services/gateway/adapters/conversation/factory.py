from adapters.agentforce.auth import SalesforceAuth
from .base import ConversationAdapter


def create_conversation_adapter(  # noqa: PLR0913
    mode: str,
    auth: SalesforceAuth,
    instance_url: str,
    agent_id: str,
    api_version: str = "v1",
    stt_provider: str = "deepgram",
    stt_api_key: str = "",
) -> ConversationAdapter:
    if mode == "mock":
        from .mock import MockConversationAdapter
        return MockConversationAdapter()

    if mode == "standard":
        from adapters.agentforce.client import AgentforceClient
        from adapters.stt.factory import create_stt_adapter
        from .standard import StandardConversationAdapter

        stt = create_stt_adapter(stt_provider, api_key=stt_api_key)
        agentforce = AgentforceClient(auth, instance_url, agent_id, api_version)
        return StandardConversationAdapter(stt=stt, agentforce=agentforce)

    if mode == "agentforce_voice":
        from .agentforce_voice import AgentforceVoiceAdapter

        return AgentforceVoiceAdapter(auth=auth, instance_url=instance_url, agent_id=agent_id)

    raise ValueError(
        f"Unknown conversation mode: '{mode}'. "
        f"Supported: mock, standard, agentforce_voice"
    )
