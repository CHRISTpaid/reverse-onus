"""Suno lyric syntax -> song structure -> engine lyric formats.

Suno reads structure from square-bracket meta tags on their own line ([Verse 1], [Chorus],
[Bridge], [Outro], [End]), case-insensitive, with optional descriptors after a colon or dash
([Verse: whispered vocals, acoustic guitar only]). [End] stops the song. Lines in
parentheses are sung as backing vocals and are kept as written.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

TAG = re.compile(r"^\s*\[([^\[\]]+)\]\s*$")
SECTION_WORDS = [  # longest first so "pre-chorus" wins over "chorus"
    ("pre-chorus", "pre-chorus"), ("prechorus", "pre-chorus"), ("post-chorus", "post-chorus"),
    ("build-up", "build"), ("buildup", "build"), ("breakdown", "breakdown"),
    ("interlude", "interlude"), ("instrumental", "instrumental"), ("refrain", "chorus"),
    ("chorus", "chorus"), ("verse", "verse"), ("bridge", "bridge"), ("intro", "intro"),
    ("outro", "outro"), ("hook", "hook"), ("solo", "solo"), ("drop", "drop"), ("break", "break"),
    ("build", "build"), ("end", "end"),
]
VOICE_TAGS = {"male vocal": "male vocals", "male vocals": "male vocals", "female vocal": "female vocals",
              "female vocals": "female vocals", "duet": "duet", "choir": "choir", "spoken word": "spoken word",
              "rap": "rap vocals", "whisper": "whispered vocals", "whispered": "whispered vocals"}
INSTRUMENTAL = {"intro", "outro", "interlude", "instrumental", "solo", "break", "breakdown", "drop", "build"}


@dataclass
class Section:
    kind: str                     # verse, chorus, ... ; "body" for untagged text
    number: int | None = None
    descriptors: list[str] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)
    raw_tag: str = ""

    @property
    def instrumental(self) -> bool:
        return not self.lines

    @property
    def label(self) -> str:
        return self.kind.title() + (f" {self.number}" if self.number else "")


@dataclass
class Song:
    sections: list[Section]
    voice: list[str] = field(default_factory=list)   # global voice hints from tags like [Female Vocal]
    ended: bool = False                               # an [End] tag was present

    @property
    def lyric_lines(self) -> list[str]:
        return [ln for s in self.sections for ln in s.lines]

    @property
    def is_instrumental(self) -> bool:
        return not self.lyric_lines


def _classify(tag: str) -> tuple[str | None, int | None, list[str], list[str]]:
    """Return (section kind or None, number, descriptors, voice hints)."""
    text = tag.strip()
    head, desc = text, ""
    m = re.match(r"^(.*?)\s*(?::|\s-\s|\s–\s)\s*(.+)$", text)
    if m:
        head, desc = m.group(1), m.group(2)
    descriptors = [d.strip() for d in re.split(r",|;", desc) if d.strip()]
    low = head.lower().strip()
    voice = [v for k, v in VOICE_TAGS.items() if low == k]
    if voice:
        return None, None, descriptors, voice
    num = None
    nm = re.search(r"(\d+)\s*$", low)
    if nm:
        num = int(nm.group(1))
        low = low[: nm.start()].strip()
    for word, kind in SECTION_WORDS:
        if word in low:
            if low.replace(word, "").strip(" -"):  # e.g. "guitar solo", "melodic outro"
                descriptors = [low] + descriptors
            return kind, num, descriptors, []
    # unknown tag such as [Fade Out] or [Guitar Riff]: a descriptor for what follows
    return None, None, [head.strip()] + descriptors, []


def parse(text: str) -> Song:
    sections: list[Section] = []
    voice: list[str] = []
    pending: list[str] = []   # descriptors from non-section tags, applied to the next section
    cur: Section | None = None
    ended = False
    for raw in (text or "").replace("\r\n", "\n").split("\n"):
        line = raw.strip()
        m = TAG.match(line)
        if m:
            kind, num, desc, vhints = _classify(m.group(1))
            if kind == "end":
                ended = True
                break
            if vhints:  # [Female Vocal]: whole song at the top, else the section it sits in/before
                if cur is None:
                    voice.extend(v for v in vhints if v not in voice)
                elif cur.lines:
                    pending.extend(vhints)
                else:
                    cur.descriptors.extend(vhints)
                continue
            if kind is None:
                if cur is not None and not cur.lines:
                    cur.descriptors.extend(desc)
                else:
                    pending.extend(desc)
                continue
            cur = Section(kind=kind, number=num, descriptors=pending + desc, raw_tag=m.group(1))
            pending = []
            sections.append(cur)
            continue
        if not line:
            continue
        if cur is None:
            cur = Section(kind="body", descriptors=pending)
            pending = []
            sections.append(cur)
        cur.lines.append(line)
    # A lone [Instrumental] tag means "no vocals", not an instrumental section of a vocal song.
    return Song(sections=sections, voice=voice, ended=ended)


def estimate_seconds(song: Song) -> float:
    """Rough song length when the user gives none (Suno picks length itself). Tune with A/B."""
    if not song.sections:
        return 120.0
    total = 0.0
    for s in song.sections:
        if s.lines:
            total += sum(max(2.2, 0.32 * len(ln.split())) for ln in s.lines) + 1.5
        else:
            total += 12.0 if s.kind in ("intro", "outro") else 16.0
    if song.sections[-1].kind != "outro":
        total += 6.0  # natural ending
    return float(min(max(total, 30.0), 480.0))


def render_tagged(song: Song, *, lowercase: bool = False, blank_between: bool = True,
                  keep_instrumental_sections: bool = True, numbered: bool = False) -> str:
    """Engine lyric format: plain [Section] tags, one per block. Descriptors are moved to the
    style caption by style.compile_caption (engines handle them better there)."""
    out: list[str] = []
    for s in song.sections:
        if s.instrumental and not keep_instrumental_sections:
            continue
        name = s.label if numbered else s.kind.title()
        if s.kind == "body":
            name = "Verse"
        tag = f"[{name.lower() if lowercase else name}]"
        out.append("\n".join([tag, *s.lines]))
    return ("\n\n" if blank_between else "\n").join(out)


def section_notes(song: Song) -> list[str]:
    """Per-section descriptors, e.g. 'chorus 1: powerful, gang vocals'."""
    return [f"{s.label.lower()}: {', '.join(s.descriptors)}" for s in song.sections if s.descriptors]


def plain_text(song: Song) -> str:
    """Lyrics without tags or backing-vocal parentheses, for word-error-rate scoring."""
    words = []
    for ln in song.lyric_lines:
        words.append(re.sub(r"\([^)]*\)", " ", ln))
    return " ".join(" ".join(words).split())
