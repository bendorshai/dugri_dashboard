# CLAUDE.md - דוגרי (Telegram bot)

> BEFORE YOU PUSH A VERSION YOU MUST UPDATE THESE VALUES IN main.py:
1. VERSION = ... 
2. VERSION_NOTES = ...

## מה זה דוגרי

בוט טלגרם למעקב הרגלי בריאות בעברית. חבר ישראלי בגובה העיניים שלא נותן לך לרמות את עצמך, ולא חופר בך.

**חמישה הרגלים בלבד** (לא להוסיף בלי אישור):
1. **תזונה** - קלוריות וחלבון, תיעוד בשיחה חופשית
2. **חלון אכילה** - למשל 16:8
3. **שעת שינה** - תיעוד יומי
4. **אימונים בשבוע** - מספר אימונים
5. **משהו לעצמי השבוע** - הרגל שבועי (טיפול, טיול, ספר)

## טון הדיבור

ישראלי, פרקטי, בגובה העיניים. לא חופר, לא מתחנף, לא נוזף. המספרים הם הכנות.

- כן: "קלטתי. שווארמה בלאפה. ≈ 720 קלוריות, 38 ג' חלבון."
- לא: "כל הכבוד!!!", "אתה בטוח?", "איך אתה מרגיש עם זה?"

מגדר: דוגרי מדבר בגוף שני נקבה/זכר לפי העדפת המשתמש.

---

## Technical orientation

### Tech stack

- **Bot framework:** python-telegram-bot 21.6 (async, webhook on Railway / polling locally)
- **AI:** OpenAI GPT-4o (photos), GPT-4o-mini (text analysis, coaching)
- **Database:** MongoDB (pymongo) - unified `users` collection (PK=email), `food_entries`, `weekly_feedback`, `error_logs`, habit logs
- **Validation:** Pydantic v2 for structured GPT response parsing
- **Deployment:** Docker + Railway (webhook mode via `RAILWAY_PUBLIC_DOMAIN`)

### Project structure

```
health_tracker/
├── main.py                 # Entry point
├── bot.py                  # Application with all handlers
├── constants.py            # All timing/numeric parameters
├── messages.py             # All Hebrew text Dugri says
├── handlers/
│   ├── base.py             # Message/callback handlers + piggyback hooks
│   ├── start_handler.py    # /start command routing
│   └── utils.py            # send_long_text, safe_react, safe_answer
├── analyzer.py             # OpenAI wrapper for food analysis
├── internal_api.py         # Dashboard -> bot webhook
├── repositories/           # MongoDB repositories
├── services/
│   ├── toggle_service.py   # Toggle state management
│   ├── onboarding_service.py
│   ├── eating_day_service.py
│   └── ...
├── scheduler.py            # Eating window alerts + proactive hooks
├── keyboards.py            # Inline keyboards + formatting
├── prompts.py              # GPT system prompts (composable blocks)
├── parsing.py              # Timezone, eating window utilities
├── config/config.json      # Runtime config (tokens, API keys)
├── start.sh                # Startup (extracts env vars to config)
├── Dockerfile
├── requirements.txt
└── tests/
```

### Key concepts

**Eating day:** Not a calendar day - defined by eating window (e.g., 08:00-20:00). A meal at 22:00 still belongs to "today." Source of truth: `EatingDayService`.

**Toggle system:** 3-state (`dormant` -> `active` -> `cancelled`). Opt-in toggles (sleep, eating_window, workouts, self_care) born dormant, revealed gradually. `weekly_summary` born active. All timing in `constants.py`, state in `ToggleService`.

**Proactive hooks:** Each active toggle has scheduled + piggyback hooks. Piggyback (attached to meal response) always takes priority over scheduled. On 2nd consecutive unanswered hook, Dugri offers to cancel the toggle. 5 random phrasings per toggle in `messages.py`.

**Pending states:** Profile-based (`user.pending_state`, 5-min TTL): `awaiting_name`, `awaiting_target_consent`, `awaiting_body_stats`, `awaiting_toggle_consent`, `awaiting_eating_window`, `awaiting_feedback_reaction`. Context-based (`context.chat_data`): `pending_edit`, `pending_question`, `pending_correction`, `pending_bulk_fix`.

### Content separation

- **`messages.py`** - All Hebrew text. Never hard-code Hebrew in logic code.
- **`constants.py`** - All timing parameters. Never hard-code timing values in logic code.

### GPT patterns

- `beta.chat.completions.parse()` with Pydantic response models
- Temperature 0 for analysis, 0.7 for feedback/suggestions
- Composable system prompts in `prompts.py`

### Dashboard interaction

Shared `users` collection (PK=email). `/start {token}` links Telegram user to dashboard account. Dashboard notifies bot of target changes via `POST /internal/notify-target-update`.

### Config (`config/config.json`)

```json
{
  "telegram": { "bot_token": "..." },
  "openai": { "api_key": "..." },
  "mongodb": { "uri": "...", "db_name": "health_tracker" }
}
```

On Railway: injected via `CONFIG2_JSON` env var, extracted by `start.sh`.
