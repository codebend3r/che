"""Unit tests for bin/utils.py.

The shared library had no test coverage as ``utils.sh``, and every defect the
migration review found in it was in one of these four areas: byte formatting,
size parsing, boolean-flag parsing, and file walking.
"""

from __future__ import annotations

import os

import pytest
from utils import (
    add_bool_flag,
    build_parser,
    format_bytes,
    iter_files,
    normalize_extensions,
    parse_bool,
    parse_size,
)

# ---------------------------------------------------------------------------
# format_bytes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0, "0 B"),
        (1, "1 B"),
        (1023, "1023 B"),
        (1024, "1.00 KB"),
        (1536, "1.50 KB"),
        # bc's scale=2 TRUNCATES. 2043 bytes is 1.99512... KB, so it must
        # render 1.99, not the 2.00 that rounding would give.
        (2043, "1.99 KB"),
        (1048575, "1023.99 KB"),
        (1048576, "1.00 MB"),
        (1073741824, "1.00 GB"),
        (1099511627776, "1.00 TB"),
        (1125899906842624, "1.00 PB"),
        (-5, "-5 B"),
    ],
)
def test_format_bytes(value, expected):
    assert format_bytes(value) == expected


def test_format_bytes_truncates_at_every_magnitude():
    """Integer maths, so the truncation holds where Decimal's default context
    would have rounded first."""
    assert format_bytes(10**14 * 2**50 - 1) == "99999999999999.99 PB"


# ---------------------------------------------------------------------------
# parse_size
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("0", 0),
        ("100", 100),
        ("100b", 100),
        ("1k", 1024),
        ("1kb", 1024),
        ("1KiB", 1024),
        ("1MB", 1048576),
        ("2 GiB", 2147483648),
        ("  10 mb  ", 10485760),
        # A leading zero is decimal here; the shell version's $(( )) read it
        # as octal and silently returned a different number.
        ("010mb", 10485760),
    ],
)
def test_parse_size(text, expected):
    assert parse_size(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "",
        "MB",
        "10xb",
        "1.5MB",
        "-5mb",
        "+5mb",
        # Terabytes were rejected by the shell version. Accepting them would
        # make `--size=1t` on files-under-size delete an entire library where
        # it used to be a safe hard error.
        "1t",
        "1tb",
        "1TiB",
        "\u0661\u0660mb",  # Arabic-Indic digits: str.isdigit() accepts these
    ],
)
def test_parse_size_rejects(text):
    with pytest.raises(ValueError):
        parse_size(text)


# ---------------------------------------------------------------------------
# parse_bool
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text", ["true", "TRUE", "yes", "1", "on", " True "])
def test_parse_bool_true(text):
    assert parse_bool(text) is True


@pytest.mark.parametrize("text", ["false", "FALSE", "no", "0", "off"])
def test_parse_bool_false(text):
    assert parse_bool(text) is False


@pytest.mark.parametrize("text", ["ture", "", "maybe", "2"])
def test_parse_bool_rejects(text):
    with pytest.raises(ValueError):
        parse_bool(text)


# ---------------------------------------------------------------------------
# add_bool_flag
# ---------------------------------------------------------------------------


def make_parser(**kwargs):
    parser = build_parser("t", "t")
    add_bool_flag(parser, "--dry-run", **kwargs)
    return parser


def test_bare_flag_enables():
    assert make_parser().parse_args(["--dry-run"]).dry_run is True


def test_equals_form_both_ways():
    assert make_parser().parse_args(["--dry-run=false"]).dry_run is False
    assert make_parser().parse_args(["--dry-run=true"]).dry_run is True


def test_default_is_respected():
    assert make_parser(default=True).parse_args([]).dry_run is True
    assert make_parser(default=False).parse_args([]).dry_run is False


def test_last_flag_wins():
    parser = make_parser()
    assert parser.parse_args(["--dry-run", "--dry-run=false"]).dry_run is False
    parser = make_parser()
    assert parser.parse_args(["--dry-run=false", "--dry-run"]).dry_run is True


def test_bare_flag_does_not_swallow_the_next_token():
    """`nargs="?"` would read the next argument as the flag's value.

    `--dry-run 0` would then mean dry_run=False and delete for real, which the
    shell scripts' argv loop could never do.
    """
    parser = build_parser("t", "t")
    add_bool_flag(parser, "--dry-run", default=True)
    parser.add_argument("rest", nargs="*")

    args = parser.parse_args(["--dry-run", "0", "1"])

    assert args.dry_run is True
    assert args.rest == ["0", "1"]


def test_invalid_value_exits_nonzero():
    with pytest.raises(SystemExit) as excinfo:
        make_parser().parse_args(["--dry-run=ture"])
    assert excinfo.value.code != 0


def test_allow_value_false_rejects_the_equals_form():
    """`--no-force=false` is a double negative; it must not silently mean force."""
    parser = build_parser("t", "t")
    add_bool_flag(parser, "--no-force", dest="no_force", allow_value=False)

    assert parser.parse_args(["--no-force"]).no_force is True
    with pytest.raises(SystemExit):
        parser.parse_args(["--no-force=false"])


