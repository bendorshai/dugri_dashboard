# Skill: Heavy Classifier Prompt Restructuring

Use this skill when the classifier prompt needs significant restructuring - not just adding a rule, but reorganizing sections, reordering directives, or fixing systemic misclassification patterns.

## When to use

- Multiple related classification failures that share a root cause
- Failures where the correct rule EXISTS in the prompt but the LLM doesn't follow it
- The LLM matches words literally instead of reading context
- Adding more rules/examples isn't fixing the problem

## Core insight: Structure > Content

The classifier prompt can have every correct rule and still fail if the rules are in the wrong order. GPT-4o-mini reads sequentially and anchors on early patterns. A rule at line 15 has far more weight than the same rule at line 75.

**The #1 failure pattern:** type definitions listed before routing rules. The LLM reads "correction = changing quantity" and matches "170 גרם חלבון" literally, never reaching the toggle-state override 40 lines later that says "during active_goal_pending, numbers are conversation_reply."

## The decision framework approach

Instead of teaching the LLM WHAT types exist, teach it HOW to decide. Open the prompt with the decision procedure:

```
סדר החשיבה שלך (חובה לפני כל סיווג):
1. בדוק את מצב ההרגלים (toggle state) - האם יש הרגל בתהליך?
2. קרא את ההיסטוריה - מה הבוט שאל אחרון?
3. רק אחרי שהבנת את ההקשר - סווג את ההודעה.
```

This forces the LLM to check context before pattern-matching.

## Prompt section order (proven effective)

1. **Identity** (1 line)
2. **Decision framework** - the 3-step thinking procedure
3. **Core principle** - "context overrides words, same message = different type depending on state"
4. **Toggle state routing rules** (the PRIMARY router) - what to do for each state
5. **Cultural context** - Hebrew slang interpretation
6. **Type definitions** - with inline guards referencing the routing rules
7. **Multi-entry / domain-specific rules**
8. **Included sub-prompts** (food rules, temporal rules, etc.)

The key structural move: toggle state routing rules BEFORE type definitions. The LLM internalizes "active_goal_pending = almost everything is conversation_reply" before it ever reads what "correction" or "sleep" means.

## "Why" reasoning: powerful but dangerous

Adding reasoning ("למה? כי...") to rules helps the LLM generalize to edge cases. But for GPT-4o-mini:

### What works
- **One-line reasons inline with the rule:**
  ```
  הצעת מספר חלופי היא התאמה, לא סירוב - המשתמש מנהל משא-ומתן, לא יוצא מהתהליך.
  ```
- **Disambiguating confusing terms:**
  ```
  חשוב: 'לא משנה' = "אתה תחליט", לא "לא מעניין אותי". זה שיתוף פעולה.
  ```
- **Explaining WHY a type guard exists:**
  ```
  חשוב: אם sleep במצב active_goal_pending, שעה היא conversation_reply (יעד), לא דיווח שינה.
  ```

### What fails catastrophically
- **Multi-line "why" blocks** - first attempt added paragraph-length explanations to every rule. GPT-4o-mini went from 5 failures to 11. The model lost focus in the verbosity.
- **"Why" without concrete examples** - abstract reasoning confuses the model. Always pair reasoning with a concrete case.
- **Separated explanations** - putting the "why" in a different section from the rule it explains. Keep them adjacent.

### The calibration lesson (session 2026-06-07)
- Attempt 1: Heavy "why" on every rule -> 5 failures became 11 (massive regression)
- Attempt 2: Concise "why" only on ambiguous rules, kept word lists inline -> 3 failures
- Attempt 3: Targeted fixes for remaining 3 -> 0 failures

## Keep word lists where they're used

**Wrong:** Define affirmative words in a "Cultural Context" section, then reference "תשובה חיובית קצרה" in the toggle rules. The LLM doesn't connect them.

**Right:** List the words inline where the routing decision happens:
```
כשהרגל במצב offered:
  הודעות חיוביות קצרות ('יאללה', 'סבבה', 'כן', 'אוקיי', 'בוא', 'קדימה',
  'בטח', 'זורם', 'נו בסדר', 'למה לא', 'אחלה', 'עושים', 'טוב') = conversation_reply.
```

Duplication between sections is OK if it prevents the LLM from missing a connection.

## Inline type guards

Every type definition that can be confused with a flow response needs an inline guard:

```
6. "correction" - תיקון לרשומה האחרונה.
   חשוב: אם הרגל במצב active_goal_pending, מספרים הם conversation_reply, לא correction.

7. "sleep" - דיווח שעת שינה.
   חשוב: אם sleep במצב active_goal_pending, שעה היא conversation_reply, לא דיווח שינה.
```

This creates a double-check: the routing rules say it first, and the type definition repeats it.

## Common misclassification patterns and fixes

### "Negotiation = refusal" bug
**Symptom:** User adjusts numbers from a suggestion ("אני מעדיף 2000 קלוריות") -> classified as toggle_cancel instead of conversation_reply.
**Root cause:** LLM reads "מעדיף" (prefer) as disagreement.
**Fix:** Explicit negotiation pattern in the active_goal_pending section with reasoning that counter-offering = engagement, not rejection.

