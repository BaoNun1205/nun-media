from __future__ import annotations

import re
from pathlib import Path

from .models import SubtitleSegment


TIMECODE_RE = re.compile(
    r"(?P<start>\d{2}:\d{2}:\d{2},\d{3})\s+-->\s+(?P<end>\d{2}:\d{2}:\d{2},\d{3})"
)


def seconds_to_srt_time(value: float) -> str:
    millis = max(0, int(round(value * 1000)))
    hours, rem = divmod(millis, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    seconds, millis = divmod(rem, 1000)
    return f"{hours:02}:{minutes:02}:{seconds:02},{millis:03}"


def srt_time_to_seconds(value: str) -> float:
    hh, mm, rest = value.split(":")
    ss, ms = rest.split(",")
    return int(hh) * 3600 + int(mm) * 60 + int(ss) + int(ms) / 1000


def write_srt(segments: list[SubtitleSegment], path: Path) -> None:
    lines: list[str] = []
    for i, segment in enumerate(segments, start=1):
        text = " ".join(segment.text.split())
        lines.extend(
            [
                str(i),
                f"{seconds_to_srt_time(segment.start)} --> {seconds_to_srt_time(segment.end)}",
                text,
                "",
            ]
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def read_srt(path: Path) -> list[SubtitleSegment]:
    raw = path.read_text(encoding="utf-8-sig")
    blocks = re.split(r"\n\s*\n", raw.strip(), flags=re.MULTILINE)
    segments: list[SubtitleSegment] = []
    for block in blocks:
        lines = [line.strip("\ufeff") for line in block.splitlines() if line.strip()]
        if len(lines) < 3:
            continue
        try:
            index = int(lines[0].strip())
        except ValueError:
            index = len(segments) + 1
        match = TIMECODE_RE.search(lines[1])
        if not match:
            continue
        segments.append(
            SubtitleSegment(
                index=index,
                start=srt_time_to_seconds(match.group("start")),
                end=srt_time_to_seconds(match.group("end")),
                text=" ".join(lines[2:]).strip(),
            )
        )
    return segments
