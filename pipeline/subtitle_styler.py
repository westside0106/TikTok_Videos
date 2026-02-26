"""
TikTok-style ASS subtitle generator.

Uses a two-layer approach for word-by-word highlighting:
  Layer 0: Full line in white (always visible during line duration)
  Layer 1: One dialogue event per word, highlighted in yellow with full line context
"""
import logging
from pathlib import Path
from dataclasses import dataclass

from utils.file_utils import seconds_to_ass_time

logger = logging.getLogger(__name__)

WORDS_PER_LINE = 4


@dataclass
class SubtitleStyle:
    font_name: str = "Arial"
    font_size: int = 72
    # ASS color format: &HAABBGGRR (AA=alpha, 00=opaque)
    primary_color: str = "&H00FFFFFF"    # white
    highlight_color: str = "&H0000FFFF"  # yellow
    outline_color: str = "&H00000000"    # black
    shadow_color: str = "&H80000000"     # semi-transparent black
    bold: int = -1                        # -1 = true in ASS
    outline_width: float = 3.0
    shadow_depth: float = 2.0
    margin_v: int = 80                   # pixels from bottom


_ASS_HEADER = """\
[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font_name},{font_size},{primary},{secondary},{outline},{shadow},{bold},0,0,0,100,100,0,0,1,{outline_w},{shadow_d},2,10,10,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def generate_ass_file(
    words: list,
    output_path: Path,
    clip_start: float,
    clip_end: float,
    style: SubtitleStyle = None,
) -> Path:
    """
    Generate a .ass subtitle file for the given clip window [clip_start, clip_end].
    Times are re-offset relative to clip_start so the clip starts at 0:00:00.

    Returns the path to the generated .ass file.
    """
    if style is None:
        style = SubtitleStyle()

    # Filter and re-offset words to clip-relative time
    clip_words = []
    for w in words:
        if w.start >= clip_start and w.end <= clip_end + 0.5:
            from pipeline.transcriber import WordSegment
            clip_words.append(WordSegment(
                word=w.word,
                start=w.start - clip_start,
                end=w.end - clip_start,
                probability=w.probability,
            ))

    header = _ASS_HEADER.format(
        font_name=style.font_name,
        font_size=style.font_size,
        primary=style.primary_color,
        secondary=style.primary_color,
        outline=style.outline_color,
        shadow=style.shadow_color,
        bold=style.bold,
        outline_w=style.outline_width,
        shadow_d=style.shadow_depth,
        margin_v=style.margin_v,
    )

    dialogue_lines = _build_dialogue_lines(clip_words, style)

    content = header + "\n".join(dialogue_lines) + "\n"
    output_path.write_text(content, encoding="utf-8")
    logger.debug("Generated ASS subtitle: %s (%d dialogue lines)", output_path.name, len(dialogue_lines))
    return output_path


def _group_words_into_lines(words: list, words_per_line: int = WORDS_PER_LINE) -> list:
    """Group flat word list into lines of words_per_line words."""
    groups = []
    for i in range(0, len(words), words_per_line):
        groups.append(words[i:i + words_per_line])
    return groups


def _build_dialogue_lines(words: list, style: SubtitleStyle) -> list:
    """
    Build all ASS Dialogue lines for the clip.
    Uses two-layer technique:
      Layer 0: Full line in white (baseline)
      Layer 1: Full line with one word highlighted yellow (per word)
    """
    if not words:
        return []

    groups = _group_words_into_lines(words)
    lines = []

    for group in groups:
        if not group:
            continue

        line_start = seconds_to_ass_time(group[0].start)
        # Add 0.3s buffer after last word so text doesn't vanish abruptly
        line_end = seconds_to_ass_time(group[-1].end + 0.3)
        full_text = " ".join(w.word.strip() for w in group)

        # Layer 0: white baseline line
        lines.append(
            f"Dialogue: 0,{line_start},{line_end},Default,,0,0,0,,{{\\an2}}{full_text}"
        )

        # Layer 1: one event per word, that word highlighted yellow
        for i, word in enumerate(group):
            w_start = seconds_to_ass_time(word.start)
            w_end = seconds_to_ass_time(word.end + 0.05)  # tiny overlap for smoothness

            # Rebuild full line with only current word in yellow
            highlighted_text = _build_highlighted_line(group, i, style)

            lines.append(
                f"Dialogue: 1,{w_start},{w_end},Default,,0,0,0,,{{\\an2}}{highlighted_text}"
            )

    return lines


def _build_highlighted_line(group: list, highlight_index: int, style: SubtitleStyle) -> str:
    """
    Reconstruct a full line where only the word at highlight_index is yellow.
    Other words remain white.

    Example result: "Hello {\\c&H0000FFFF&}world{\\c&H00FFFFFF&} this works"
    """
    parts = []
    for i, word in enumerate(group):
        text = word.word.strip()
        if i == highlight_index:
            parts.append(f"{{\\c{style.highlight_color}&}}{text}{{\\c{style.primary_color}&}}")
        else:
            parts.append(text)
    return " ".join(parts)