### "Literal type match over context" bug
**Symptom:** "23 בלילה" during sleep goal setting -> classified as sleep log instead of conversation_reply (goal value).
**Root cause:** LLM matches the literal sleep pattern before checking toggle state.
**Fix:** Toggle state rules before type definitions + inline guard on the sleep type.

### "Ambiguous short word = unrelated" bug
**Symptom:** "טוב", "לא משנה", "אממ" during active flow -> classified as unrelated.
**Root cause:** Words that can standalone are treated as meaningless without sufficient context anchoring.
**Fix:** (1) List these words explicitly in the toggle state rules, (2) Add disambiguation ("'לא משנה' = 'אתה תחליט', לא 'לא מעניין אותי'"), (3) Repeat in the unrelated definition that these are NEVER unrelated during active flow.

### "Back-reference dropped" bug
**Symptom:** "שלשום גם בדיוק אותו דבר" not counted as a separate habit_entry.
**Root cause:** The LLM doesn't resolve anaphora ("same thing") as a concrete entry.
**Fix:** Dedicated back-reference section with explicit examples showing input -> output mapping, and the rule "count each reference as a separate entry."

## Testing procedure

1. Run baseline: `python -m pytest tests/test_lazy_optin_llm.py -n 2 --tb=short`
2. Make structural changes to `content/prompts/classifier_system_prompt.txt`
3. Run full suite again - watch for REGRESSIONS, not just target fixes
4. If regressions appear, diagnose the pattern before adding more rules
5. Targeted fixes for remaining failures
6. Run twice to confirm stability (LLM variance)
7. Also run `python -m pytest tests/test_retroactive.py -v --tb=short`

### "Prompt length kills edge-case accuracy" (session 2026-06-16)
**Symptom:** GPT-4o-mini ignores explicit examples for a specific edge case (log confirmation vs goal offer), no matter where the examples are placed in the prompt. The same examples work perfectly with a ~400 char prompt but fail at ~3800+ chars.
**Root cause:** GPT-4o-mini has limited attention for structured output classification. As prompt length grows, the model's ability to follow fine-grained examples degrades. Tested systematically:
- Ultra-minimal prompt (~400 chars): correct classification
- Medium prompt (~800 chars): wrong classification
- Full prompt with food extraction rules (~5000 chars): consistently wrong
- Same full prompt with GPT-4o: correct classification
**Key finding:** It's not about WHERE in the prompt the examples are - it's about total prompt length. The food extraction rules (~1500 chars of quantity/accuracy/hebrew/temporal rules) added enough volume to push the model past its attention threshold, even though the rules are clearly labeled "for meal only" and placed at the end.
**Implication for tiered routing:** Classification and inline extraction should use separate prompts. Combining "classify into 4 types" with "extract food data for meals" in one prompt degrades classification accuracy on edge cases. The tier 1 router should classify only; meal extraction should be a separate call.

### "Type names shape classification" (session 2026-06-16)
Renaming `opt_in` to `goals_talk` and `logger` to `habit_logger` improved accuracy because the LLM uses the type name as semantic signal. `opt_in` is an internal implementation term; `goals_talk` tells the LLM what the category means. Similarly, `logger` is generic; `habit_logger` clarifies it's about habits, not logging in general.

### "Domain framing prevents cross-contamination" (session 2026-06-16)
Adding "each habit has a logging aspect AND a goals aspect" before the categories prevented the LLM from conflating workout-related words with goals_talk. Without this framing, "אימון" in a user message triggered goals_talk because the goals_talk definition mentioned workouts. The framing taught the LLM that the SAME word can belong to different categories depending on context.

### "Same-habit multi-date vs multi-intent" (session 2026-06-16)
"Sleep at 22 yesterday, 21 day before" = same habit, multiple dates = habit_logger. "Hamburger + sleep at 23" = different habit types = multi-intent = other. LLMs can't infer this distinction without explicit examples of both patterns side by side.

## Anti-patterns (things that made it worse)

1. **Over-abstracting word lists** - replacing inline examples with "תשובה חיובית קצרה" lost the LLM
2. **Verbose reasoning blocks** - GPT-4o-mini gets confused by long explanations, loses the actual rule
3. **Removing the "important distinctions" examples section** - concrete routing examples (answer_question vs feedback_request vs toggle_activate) anchor the LLM's understanding of boundary cases
4. **Moving cultural context too far from toggle rules** - the LLM needs to know "למה לא = yes" right before it routes an offered toggle response
5. **Removing redundancy for "cleanliness"** - saying the same rule in both the routing section AND the type definition is intentional double-checking, not duplication

## Files

- Classifier prompt: `content/prompts/classifier_system_prompt.txt`
- Test suite: `tests/test_lazy_optin_llm.py` (source of truth spec in lines 12-400)
- Included sub-prompts: `content/prompts/food_quantity_rules.txt`, `accuracy_rule.txt`, `hebrew_rules.txt`, `temporal_extraction_rules.txt`
- Prompt assembly: `analyzer.py`, method `classify_message()` (~line 210)
- See also: `skills/llm-model-changing.md` for model evaluation and prompt ORDER (rules-first vs context-first)
