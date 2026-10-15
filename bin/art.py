"""The che wordmark and the face it shares a name with, as text.

``LOGO`` is the block-letter wordmark that ``che install``, ``che doctor`` and
the first-run screen print. ``FACE`` is Che Guevara, rendered from a photograph
to 32 columns by 18 rows so the two fit side by side in an 80-column terminal.
Dense characters are the bright parts of the photo, which reads correctly on a
dark background.

``banner()`` lays the face beside whatever a screen wants next to it, normally
the wordmark with a subtitle underneath, centred vertically on the face. Lines
may carry colour escapes; widths are measured with ``tui.display_width`` so the
escapes do not push the right-hand column about.
"""

from __future__ import annotations

from collections.abc import Sequence

import tui

LOGO = r"""
   ██████╗██╗  ██╗███████╗
  ██╔════╝██║  ██║██╔════╝
  ██║     ███████║█████╗
  ██║     ██╔══██║██╔══╝
  ╚██████╗██║  ██║███████╗
   ╚═════╝╚═╝  ╚═╝╚══════╝
"""

FACE = """
**#*-
#*-.         .::---:::.
=       .:+#%@@@@@@@@@%#*+-.
      .-*%@@@@@@@@@*==----+*-
     .=-====*%@@@@+:..:===--+:
     . .-:.  .=%@%+=-+:...=+==
      .=:-.:=:.+#***+***+++**+.
      -.:++**+-#@%##%%####%##*-
     .=+**#%#-:-+=--+%%@@####+.
     .+*#%@@*...=+::+##%%#***-.
      -*##%@*=:-#*=-:--==##*+:.
      .=+#+-::--::-:.:.: :++=:.
       :++...::::---==++:---...
        :..=**+++-=*#%@%=:::..
         .:-*%@@@@@@@%#*. :::
:  .      .  -+**#*=-.
++-.                       .::
+*+=:                    .-===.
"""

# What the face gets on its left, so it lines up with the two-space indent the
# wordmark and every subtitle carry.
INDENT = "  "
# Columns between the face and the block beside it. The wordmark lines start
# with two spaces of their own, so the visible gap is wider than this.
GAP = 1


LOGO_LINES: tuple[str, ...] = tuple(LOGO.strip("\n").splitlines())
FACE_LINES: tuple[str, ...] = tuple(FACE.strip("\n").splitlines())

HEIGHT = len(FACE_LINES)
WIDTH = len(INDENT) + max(len(line) for line in FACE_LINES)


def _paint(lines: Sequence[str], colors: tui.Palette, indent: str = "") -> list[str]:
    return [f"{colors.bright_magenta}{indent}{line}{colors.reset}" for line in lines]


def wordmark(colors: tui.Palette) -> list[str]:
    """The block letters, coloured the way every screen prints them."""
    return _paint(LOGO_LINES, colors)


def compose(left: Sequence[str], right: Sequence[str], *, gap: int = GAP) -> list[str]:
    """Lay ``right`` beside ``left``, the shorter block centred on the taller."""
    left = list(left)
    right = list(right)
    left_width = max((tui.display_width(line) for line in left), default=0)
    height = max(len(left), len(right))
    left_top = (height - len(left)) // 2
    right_top = (height - len(right)) // 2

    rows = []
    for index in range(height):
        a = left[index - left_top] if 0 <= index - left_top < len(left) else ""
        b = right[index - right_top] if 0 <= index - right_top < len(right) else ""
        if b:
            a += " " * (left_width + gap - tui.display_width(a))
        rows.append((a + b).rstrip())
    return rows


def fits(right: Sequence[str], columns: int) -> bool:
    """Whether the face and ``right`` sit side by side in ``columns``."""
    right_width = max((tui.display_width(line) for line in right), default=0)
    return WIDTH + GAP + right_width <= columns


def banner(right: Sequence[str], *, colors: tui.Palette, columns: int | None = None) -> list[str]:
    """The face with ``right`` beside it, or ``right`` alone when it would not fit.

    ``right`` is normally the wordmark plus whatever a screen wants under it (a
    subtitle, the command count). It comes back untouched, indent and all, on a
    terminal too narrow for both, so every caller keeps working at 40 columns.
    The face is indented to line up with the wordmark and painted in its colour.
    """
    if columns is None:
        columns = tui.size()[0]
    if not fits(right, columns):
        return list(right)
    return compose(_paint(FACE_LINES, colors, INDENT), right)


def print_logo(subtitle: str = "") -> None:
    """The face beside the wordmark, with ``subtitle`` under the letters."""
    colors = tui.palette()
    right = wordmark(colors)
    if subtitle:
        right.append(f"  {colors.grey}{subtitle}{colors.reset}")
    for line in banner(right, colors=colors):
        print(line)
    print()
