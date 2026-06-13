# Re-Engagement System - Implementation Plan

## Context

Users who stop logging food or stop communicating entirely get no attention from Dugri today. This feature adds two re-engagement pipelines:

- **Pipeline A (Food Nudge)**: User is active (logs sleep/workouts, sends messages) but not logging food. Gets a daily morning nudge ("didn't you eat yesterday?", roating between 5 alternatives randomly) that blocks sleep questions until answered. Resets when food is logged.
- **Pipeline B (Complete Silence)**: User stops communicating entirely. 3-day escalation (nudge -> smart question -> context message), then total silence from bot. Resets when user sends any message.

Pipeline B overrides A. During B (days 1-3), only weekly feedback continues (and future feature wisdom gems, document it in TDD). After day 3, nothing at all.

---

## 1. New Model Fields (`models/profile.py`)

Add 3 flat fields to `User`:

```python
last_user_message_at: datetime | None = None
re_engagement_stage: Literal["none", "food_nudge_pending", "silence_day1", "silence_day2", "silence_day3", "silenced"] = "none"
re_engagement_last_sent_at: datetime | None = None
```

Add backward-compat handling in `from_mongo_dict()` - existing users default to `"none"` stage.

### State Machine

```
"none" ---(no food yesterday, user active)---> "food_nudge_pending"
"none" ---(1 day silence)---> "silence_day1"
"food_nudge_pending" ---(food logged)---> "none"
"food_nudge_pending" ---(1 day silence)---> "silence_day1"
"silence_day1" ---(+1 day)---> "silence_day2"
"silence_day2" ---(+1 day)---> "silence_day3"
"silence_day3" ---(+1 day)---> "silenced" (permanent, no message)

Any stage ---(user sends message)---> "none" (full reset)
```

---

## 2. New Service: `services/re_engagement_service.py`

### Suppression Levels

```python
class SuppressionLevel(Enum):
    NONE = "none"                        # Normal operation
    BLOCK_SLEEP = "block_sleep"          # Pipeline A: food nudge pending
    ALLOW_WEEKLY_ONLY = "allow_weekly"   # Pipeline B days 1-3
    TOTAL = "total"                      # Pipeline B after day 3
```

### Key Methods

- `get_suppression_level(profile) -> SuppressionLevel` - Pure function on `re_engagement_stage`
- `check_re_engagement(profile, clock) -> ReEngagementAction | None` - Determines what to send
- `generate_smart_question(profile) -> str` - GPT day-2 message
- `generate_context_message(profile) -> str` - GPT day-3 message
- `transition_stage(tid, new_stage)` - Updates stage + last_sent_at

### Logic Flow in `check_re_engagement()`

1. If `re_engagement_stage == "silenced"` -> return None (done)
2. Calculate `days_since_last_message` using `last_user_message_at` + UserClock
3. **Pipeline B check first** (overrides A):
   - stage in ("none", "food_nudge_pending") + days_silent >= 1 + in morning window + not sent today -> send day1 nudge
   - stage == "silence_day1" + days_silent >= 2 -> send GPT smart question
   - stage == "silence_day2" + days_silent >= 3 -> send GPT context message
   - stage == "silence_day3" + days_silent >= 4 -> transition to "silenced" silently
