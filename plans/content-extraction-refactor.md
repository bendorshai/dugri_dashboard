# Plan: Extract Hebrew Content to .txt Files

## Context

`messages.py` (~485 lines) and `prompts.py` (~461 lines) contain all Hebrew text the bot uses - user-facing messages and GPT system prompts. Editing them requires navigating Python string syntax mixed with Hebrew RTL text. This refactor extracts each message/prompt into its own `.txt` file so content can be edited directly without touching code.

## Directory Structure

```
health_tracker/content/
  __init__.py              # empty package marker
  loader.py                # ContentLoader - reads .txt files into namespace
  messages/                # one .txt per message variable
    onboarding_greeting.txt
    onboarding_name_response.txt     # has {name} placeholder
    hook_sleep_prompts.txt           # list: 5 variants separated by ---
    loop_close_goal_set.txt          # dict: [key] section headers
    edu_intro_first_log.txt          # dict: from dugri_messages.py
    edu_why_kernel.txt               # dict: from dugri_messages.py
    ...                              # ~57 files total
  prompts/                 # one .txt per prompt variable
    food_quantity_rules.txt          # building block (included by others)
    hebrew_rules.txt                 # building block
    accuracy_rule.txt                # building block
    temporal_extraction_rules.txt    # building block
    parse_message_system_prompt.txt  # uses {{include:food_quantity_rules.txt}} etc.
    classifier_system_prompt.txt     # uses {{include:...}}
    ...                              # ~20 files total
```

Filenames are lowercase of the Python variable name + `.txt`. Each file contains a single content item.

## Three Content Formats

### 1. Plain string (most files)
File contains the text as-is. Runtime placeholders like `{name}`, `{calories:,}` stay in the file for `.format()` at runtime.

### 2. List - variants separated by `---`
```
בוקר. מתי נרדמת אתמול?
---
היי, באיזו שעה הלכת לישון?
---
מה היה אתמול בלילה, מתי נרדמת?
```
Loader splits on `---`, strips each variant, returns `list[str]`.

### 3. Dict - `[key]` section headers
```
[sleep]

מחר בבוקר אשאל אותך מתי הלכת לישון. ככה נעקוב ביחד.
[workouts]

בימי חמישי אבדוק איתך מה היה עם האימונים השבוע.
```
Loader parses into `dict[str, str]`. Content between `[key]\n` and next `[key]` (or EOF) is the value. The leading `\n\n` before text is preserved as-is (blank lines after `[key]` become the `\n\n` prefix that current code expects).

## Nesting Solution: `{{include:filename}}`

For prompts that compose building blocks, the `.txt` file uses `{{include:filename}}` directives:

```
אתה מערכת ניתוח תזונתי...

כללי מזון:
{{include:food_quantity_rules.txt}}
{{include:accuracy_rule.txt}}
{{include:hebrew_rules.txt}}
```

- The loader resolves includes by replacing the directive with the referenced file's content from the same directory.
- Two-pass: first read all files raw, then resolve includes.
- Recursive resolution (included files can themselves have includes).
- Circular include detection via a "seen" set - raises fatal error.
- Double braces (`{{...}}`) don't conflict with single-brace runtime placeholders (`{name}`).

## Loader Design: `content/loader.py`

**`ContentNamespace`** - simple object holding attributes via `setattr()`. Supports `ns.VARIABLE_NAME` access.

**`load_content(directory: Path, logger: Logger) -> ContentNamespace`**:
1. Log `"Loading content from {directory}..."`
2. Read all `.txt` files into a `{filename: raw_content}` dict
3. Resolve `{{include:...}}` directives (two-pass, recursive, cycle detection)
4. Detect format per file:
   - Contains `\n---\n` (or starts/ends with `---`) -> split into list, strip each variant
   - First non-blank line matches `[key]` pattern -> parse as dict, preserve internal whitespace
   - Otherwise -> plain string, strip outer whitespace
