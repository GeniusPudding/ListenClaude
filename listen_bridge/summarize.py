"""Local heuristic summarization — no LLM, no network."""

import re

_SENTENCE_END = re.compile(r"(?<=[。！？.!?])\s+|(?<=[。！？.!?])$")


def split_paragraphs(text: str) -> list[str]:
    return [p.strip() for p in text.split("\n\n") if p.strip()]


def split_sentences(paragraph: str) -> list[str]:
    sents = _SENTENCE_END.split(paragraph)
    return [s.strip() for s in sents if s.strip()]


def first_paragraph(text: str) -> str:
    paras = split_paragraphs(text)
    return paras[0] if paras else ""


_BULLET_RE = re.compile(r"^\s*(?:[-*•·]|\d+[.)])\s+")
_HEADER_RE = re.compile(r"^\s*#{1,6}\s+")
_TABLE_RE  = re.compile(r"^\s*\|")


def progress_summary(text: str, max_bullets: int = 4) -> str:
    """What-was-done style summary: short opening + first few bullets.

    Designed for spoken playback. Claude responses in this project tend
    to open with a short status sentence ("推上了 …") followed by a
    bullet list of concrete changes. Read both so the listener knows
    what the turn accomplished, not just that something happened.
    """
    intro = ""
    bullets: list[str] = []
    in_code = False

    for raw in text.split("\n"):
        line = raw.strip()
        if raw.lstrip().startswith("```"):
            in_code = not in_code
            continue
        if in_code or not line:
            continue
        if _HEADER_RE.match(line):
            if not intro:
                intro = _HEADER_RE.sub("", line)
            continue
        if _BULLET_RE.match(line):
            if len(bullets) < max_bullets:
                content = _BULLET_RE.sub("", line)
                content = re.sub(r"`([^`]+)`", r"\1", content)
                content = re.sub(r"\*\*([^*]+)\*\*", r"\1", content)
                bullets.append(content)
            continue
        if _TABLE_RE.match(line):
            continue
        if not intro:
            sents = split_sentences(line)
            if sents:
                intro = sents[0]

    def _clean(s: str) -> str:
        s = re.sub(r"`([^`]+)`", r"\1", s)
        s = re.sub(r"\*\*([^*]+)\*\*", r"\1", s)
        return s.rstrip("。!?.!?")

    parts = []
    if intro:
        parts.append(_clean(intro))
    if bullets:
        # Join bullets with "。" so each item becomes a full sentence — gives
        # Edge / system TTS a clear falling intonation per bullet instead of
        # racing through them like a comma-separated enumeration.
        parts.append("要點:" + "。".join(_clean(b) for b in bullets))
    if parts:
        return "。".join(parts)
    return first_paragraph(text)


def heuristic_summary(text: str) -> str:
    """Pick headings (lines starting with #) and the first sentence of each
    paragraph; skip code blocks entirely."""
    out = []
    in_code = False
    for raw in text.split("\n"):
        stripped = raw.strip()
        if stripped.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        if stripped.startswith("#"):
            out.append(stripped.lstrip("#").strip())
            continue
    paras = split_paragraphs(text)
    for p in paras:
        if p.startswith("#") or p.startswith("```"):
            continue
        sents = split_sentences(p)
        if sents:
            out.append(sents[0])
    return " ".join(out)


def prepare_text(text: str, mode: str, max_chars: int) -> str:
    """Apply the configured summarization mode and truncate to max_chars."""
    if mode == "llm":
        from . import llm
        rewritten = llm.summarize_via_claude(text)
        if rewritten:
            result = rewritten
        else:
            # CLI missing or call failed — fall back to the best heuristic.
            result = progress_summary(strip_markdown_noise(text))
    else:
        text = strip_markdown_noise(text)
        if mode == "full":
            result = text
        elif mode == "first":
            result = first_paragraph(text)
        elif mode == "summary":
            result = heuristic_summary(text)
        elif mode == "progress":
            result = progress_summary(text)
        else:
            result = text
    if len(result) > max_chars:
        result = result[: max_chars - 1].rstrip() + "…"
    return result


def strip_markdown_noise(text: str) -> str:
    """Drop fenced code blocks, inline backticks, and Markdown link syntax —
    they don't read well in speech."""
    out_lines = []
    in_code = False
    for line in text.split("\n"):
        if line.lstrip().startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        out_lines.append(line)
    text = "\n".join(out_lines)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    return text
