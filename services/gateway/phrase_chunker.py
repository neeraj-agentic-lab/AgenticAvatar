import asyncio
import re
from typing import AsyncGenerator

_SENTENCE_END = re.compile(r'[.!?](?:\s|$)')
_CLAUSE_BREAK = re.compile(r'[,;:]\s')
_NO_SPLIT = re.compile(
    r'(?:'
    r'\d[\d,._:/%-]*'
    r'|https?://\S+'
    r'|www\.\S+'
    r'|[A-Z]{2,}'
    r'|(?:[A-Za-z]\.){2,}'
    r'|Mr\.|Mrs\.|Dr\.|Sr\.|Jr\.'
    r')'
)

_MIN_WORDS_FOR_CLAUSE = 12
_MAX_WORDS = 25
_SILENCE_TIMEOUT_MS = 150


async def chunk_text(
    text_deltas: AsyncGenerator[str, None],
    min_words: int = _MIN_WORDS_FOR_CLAUSE,
    max_words: int = _MAX_WORDS,
    silence_ms: int = _SILENCE_TIMEOUT_MS,
) -> AsyncGenerator[str, None]:
    """
    Consume streamed text deltas and yield complete, TTS-safe phrases.

    Uses an internal queue so asyncio.wait_for never touches the async
    generator directly — avoiding the Python bug where cancelling
    __anext__() leaves the generator permanently closed.
    """
    queue: asyncio.Queue[str | None] = asyncio.Queue()

    async def _feed():
        try:
            async for delta in text_deltas:
                await queue.put(delta)
        finally:
            await queue.put(None)

    feed_task = asyncio.create_task(_feed())
    buffer = ""

    try:
        while True:
            # Safely timeout on queue.get() — queue is not an async generator
            try:
                delta = await asyncio.wait_for(queue.get(), timeout=silence_ms / 1000)
            except asyncio.TimeoutError:
                if buffer.strip():
                    phrase = _clean(buffer.strip())
                    if phrase:
                        yield phrase
                    buffer = ""
                continue

            if delta is None:
                break

            buffer += delta
            word_count = len(buffer.split())

            # Rule 1: sentence-ending punctuation
            match = _SENTENCE_END.search(buffer)
            if match and not _in_no_split_zone(buffer, match.start()):
                yield_text = buffer[: match.end()].strip()
                buffer = buffer[match.end():]
                phrase = _clean(yield_text)
                if phrase:
                    yield phrase
                continue

            # Rule 2: clause break after min_words
            if word_count >= min_words:
                match = _CLAUSE_BREAK.search(buffer)
                if match and not _in_no_split_zone(buffer, match.start()):
                    yield_text = buffer[: match.end()].strip()
                    buffer = buffer[match.end():]
                    phrase = _clean(yield_text)
                    if phrase:
                        yield phrase
                    continue

            # Rule 3: force break at max_words
            if word_count >= max_words:
                idx = _last_safe_split(buffer)
                if idx > 0:
                    yield_text = buffer[:idx].strip()
                    buffer = buffer[idx:]
                    phrase = _clean(yield_text)
                    if phrase:
                        yield phrase

        # Rule 5: flush remainder
        if buffer.strip():
            phrase = _clean(buffer.strip())
            if phrase:
                yield phrase

    finally:
        feed_task.cancel()
        try:
            await feed_task
        except (asyncio.CancelledError, Exception):
            pass


def _in_no_split_zone(text: str, pos: int) -> bool:
    for m in _NO_SPLIT.finditer(text):
        if m.start() <= pos <= m.end():
            return True
    return False


def _last_safe_split(text: str) -> int:
    for i in range(len(text) - 1, 0, -1):
        if text[i].isspace() and not _in_no_split_zone(text, i):
            return i
    return 0


def _clean(text: str) -> str:
    text = re.sub(r'\*{1,3}(.*?)\*{1,3}', r'\1', text)
    text = re.sub(r'`[^`]*`', '', text)
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    text = re.sub(r'\[\d+(?:,\s*\d+)*\]', '', text)
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'\s+', ' ', text).strip()
    return text