5. Convert filename to attribute: `onboarding_greeting.txt` -> `ONBOARDING_GREETING`
6. Log `"Loaded {count} content items from {directory}"`

## Fatal Error on Missing Files

The loader is **all-or-nothing**. If any `.txt` file referenced by `{{include:...}}` is missing, the loader raises a fatal error and the bot does not start. Specifically:
- Missing include target -> `FileNotFoundError` with clear message naming the missing file and which file referenced it
- This happens at module import time (startup), so the bot crashes immediately with a clear log

## Backward Compatibility

`messages.py` and `prompts.py` become thin wrappers:

```python
import logging
from pathlib import Path
from content.loader import load_content

_logger = logging.getLogger(__name__)
_ns = load_content(Path(__file__).parent / "content" / "messages", _logger)
globals().update(vars(_ns))
```

All consuming code (`import messages as M; M.ONBOARDING_GREETING`, `from prompts import CLASSIFIER_SYSTEM_PROMPT`) continues to work unchanged.

## `dugri_messages.py` - Merge Into Messages

`dugri_messages.py` contains 2 dicts of Hebrew education text, both in use:
- `EDU_INTRO_FIRST_LOG` - one-time "whisper" per habit (used in `handlers/base.py` lines 138, 781)
- `EDU_WHY_KERNEL` - short "why" per habit (used in `tests/test_education.py`)

These become `content/messages/edu_intro_first_log.txt` and `content/messages/edu_why_kernel.txt` (dict format with `[key]` headers). `dugri_messages.py` becomes a thin wrapper that re-exports from `messages.py`, so existing `from dugri_messages import ...` continues to work. Eventually the imports can be updated to point directly at `messages`.

## Files to Modify

- `health_tracker/messages.py` - replace body with loader call
- `health_tracker/prompts.py` - replace body with loader call
- `health_tracker/dugri_messages.py` - replace body with re-export from messages

## Files to Create

- `health_tracker/content/__init__.py` - empty
- `health_tracker/content/loader.py` - the loader
- `health_tracker/content/messages/*.txt` - ~57 message files (including edu_intro_first_log, edu_why_kernel)
- `health_tracker/content/prompts/*.txt` - ~20 prompt files
- `health_tracker/tests/test_content_loader.py` - loader unit tests

## Implementation Steps

### Step 1: TDD - Write loader tests
Create `tests/test_content_loader.py` with tests for:
- Plain string loading
- Placeholders survive loading (`{name}` works with `.format()`)
- List format (split on `---`, correct count)
- Dict format (parse `[key]` headers, preserve `\n\n` prefix)
- Include resolution (single level, nested)
- Circular include detection (raises fatal error)
- Missing include file (raises fatal error with clear message naming missing file and referrer)
- Filename-to-attribute conversion
- UTF-8 Hebrew round-trip

### Step 2: Implement loader
Create `content/__init__.py` and `content/loader.py`. Get all tests green.

### Step 3: Extract messages to .txt files
Mechanically extract each variable from `messages.py` and `dugri_messages.py` into `content/messages/`. Convert both to thin wrappers.

### Step 4: Verify messages backward compat
Run existing `tests/test_messages.py` and `tests/test_education.py` - must pass unchanged. Run full test suite.

### Step 5: Extract prompts to .txt files
Extract building blocks first, then composed prompts with `{{include:...}}` directives. Convert `prompts.py` to thin wrapper.

### Step 6: Verify prompts backward compat
Write snapshot comparison tests: for each prompt, compare loaded value against hardcoded original. Run full test suite.

### Step 7: Cleanup
Remove snapshot tests (migration scaffolding). Final full test run.

## Verification

1. All existing tests pass unchanged (especially `test_messages.py`, `test_education.py`)
2. Loader logs appear at startup: "Loading content..." and "Loaded N items..."
3. Manually verify a few .txt files contain correct Hebrew content
4. Verify `{{include:...}}` produces identical prompt strings by comparing old vs new
5. Run full test suite: `cd health_tracker && python -m pytest tests/`
