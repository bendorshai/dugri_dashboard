from __future__ import annotations

"""
content/loader.py - Load .txt content files into a namespace object.

Reads all .txt files from a directory and returns a ContentNamespace where
each file becomes an uppercase attribute (e.g. greeting.txt -> ns.GREETING).

The .txt files use a simple markup convention described below.


FILE FORMAT
-----------
Each .txt file holds exactly one content item. The loader auto-detects which
of three shapes the content represents:

1. PLAIN STRING (default)
   The file content is returned as a Python str, as-is.
   Runtime placeholders like {name} or {calories:,} are preserved literally
   so that calling code can use .format() on them at runtime.

   Example file (onboarding_greeting.txt):

       היי, אני דוגרי
       הלב של מה שאני עושה הוא מודעות תזונתית.

2. LIST (variants separated by ---)
   If the file contains a line that is exactly "---" surrounded by newlines,
   the loader splits the content on those separators and returns a list[str].
   Each variant is stripped of surrounding whitespace.
   Use this for rotating prompt pools where code picks one with random.choice().

   Example file (hook_sleep_prompts.txt):

       בוקר. מתי נרדמת אתמול?
       ---
       היי, באיזו שעה הלכת לישון?
       ---
       מה היה אתמול בלילה, מתי נרדמת?

   -> Loaded as ["בוקר. מתי נרדמת אתמול?", "היי, באיזו שעה הלכת לישון?", ...]

3. DICT (sections with [key] headers)
   If the first non-blank line matches [some_key], the loader parses the file
   as a dictionary. Each [key] line starts a new entry; everything between
   one [key] and the next (or EOF) becomes the value. Leading newlines within
   a value are preserved (important for values that start with \n\n).

   Example file (loop_close_goal_set.txt):

       [sleep]

       מחר בבוקר אשאל אותך מתי הלכת לישון.
       [workouts]

       בימי חמישי אבדוק איתך מה היה עם האימונים.

   -> Loaded as {"sleep": "\n\nמחר בבוקר...", "workouts": "\n\nבימי חמישי..."}


INCLUDE DIRECTIVES
------------------
A file can inline the content of another file in the same directory using:

    {{include:other_file.txt}}

This is resolved at load time before format detection. Includes can be nested
(file A includes B which includes C), but circular includes raise RuntimeError.
A missing include target raises FileNotFoundError - the app will not start.

The double braces {{ }} are intentional to avoid collision with Python's
single-brace format placeholders like {name}.

Example (parse_message_system_prompt.txt):

    אתה מערכת ניתוח תזונתי...

    כללי מזון:
    {{include:food_quantity_rules.txt}}
    {{include:accuracy_rule.txt}}
    {{include:hebrew_rules.txt}}


FORMAT HINT (override auto-detection)
-------------------------------------
If a file's first line is exactly "# format: plain", "# format: list",
or "# format: dict", the loader uses that format instead of auto-detecting.
The hint line is stripped from the content.

This is needed when content happens to contain "---" or "[something]" that
would trigger false auto-detection. For example, a prompt that contains a
Markdown horizontal rule (---) needs "# format: plain" to avoid being
split into a list.
"""

import re
import logging
from pathlib import Path

_INCLUDE_RE = re.compile(r"\{\{include:(.+?)\}\}")
_DICT_KEY_RE = re.compile(r"^\[(.+)\]$")
_LIST_SEPARATOR = "\n---\n"
_FORMAT_HINT_RE = re.compile(r"^# format:\s*(plain|list|dict)\s*$")


class ContentNamespace:
    """Simple attribute holder for loaded content."""

    def __getattr__(self, name):
        raise AttributeError(
            f"Content item '{name}' not found. "
            f"Check that the corresponding .txt file exists."
        )


def load_content(directory: Path, logger: logging.Logger) -> ContentNamespace:
    """Load all .txt files from directory into a ContentNamespace.

    - Resolves {{include:filename}} directives
    - Auto-detects format: plain string, list (--- separated), dict ([key] sections)
    - First-line "# format: plain|list|dict" overrides auto-detection
    - Raises FileNotFoundError on missing includes
    - Raises RuntimeError on circular includes
    """
    logger.info("Loading content from %s...", directory)

    raw_contents = {}
    for path in sorted(directory.glob("*.txt")):
        raw_contents[path.name] = path.read_text(encoding="utf-8")

    resolved = {}
    for filename, content in raw_contents.items():
        resolved[filename] = _resolve_includes(
            filename, content, raw_contents, set(), directory
        )

    ns = ContentNamespace()
    for filename, content in resolved.items():
        attr_name = Path(filename).stem.upper()
        value = _detect_and_parse(content)
        setattr(ns, attr_name, value)

    logger.info("Loaded %d content items from %s", len(resolved), directory)
    return ns


def _resolve_includes(
    filename: str,
    content: str,
    all_raw: dict[str, str],
    seen: set[str],
    directory: Path,
) -> str:
    if filename in seen:
        raise RuntimeError(
            f"Circular include detected: {filename} "
            f"(chain: {' -> '.join(seen)} -> {filename})"
        )
    seen = seen | {filename}

    def replace_include(match):
        ref = match.group(1)
        if ref not in all_raw:
            raise FileNotFoundError(
                f"Include file '{ref}' not found "
                f"(referenced by '{filename}' in {directory})"
            )
        return _resolve_includes(ref, all_raw[ref], all_raw, seen, directory)

    return _INCLUDE_RE.sub(replace_include, content)


def _detect_and_parse(content: str) -> str | list[str] | dict[str, str]:
    forced_format, body = _extract_format_hint(content)

    if forced_format == "list":
        return _parse_list(body)
    if forced_format == "dict":
        return _parse_dict(body)
    if forced_format == "plain":
        return body

    # Auto-detect
    if _LIST_SEPARATOR in body or body.startswith("---\n") or body.endswith("\n---"):
        return _parse_list(body)

    lines = body.split("\n")
    first_non_blank = next((line for line in lines if line.strip()), "")
    if _DICT_KEY_RE.match(first_non_blank):
        return _parse_dict(body)

    return body


def _extract_format_hint(content: str) -> tuple[str | None, str]:
    first_newline = content.find("\n")
    if first_newline < 0:
        return None, content
    first_line = content[:first_newline]
    m = _FORMAT_HINT_RE.match(first_line)
    if m:
        return m.group(1), content[first_newline + 1:]
    return None, content


def _parse_list(content: str) -> list[str]:
    parts = content.split("---")
    return [p.strip() for p in parts if p.strip()]


def _parse_dict(content: str) -> dict[str, str]:
    result = {}
    current_key = None
    current_lines = []

    for line in content.split("\n"):
        m = _DICT_KEY_RE.match(line)
        if m:
            if current_key is not None:
                result[current_key] = _join_dict_value(current_lines)
            current_key = m.group(1)
            current_lines = []
        else:
            current_lines.append(line)

    if current_key is not None:
        result[current_key] = _join_dict_value(current_lines)

    return result


def _join_dict_value(lines: list[str]) -> str:
    value = "\n".join(lines)
    return value.rstrip("\n")
