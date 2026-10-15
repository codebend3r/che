"""ffprobe helpers and shared extension lists for the scripts under ``bin/video/``.

Split out of ``utils.py``, which keeps the logging, argument parsing and
subprocess plumbing every script shares. Scripts pick it up the same way::

    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from media import probe_media

Standard library only, like everything else at the ``bin/`` root. ffprobe
itself is an external binary; callers check for it with ``require_binary``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from utils import run

# The two containers the library is kept in: what delete-duplicate-videos,
# rename-video-file, validate-video-files and video-list all scan.
LIBRARY_EXTENSIONS = ("mp4", "mkv")

# What show-codecs audits and fix-codecs re-encodes. One list, so fix-codecs
# can never pass over a file show-codecs reported.
CODEC_SCAN_EXTENSIONS = ("mp4", "mkv", "mov", "avi")

# Everything any video script reads, so each file is opened once.
_PROBE_ENTRIES = "stream=codec_type,codec_name,width:stream_tags=language:format=bit_rate"


@dataclass(frozen=True)
class MediaProbe:
    """ffprobe's view of one file's streams and container.

    The codec and language accessors return what the one-field-per-call
    ffprobe invocations the scripts used to make printed, so callers read the
    same values as before. That takes restoring by hand: the JSON writer OMITS
    a field ffprobe cannot fill, where the csv and default writers printed
    ``unknown`` or ``N/A``. ``width`` and ``bit_rate`` are numbers instead,
    ``None`` where ffprobe had nothing to report.

    One difference is deliberate. On ffprobe 9 the csv writer appended a comma
    per side-data block on the stream, so AC3 or E-AC3 audio in an MP4 came
    back as ``ac3,`` and its language as ``und,``. JSON has no such artefact.
    """

    streams: tuple[dict, ...]
    format: dict

    @classmethod
    def from_json(cls, data: dict) -> MediaProbe:
        """Build from ffprobe's parsed ``-of json`` output."""
        return cls(streams=tuple(data.get("streams", ())), format=data.get("format", {}))

    def first(self, kind: str) -> dict | None:
        """The first ``"video"``/``"audio"``/``"subtitle"`` stream: ``-select_streams v:0``."""
        return next((s for s in self.streams if s.get("codec_type") == kind), None)

    def codec(self, kind: str) -> str:
        """The first ``kind`` stream's codec.

        ``""`` when there is no such stream, ``"unknown"`` when there is one
        but ffprobe cannot name its codec - the two values the per-field calls
        printed for those cases.
        """
        stream = self.first(kind)
        if stream is None:
            return ""
        return stream.get("codec_name", "unknown")

    def width(self) -> int | None:
        """The first video stream's width in pixels, or None."""
        return _count((self.first("video") or {}).get("width", ""))

    def bit_rate(self) -> int | None:
        """The container's overall bit rate, or None where ffprobe said ``N/A``."""
        return _count(self.format.get("bit_rate", ""))

    def languages(self, kind: str) -> list[str]:
        """Every language tagged on a ``kind`` stream, sorted and de-duplicated.

        The key is matched case-insensitively because ``-show_entries
        stream_tags=language`` matches that way, so a container's ``LANGUAGE``
        tag arrives under its own spelling.
        """
        return sorted(
            {
                value.strip()
                for stream in self.streams
                if stream.get("codec_type") == kind
                for key, value in stream.get("tags", {}).items()
                if key.lower() == "language" and value.strip()
            }
        )


def _count(value: object) -> int | None:
    """``value`` as a non-negative integer, or None when it is absent or not numeric."""
    text = str(value)
    return int(text) if text.isdecimal() else None


def probe_media(path: Path) -> MediaProbe | None:
    """Probe ``path`` once for everything the video scripts read.

    Returns None when ffprobe fails - a corrupt or unreadable file - which
    callers have to tell apart from a readable file that lacks a stream or a
    tag. One process per file, where the scripts used to spawn one per field:
    on an SMB share each of those re-opened the file and re-read its header.
    """
    completed = run(
        ["ffprobe", "-v", "error", "-show_entries", _PROBE_ENTRIES, "-of", "json", str(path)],
        check=False,
        capture=True,
    )
    if completed.returncode != 0:
        return None
    try:
        data = json.loads(completed.stdout or "")
    except json.JSONDecodeError:
        return None
    return MediaProbe.from_json(data)