4. **Pipeline A check** (only if Pipeline B didn't fire):
   - stage == "none" + no food yesterday + user IS active (has recent messages within 24h) + in morning window -> send food nudge
   - stage == "food_nudge_pending" + food logged -> reset to "none"

### Detecting "No Food Yesterday"

```python
yesterday = (clock.today() - timedelta(days=1)).strftime("%d/%m/%Y")
entries = food_repo.get_by_user_and_dates(tid, [yesterday])
return len(entries) > 0
```

Uses calendar day (not eating day) - this is about "did you use the bot," not nutrition accounting.

### Detecting "User Active But Not Logging Food"

Check `last_user_message_at` is within 24h (user is communicating) but no food entries yesterday. This distinguishes Pipeline A (active, no food) from Pipeline B (silent).

---

## 3. GPT Prompts

### Day 2 - Smart Question (`content/prompts/re_engagement_smart_question.txt`)

System prompt with user context (name, active habits, food days count, patterns). Instructs GPT to write one short Hebrew question in Dugri tone that helps understand why the user stopped. Should surface useful info (could lead to feature requests).

### Day 3 - Context Message (`content/prompts/re_engagement_context_message.txt`)

System prompt with journey stats (days active, total meals, habits tracked, patterns). Must:
1. Summarize what was achieved together (specific numbers)
2. Encourage return gently
3. End with clear "I won't initiate anymore. When you want - just write."

Both use `FoodAnalyzer._create()` wrapper (existing pattern for GPT calls with token tracking).

---

## 4. Message Templates

### `content/messages/food_nudge.txt` (pool, random selection)

~5 Hebrew variants like "didn't you eat anything yesterday?" / "a whole day with no food entry. What happened?"

### `content/messages/silence_day1.txt` (pool, random selection)

~3 Hebrew variants for first silence nudge.

---

## 5. Scheduler Changes (`scheduler.py`)

### Insertion Point

In `_check_user_hooks()`, **after** goal reminders, **before** habit hooks:

```python
# --- Goal reminders (highest priority) --- [existing]

# --- Re-engagement (NEW) ---
suppression = re_engagement_svc.get_suppression_level(profile)
if suppression == SuppressionLevel.TOTAL:
    return  # silenced user - skip everything

action = re_engagement_svc.check_re_engagement(profile, clock)
if action:
    re_engagement_svc.transition_stage(tid, action.new_stage)
    await _send_and_save(context, tid, action.message, ...)
    return  # one message per tick

if suppression == SuppressionLevel.ALLOW_WEEKLY_ONLY:
    # only fire weekly_summary hook, skip all others
    # (filter existing hooks loop to weekly_summary only)
    ...
    return

# --- Habit hooks --- [existing, with sleep suppression added]
for hook in hooks:
    if toggle_name == "sleep" and suppression == SuppressionLevel.BLOCK_SLEEP:
        continue  # food nudge blocks sleep
    ...
```

### Wiring

- Add `re_engagement_service` to `schedule_global_poller()` params and `data` dict
- Instantiate in `bot.py` alongside existing services

---

## 6. Handler Changes (`handlers/base.py`)

In `handle_message()`, after saving user message to recent_messages:

```python
self.user_repo.update_fields(tid, {
    "last_user_message_at": datetime.now(timezone.utc).isoformat(),
})

# Returning from silence pipeline -> welcome back + reset
previous_stage = profile.re_engagement_stage
if previous_stage in ("silence_day1", "silence_day2", "silence_day3", "silenced"):
    re_engagement_svc.handle_return(profile, tid)
elif previous_stage != "none":
    self.user_repo.update_fields(tid, {"re_engagement_stage": "none"})
```

### Welcome Back on Return from Silence (Pipeline B)

When a user returns after being in any silence stage, `handle_return()` does:

1. **Resets `re_engagement_stage` to `"none"`**
2. **Resets `consecutive_unanswered` to 0** on all active toggles - fresh start, no exit doors on first interaction back
3. **Sends a welcome-back message** listing the user's active toggles and inviting them to fill in the gap

The welcome-back message is GPT-generated. It gets the user's name and list of active toggle names, and produces a short, warm Dugri-style message that naturally invites the user to re-log those habits if they want. No lists, no forms - just a casual mention.

Example tone (sleep + workouts active):
```
שי, טוב שחזרת. אם בא לך לעדכן על שינה או אימונים מהימים האחרונים - קדימה. אם לא - ממשיכים מפה.
```

The message is sent as a bot reply within the normal handler flow, not via the scheduler.

### Pipeline A (food_nudge_pending) - no welcome back

When returning from `food_nudge_pending`, just reset to `"none"` silently. The user is actively chatting - they don't need a welcome message.

---

## 7. Constants (`constants.py`)

```python
FOOD_NUDGE_WINDOW = (8, 10)  # Same as sleep
```

---

## 8. Files to Create/Modify

| File | Action |
|------|--------|
| `models/profile.py` | Add 3 fields + backward compat |
| `services/re_engagement_service.py` | **New** - core logic |
| `scheduler.py` | Insert re-engagement check + suppression |
| `handlers/base.py` | Track last_user_message_at + reset stage |
| `constants.py` | Add FOOD_NUDGE_WINDOW |
| `bot.py` | Instantiate + wire service |
| `messages.py` | Load new message files |
| `content/messages/food_nudge.txt` | **New** - nudge templates |
| `content/messages/silence_day1.txt` | **New** - silence nudge templates |
| `content/prompts/re_engagement_smart_question.txt` | **New** - GPT prompt |
| `content/prompts/re_engagement_context_message.txt` | **New** - GPT prompt |
| `tests/test_re_engagement.py` | **New** - comprehensive tests |

---

## 9. Test Plan

### Unit Tests (mock GPT, mock food_repo)

**Pipeline A:**
- Food nudge fires when no food yesterday + morning window + user active
- Food nudge skipped outside morning window
- Food nudge resets when food logged
- Food nudge blocks sleep but allows workouts/self_care
- Food nudge daily forever without food (user active)
- Food nudge not sent to new users (no last_user_message_at)

**Pipeline B:**
- Silence day 1 after 1 day no messages
- Silence day 2 calls GPT for smart question
- Silence day 3 calls GPT for context message
- "Silenced" stage after day 4 (no message sent)
- Total suppression blocks all hooks including weekly
- Days 1-3 allow weekly feedback only

**Welcome back:**
- Return from silence stages sends welcome message with active toggles
- Return from "silenced" (permanent) also sends welcome message
- Return from "food_nudge_pending" does NOT send welcome message
- `consecutive_unanswered` reset to 0 on all active toggles on return
- Welcome message lists only active toggles (not dormant/cancelled)
- User with only food active gets shorter message (just food)

**Transitions:**
- User message resets any stage to "none"
- Pipeline A transitions to B when user goes silent
- Pipeline B overrides A
- No double-send same day (re_engagement_last_sent_at)

**Edge cases:**
- UserClock timezone safety (Asia/Jerusalem midnight)
- User with no last_user_message_at (new user) - skip re-engagement
- User with food yesterday but no food today - no nudge yet

### Integration Tests (scheduler)
- Re-engagement fires after goals, before hooks
- Silenced user gets zero messages from any hook
- Food nudge + sleep suppression in full scheduler tick

---

## 10. Verification

1. Run `pytest tests/test_re_engagement.py -v`
2. Manual test with a test user:
   - Log food normally, verify no nudge next morning
   - Skip food for a day, verify nudge at 8-10
   - Log food after nudge, verify sleep resumes
   - Stop messaging entirely, verify 3-day escalation
   - Send message after silenced, verify full reset