def test_abbreviations_are_rejected():
    """argparse accepts `--dry` for `--dry-run` unless allow_abbrev is off."""
    with pytest.raises(SystemExit):
        make_parser().parse_args(["--dry"])


# ---------------------------------------------------------------------------
# normalize_extensions
# ---------------------------------------------------------------------------


def test_normalize_extensions_preserves_globs():
    assert normalize_extensions("mp*, jpg ,png") == ["mp*", "jpg", "png"]


def test_normalize_extensions_rejects_leading_dot():
    with pytest.raises(SystemExit):
        normalize_extensions(".jpg")


# ---------------------------------------------------------------------------
# iter_files
# ---------------------------------------------------------------------------


def test_iter_files_matches_iname_semantics(tmp_path):
    """`find -iname '*.mkv'` matches a file named exactly `.mkv`."""
    (tmp_path / ".mkv").touch()
    (tmp_path / "a.MKV").touch()
    (tmp_path / "b.mkv").touch()
    (tmp_path / "c.txt").touch()

    found = {p.name for p in iter_files(tmp_path, extensions=["mkv"])}

    assert found == {".mkv", "a.MKV", "b.mkv"}


def test_iter_files_supports_glob_extensions(tmp_path):
    for name in ("a.mp4", "b.mp3", "c.txt"):
        (tmp_path / name).touch()

    found = {p.name for p in iter_files(tmp_path, extensions=["mp*"])}

    assert found == {"a.mp4", "b.mp3"}


def test_iter_files_skips_macos_sidecars_by_default(tmp_path):
    (tmp_path / "._a.mkv").touch()
    (tmp_path / "a.mkv").touch()

    assert {p.name for p in iter_files(tmp_path, extensions=["mkv"])} == {"a.mkv"}

    both = iter_files(tmp_path, extensions=["mkv"], skip_macos_metadata=False)
    assert {p.name for p in both} == {"._a.mkv", "a.mkv"}


def test_iter_files_skips_symlinked_files(tmp_path):
    """`find -type f` does not match a symlink."""
    (tmp_path / "real.mkv").touch()
    (tmp_path / "link.mkv").symlink_to(tmp_path / "real.mkv")

    assert {p.name for p in iter_files(tmp_path, extensions=["mkv"])} == {"real.mkv"}


def test_iter_files_does_not_follow_symlinked_directories(tmp_path):
    """`find` without -L stays inside the tree; a loop must not hang the walk."""
    inner = tmp_path / "inner"
    inner.mkdir()
    (inner / "a.mkv").touch()
    (tmp_path / "loop").symlink_to(tmp_path, target_is_directory=True)

    found = {p.name for p in iter_files(tmp_path, extensions=["mkv"])}

    assert found == {"a.mkv"}


def test_iter_files_non_recursive_stays_at_top_level(tmp_path):
    (tmp_path / "top.mkv").touch()
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "deep.mkv").touch()

    found = {p.name for p in iter_files(tmp_path, extensions=["mkv"], recursive=False)}

    assert found == {"top.mkv"}


def test_iter_files_skip_hidden(tmp_path):
    (tmp_path / ".secret").mkdir()
    (tmp_path / ".secret" / "a.mkv").touch()
    (tmp_path / ".hidden.mkv").touch()
    (tmp_path / "visible.mkv").touch()

    found = {p.name for p in iter_files(tmp_path, extensions=["mkv"], skip_hidden=True)}

    assert found == {"visible.mkv"}


def test_iter_files_raises_on_missing_root(tmp_path):
    """`find` errored on a missing path; yielding nothing would make a typo
    look like a clean library."""
    with pytest.raises(FileNotFoundError):
        list(iter_files(tmp_path / "nope", extensions=["mkv"]))


def test_iter_files_streams(tmp_path):
    """The first result must arrive before the whole tree has been walked."""
    for index in range(200):
        directory = tmp_path / f"d{index:03d}"
        directory.mkdir()
        (directory / "a.mkv").touch()

    walker = iter_files(tmp_path, extensions=["mkv"])
    first = next(walker)

    assert first.name == "a.mkv"


def test_iter_files_case_sensitive_matching(tmp_path):
    """A few scripts used `-name`, not `-iname`, and must stay case-sensitive."""
    (tmp_path / "a.mkv").touch()
    (tmp_path / "B.MKV").touch()

    insensitive = {p.name for p in iter_files(tmp_path, extensions=["mkv"])}
    sensitive = {p.name for p in iter_files(tmp_path, extensions=["mkv"], case_sensitive=True)}

    assert insensitive == {"a.mkv", "B.MKV"}
    assert sensitive == {"a.mkv"}


def test_iter_files_yields_only_regular_files(tmp_path):
    """`find -type f` excluded FIFOs; opening one to hash it blocks forever."""
    (tmp_path / "real.mkv").touch()
    os.mkfifo(tmp_path / "pipe.mkv")

    assert {p.name for p in iter_files(tmp_path, extensions=["mkv"])} == {"real.mkv"}
