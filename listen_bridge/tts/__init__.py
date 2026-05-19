"""TTS engine dispatch."""

from .. import config


def speak(text: str) -> None:
    if not text:
        return
    engine = config.TTS_ENGINE.lower()
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
    else:
        from . import system
        system.speak(text)
