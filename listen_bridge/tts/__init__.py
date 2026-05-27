"""TTS engine dispatch."""

import re

from .. import config


_ASCII_LETTER_RE = re.compile(r"[A-Za-z]")


def _english_ratio(text: str) -> float:
    """Fraction of characters that are ASCII letters. Used by the
    'auto' router to decide whether a given utterance should go to
    the English-strong engine (Edge) or the Chinese-clone engine
    (GPT-SoVITS)."""
    if not text:
        return 0.0
    letters = len(_ASCII_LETTER_RE.findall(text))
    # Use total length (incl. CJK chars and punctuation) as the
    # denominator — single English words inside a Chinese sentence
    # then score low and stay on the clone engine.
    return letters / len(text)


def _resolve_engine(text: str) -> str:
    """Resolve the configured engine for a given utterance. 'auto'
    inspects the text; everything else is static."""
    engine = config.TTS_ENGINE.lower()
    if engine != "auto":
        return engine
    ratio = _english_ratio(text)
    if ratio > config.TTS_AUTO_ENGLISH_THRESHOLD:
        return config.TTS_AUTO_EN_ENGINE
    return config.TTS_AUTO_ZH_ENGINE


def speak(text: str, engine: str | None = None) -> None:
    """Synthesize and play `text`.

    `engine` lets a caller override config.TTS_ENGINE for this one
    utterance — used by the Notification hook to force short prompts
    through a reliable engine (Edge) regardless of the main voice
    setting, so the user-facing voice clone stays decoupled from the
    short-utterance robustness needs of the notification path."""
    if not text:
        return
    if engine:
        engine = engine.lower()
    else:
        engine = _resolve_engine(text)
    if engine == "edge":
        from . import edge
        edge.speak(text)
    elif engine == "piper":
        from . import piper
        piper.speak(text)
    elif engine == "elevenlabs":
        from . import elevenlabs
        elevenlabs.speak(text)
    elif engine == "fish":
        # fish.speak() falls back to TTS_FALLBACK_ENGINE internally if CUDA
        # / fish-speech / the local server is unavailable, so this branch is
        # safe on machines without a GPU.
        from . import fish
        fish.speak(text)
    elif engine == "gptsovits":
        # gptsovits.speak() talks to a long-lived `api_v2.py` server in
        # .venv-gptsovits/. Same safety net as fish — falls back to
        # TTS_FALLBACK_ENGINE if CUDA / models / server is missing.
        from . import gptsovits
        gptsovits.speak(text)
    else:
        from . import system
        system.speak(text)
