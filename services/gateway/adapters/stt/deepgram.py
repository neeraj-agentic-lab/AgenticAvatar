from typing import AsyncGenerator

from deepgram import DeepgramClient, LiveTranscriptionEvents, LiveOptions

from .base import STTAdapter, TranscriptEvent


class DeepgramSTTAdapter(STTAdapter):
    def __init__(self, api_key: str):
        self._client = DeepgramClient(api_key)
        self._connection = None

    async def stream(
        self,
        audio_chunks: AsyncGenerator[bytes, None],
        sample_rate: int = 16000,
        channels: int = 1,
    ) -> AsyncGenerator[TranscriptEvent, None]:
        import asyncio

        queue: asyncio.Queue[TranscriptEvent | None] = asyncio.Queue()

        connection = self._client.listen.asynclive.v("1")
        self._connection = connection

        async def on_transcript(_, result, **kwargs):
            alt = result.channel.alternatives[0]
            text = alt.transcript.strip()
            if not text:
                return
            await queue.put(TranscriptEvent(
                text=text,
                is_final=result.is_final,
                confidence=alt.confidence,
                duration_ms=int(result.duration * 1000),
            ))

        async def on_close(*_, **__):
            await queue.put(None)

        connection.on(LiveTranscriptionEvents.Transcript, on_transcript)
        connection.on(LiveTranscriptionEvents.Close, on_close)

        options = LiveOptions(
            model="nova-2",
            language="en-US",
            encoding="linear16",
            sample_rate=sample_rate,
            channels=channels,
            interim_results=True,
            endpointing=300,
            utterance_end_ms=1000,
        )
        await connection.start(options)

        async def send_audio():
            async for chunk in audio_chunks:
                await connection.send(chunk)
            await connection.finish()

        asyncio.create_task(send_audio())

        while True:
            event = await queue.get()
            if event is None:
                break
            yield event

    async def close(self) -> None:
        if self._connection:
            await self._connection.finish()
            self._connection = None
