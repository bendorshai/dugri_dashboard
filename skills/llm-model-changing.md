# Skill: LLM Classifier Model Evaluation

Use this skill when comparing or switching the LLM model used for the classifier/router.

## Architecture

- The classifier is in `analyzer.py`, method `classify_message()` (~line 248)
- Model is set as a string literal: `model="gpt-4o-mini"` in the `client.beta.chat.completions.parse()` call
- It uses OpenAI structured output (`response_format=MessageClassification`)
- The prompt is assembled in `classify_message()` from several parts: history, toggle state, `CLASSIFIER_SYSTEM_PROMPT` (in `prompts.py`), date, and last entry
- The `MessageClassification` Pydantic model (~line 94 in `analyzer.py`) defines the output schema with 13 types

## Test suite

- **File:** `tests/test_lazy_optin_llm.py` (~76 integration tests)
- These are **live API tests** - they call the actual OpenAI API, no mocks
- They cost real money and take ~5-10 minutes for the full suite
- API key is loaded from `config/config.json` under `openai.api_key`
- Tests are organized by feature: NutritionOffer, BodyStats, WeightGoal, Confirm, Sleep, EatingWindow, Workouts, SelfCare, GoalRemind, ToggleCancel, NoneIsRare, GoalShortcut, MultiEntryHabits, NameDeclaration, UncertaintyDuringGoal, RefusalTone, NoneDuringActiveFlow

## Evaluation procedure

### Step 1: Baseline
Run the full suite with the current model and record pass/fail count:
```
cd health_tracker && python -m pytest tests/test_lazy_optin_llm.py -vs
```

### Step 2: Swap model
Change ONLY the model string in `analyzer.py:~248`. Do not change anything else - no prompt changes, no max_tokens, no temperature changes. The point is to test the model against the existing prompt.

### Step 3: Run failing tests first
If you have a specific case to test (like a new TDD test), run it first:
```
python -m pytest tests/test_lazy_optin_llm.py::TestClass::test_name -xvs
```

### Step 4: Run full suite
```
python -m pytest tests/test_lazy_optin_llm.py -vs
```
This takes 5-10 minutes. Use `run_in_background` and read the output file when done.

### Step 5: Analyze failures
For each failure, classify it as:
- **API/network error** - `LengthFinishReasonError`, `ConnectError`, timeouts. These are infrastructure issues, not model issues. Re-run to confirm.
- **Classification regression** - model returns wrong type. This is a real model capability difference.
- **Structured output issue** - model generates valid JSON but wrong values (e.g., wrong sleep_time, missing habit_entries). This is a parsing/extraction difference.

### Step 6: Report to user before making any changes
Present findings as a comparison table. **Never relax test assertions to accommodate a new model.** If the new model fails tests, those are real regressions that must be solved or accepted as blockers.

## What we learned (2026-06-06)

### gpt-4o-mini (current, baseline)
- 76/76 tests pass after prompt hardening (v5.1.0)
- Stable, predictable output sizes, no runaway generation
- Cost: $0.15/$0.60 per 1M tokens
- Weakness: short ambiguous Hebrew words can be misclassified; fixed via explicit examples in the none definition and options-matching rule
- Fix approach: targeted prompt additions, not model swap or structural changes

### gpt-4.1-mini (tested, rejected)
- 72/76 tests pass (4 failures, 3 new regressions)
- **Critical issue:** runaway token generation - produced 32,768 completion tokens for a simple sleep classification. The `client.beta.chat.completions.parse()` call has no default max_tokens, and gpt-4.1-mini can generate excessive output before producing the structured JSON. This caused `LengthFinishReasonError` which the exception handler caught as `type="none"`.
- Needed `max_tokens=2048` guard that gpt-4o-mini never needed
- Multi-entry anaphora resolution worse ("אותו דבר" not expanded to second entry)
- Misrouted "למה חלבון?" (help -> answer_question) - different boundary between conceptual questions and data questions
- Cost: $0.40/$1.60 per 1M tokens (~2.7x more expensive)
- Better at instruction following for direct context matching (the "לרדת" case passed immediately)

### Key insights
1. **Newer != better for classification.** gpt-4.1-mini is a reasoning model that over-thinks classification tasks. gpt-4o-mini is better suited for fast pattern matching.
2. **Always test the full suite before committing.** Single-test success is misleading.
3. **gpt-4o-mini needs rules BEFORE context.** Context-first order (history before rules) was tested and caused 6 failures (vs 1 in baseline). The model applies rules more reliably when it reads them before the conversation. Reverted.
4. **Watch for runaway generation** with newer models. Always check completion_tokens in failure logs. If a classification call uses >1000 tokens, something is wrong.
5. **gpt-4.1-nano** ($0.10/$0.40) was considered but not tested. It's cheaper than gpt-4o-mini but likely weaker for Hebrew context. Could be worth testing if cost becomes a concern.
6. **When switching models, test prompt order preference.** Different model families may have different attention patterns - some work better with rules-first, others with context-first. Always test both orders with the full suite.

## Prompt structure (gpt-4o-mini)

**Rules first, history last (adjacent to user message).** Tested empirically 2026-06-06.

The current working order:
```
1. Reply context (if user swiped-replied to a specific message)
2. Toggle state (which habits are active/offered/pending)
3. CLASSIFIER_SYSTEM_PROMPT (role + cultural context + all rules)
4. Date (for temporal resolution)
5. Last entry (for correction context)
6. Conversation history (right before user message - keeps conversation flow tight)
```

History at the END is critical - the model reads the bot's last question and immediately sees the user's answer. The rules are already internalized by then.

## Maintaining this skill

After every model evaluation session, update this file with new findings - models tested, pass/fail results, prompt order experiments, and any new insights. This skill is a living document. Future sessions should read it before starting and write back to it when done, so knowledge accumulates across conversations.

## Cost estimation formula

Per classification call (~2,500 input tokens, ~100 output tokens):
```
cost = (2500 * input_price_per_M / 1_000_000) + (100 * output_price_per_M / 1_000_000)
monthly = cost * messages_per_day * 30
```

For gpt-4o-mini: ~$0.0004/call, ~$12/month at 1K msgs/day.
