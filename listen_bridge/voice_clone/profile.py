"""Voice profile: read / write / locate the per-voice config file.

profile.json lives at ``voices/<name>/profile.json`` and looks like:

    {
        "name": "ig-demo",
        "description": "Taiwanese female from IG reels",
        "sources": [
            {"url": "https://...", "wav": "source/reel-1.wav"}
        ],
        "engines": {
            "gptsovits": {
                "reference":      "reference-c.wav",
                "reference_text": "reference-c.txt",
                "gpt_ckpt":       "training/GPT_weights/ig-demo-e15.ckpt",
                "synthesis": {
                    "speed_factor":    0.7,
                    "temperature":     0.5,
                    "top_p":           0.5,
                    "text_split":      "cut0"
                }
            }
        }
    }

All paths inside the file are **relative to the profile directory** so a
profile is self-contained and movable. Helpers below resolve them to
absolute paths against the profile's home dir.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

from .. import config


VOICES_ROOT = os.path.join(config._REPO_ROOT, "voices")


def profile_dir(name: str) -> str:
    """Absolute path to the directory holding profile.json for <name>."""
    return os.path.join(VOICES_ROOT, name)


def profile_path(name: str) -> str:
    return os.path.join(profile_dir(name), "profile.json")


@dataclass
class VoiceProfile:
    """In-memory view of a single voice profile."""

    name: str
    home: str                       # absolute path to voices/<name>/
    raw: dict[str, Any] = field(default_factory=dict)

    # --- lookup helpers --------------------------------------------------

    @property
    def description(self) -> str:
        return self.raw.get("description", "")

    def resolve(self, rel: str) -> str:
        """Turn a profile-relative path into an absolute path."""
        if not rel:
            return ""
        if os.path.isabs(rel):
            return rel
        return os.path.abspath(os.path.join(self.home, rel))

    def engine(self, engine_name: str) -> dict[str, Any]:
        return self.raw.get("engines", {}).get(engine_name, {})

    def has_engine(self, engine_name: str) -> bool:
        return bool(self.engine(engine_name))

    # --- mutation --------------------------------------------------------

    def add_source(self, url: str, wav_rel: str) -> None:
        sources = self.raw.setdefault("sources", [])
        for s in sources:
            if s.get("wav") == wav_rel:
                s["url"] = url
                return
        sources.append({"url": url, "wav": wav_rel})

    def set_engine(self, engine_name: str, cfg: dict[str, Any]) -> None:
        self.raw.setdefault("engines", {})[engine_name] = cfg

    def update_engine(self, engine_name: str, patch: dict[str, Any]) -> None:
        eng = self.raw.setdefault("engines", {}).setdefault(engine_name, {})
        eng.update(patch)

    # --- IO --------------------------------------------------------------

    def save(self) -> None:
        os.makedirs(self.home, exist_ok=True)
        path = profile_path(self.name)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.raw, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)


def load(name: str, create_if_missing: bool = False) -> VoiceProfile:
    """Load voices/<name>/profile.json. With create_if_missing=True a
    bare scaffold profile is materialised on disk so subsequent pipeline
    steps have something to mutate."""
    home = profile_dir(name)
    path = profile_path(name)
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    elif create_if_missing:
        raw = {"name": name, "description": "", "sources": [], "engines": {}}
        os.makedirs(home, exist_ok=True)
    else:
        raise FileNotFoundError(f"no voice profile at {path}")
    raw.setdefault("name", name)
    return VoiceProfile(name=name, home=home, raw=raw)


def list_profiles() -> list[VoiceProfile]:
    """All voice profiles under voices/ (anywhere with a profile.json)."""
    out: list[VoiceProfile] = []
    if not os.path.isdir(VOICES_ROOT):
        return out
    for entry in sorted(os.listdir(VOICES_ROOT)):
        full = os.path.join(VOICES_ROOT, entry)
        if entry.startswith("_") or not os.path.isdir(full):
            continue
        if os.path.isfile(os.path.join(full, "profile.json")):
            try:
                out.append(load(entry))
            except (OSError, json.JSONDecodeError):
                pass
    return out
