# Health Tracker Bot

Telegram bot for tracking daily calorie and protein intake.

## Stack
- Python 3.12+ with python-telegram-bot v21.6
- MongoDB (PyMongo) for user profiles, food entries, feedback, insights
- OpenAI API (GPT-4o-mini for text, GPT-4o for photos) for food analysis
- Google Sheets (gspread) for logging entries
- Deployed on Railway with Docker

## Architecture
- `main.py` — config loading, dependency wiring, webhook/polling
- `bot.py` — handler registration, error handler, scheduler setup
- `analyzer.py` — GPT wrapper with Pydantic structured output
- `storage.py` — MongoDB collections (user_profiles, food_entries, weekly_feedback, gpt_insights)
- `sheets.py` — Google Sheets column-mapped client
- `scheduler.py` — eating window notification jobs
- `handlers/base.py` — all message, photo, and callback handlers
- `keyboards.py` — inline keyboards and callback prefixes

## Testing
```bash
python -m pytest tests/ -v
```
Tests stub external dependencies (telegram, openai, pymongo, gspread) with MagicMock.

## Config
Copy `config/config.example.json` to `config/config.json` and fill in credentials.
