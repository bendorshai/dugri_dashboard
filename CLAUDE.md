# CLAUDE.md — דוגרי

הקובץ הזה הוא ההקשר הקבוע של הפרויקט. תקרא אותו בתחילת כל סשן ולפני כל החלטה משמעותית. עדכונים שוטפים והחלטות נקודתיות נמצאים תחת `docs/decisions/`.

---

## מה זה דוגרי

דוגרי הוא בוט טלגרם למעקב הרגלי בריאות בעברית. המודל: השירות עצמו חי בטלגרם; האתר נועד רק להרשמה, תשלום, וניהול חשבון.

**הפוזיציה השיווקית במשפט אחד:** דוגרי הוא חבר ישראלי בגובה העיניים שלא נותן לך לרמות את עצמך, ולא חופר בך.

**הסלוגן:** איתך על ההרגלים.

---

## חמשת ההרגלים

המוצר עוקב אחרי **חמישה** הרגלים בלבד. לא ארבעה ולא שישה. הפשטות היא חלק מהמותג, לא מקרית.

1. **תזונה** — קלוריות וחלבון יחד, הרגל אחד עם שני מדדים. תיעוד בשיחה חופשית בעברית.
2. **חלון אכילה** — למשל 14:8 או 16:8.
3. **שעת שינה** — תיעוד יומי של שעת ההירדמות.
4. **אימונים בשבוע** — מספר אימונים, לא דקות או חזרות.
5. **משהו לעצמי השבוע** — הרגל שבועי של עשייה לעצמך (טיפול, טיול, ספר, שקיעה בים). זה הבידול המהותי מכל המתחרים.

**שום הרגל אחר אינו רלוונטי.** לא קפה, לא מים, לא צעדים, לא מצב רוח. אם מישהו (משתמש או קוד) מציע להוסיף — לפנות אלי קודם.

---

## אישיות המותג

שלוש שכבות, לפי סדר חשיבות:

1. **חבר בגובה העיניים** — לא מאמן, לא מטפל, לא מורם מעם. עברית טבעית ישראלית, בלי טון של מקצוען.
2. **לא נותן לך לרמות את עצמך** — לא חוקר, לא מטיל ספק, לא נוזף. מציג נתונים בקור רוח. הכנות נוצרת מהמספרים, לא מהדיאלוג.
3. **פשטות רדיקלית** — בוט בטלגרם, חמישה הרגלים, אין UI ללמוד.

---

## טון הדיבור

**עקרונות:**
- ישראלי בגובה העיניים — "קלטתי", "או, חזרת", "בוא נמשיך".
- פרקטי, לא רגשי — לא שואל "מה הרגשת", לא מזמין שיתוף.
- נותן תוקף, לא נוזף ולא מתחנף.
- המספרים הם הכנות — דוגרי לא מטיל ספק במה שכתבת, רק מציג חישוב.

**דוגרי לא יגיד:**
- "איך אתה מרגיש עם זה?" (חופר)
- "כל הכבוד!!! מצוין!!!" (מתחנף)
- "אתה בטוח שזה הכל?" (מטיל ספק)
- "שמת לב שאתה חורג מהיעד?" (נוזף)
- "להגיע ליעד הקלורי שלך זה צעד חשוב..." (קלישאה אימונית)

**דוגרי כן יגיד:**
- "קלטתי. שווארמה בלאפה עם הרבה טחינה. ≈ 720 קלוריות, 38 ג' חלבון. סך הכל היום: 1,840."
- "היי, חזרת. בוא נמשיך — מה אכלת היום?"
- "יפה. רשמתי 'משהו לעצמי' השבוע."

---

## כתיבה מגדרית

**הטקסט הציבורי (אתר, עמוד נחיתה) מנוסח בגוף ראשון רבים** — "פתחנו", "הבטחנו", "הורדנו". המסר: אנחנו ביחד בזה. דוגרי לא מטיף, הוא מצטרף לכאב.

**בתוך הבוט** — הטקסטים שמורים בנפרד; דוגרי מדבר עם המשתמש בגוף שני נקבה/זכר לפי העדפת המשתמש (יוגדר באונבורדינג).

**לא להשתמש ב-"/ה" בתוך טקסט שיווקי באתר.** מכוער ויזואלית. גוף ראשון רבים פותר את זה אלגנטית. ה-"/ה" יופיע רק בצ'קבוקסים משפטיים (שם זה תקן ולא מפריע).

---

## פלטת צבעים

| תפקיד | צבע | קוד |
|-------|-----|-----|
| צבע הזהות (לוגו, כפתורים ראשיים, כותרות) | קינמון | `#A67448` |
| צבע אוויר (רקעי אזורים, גרפים) | תכלת ים תיכוני | `#5BA8C4` |
| רקע ראשי | שמנת | `#FAF7F2` |
| טקסט | אפור חמים | `#5A554D` |
| סטטוס חיובי | זית | `#8FA876` |
| סטטוס שלילי/התראה | טרקוטה | `#C97A6B` |

**אסור:**
- לבן צורם — תמיד שמנת.
- שחור — תמיד אפור חמים.
- ירוקים אנרגטיים-מסחריים (סגנון אפליקציות כושר).
- גרדיאנטים צעקניים.

---

## לוגו

הלוגו הוא בועת דיבור עם המילה "דוגרי" בעברית ומתחתיה "איתך על ההרגלים".

**שתי גרסאות רשמיות:**
1. **ראשית** — רקע שמנת, מסגרת וטקסט קינמון. לאתר, מסמכים, חתימות מייל, מצגות.
2. **משנית** — בועה ממולאת בקינמון, טקסט שמנת. לאווטר טלגרם, favicon, אייקון אפליקציה — כל מקום שצריך נוכחות בולטת בגודל קטן.

**אסור:**
- לשנות צבעים — אין גרסת תכלת ללוגו.
- להטות, להוסיף אפקטים, גרדיאנטים.
- לערוך את הפרופורציות.

---

## פיסיון של המייסד

המייסד (שי בן-דור מאיר) **נוכח רק בשולי משפך השיווק**, לא במוצר.

**איפה שי מופיע:**
- בעמוד "מי עומד מאחורי דוגרי" (אם קיים).
- בתחתית עמוד המכירה כסיפור קצר.
- בפוסטים אישיים בפייסבוק.

**איפה שי לא מופיע:**
- בליבת עמוד הנחיתה.
- בתוך הבוט — דוגרי הוא דוגרי, לא דובר של שי.
- בדשבורד.
- בצ'קבוקסים המשפטיים ("דברי פרסומת מדוגרי", לא "מדוגרי או משי").

**הסיבה:** הפרדה מגנה על שי מביקורת אישית, ושומרת על דוגרי כמותג עצמאי.

---

## עקרונות מוצריים קריטיים

### עיקרון 1: אנחנו לא חופרים
- אין שאלון אונבורדינג של 7-10 מסכים. ההיכרות עם המשתמש מתפתחת בקצב שלו, בתוך הבוט.
- אין שדות חובה מיותרים.
- אם משהו יכול להיכנס לבוט ולא לאתר — הוא נכנס לבוט.

### עיקרון 2: שיחה, לא טופס
- המשתמש כותב "אכלתי שווארמה בלאפה" — דוגרי מבין.
- לא רשימות נפתחות. לא חיפוש מנות. לא ספריות מאכלים.

### עיקרון 3: המספרים הם הכנות
- דוגרי מציג חישוב, לא ביקורת.
- אם המשתמש כתב 200 קלוריות בארוחה של 800 — דוגרי לא חוקר. הוא רושם 800 (לפי ההערכה שלו) ומציג. אם המשתמש רוצה לתקן — הוא מתקן.

### עיקרון 4: פשטות רדיקלית
- חמישה הרגלים, לא חמישה-עשר.
- אין אינטגרציות, אין שעונים חכמים, אין סטטיסטיקות מורכבות.
- אם פיצ'ר לא חיוני — הוא מסיח. מסירים.

---

## עקרונות עיצוב ל-UI ולעמוד הנחיתה

- **רקע שמנת**, לא לבן.
- **קינמון** לפעולות עיקריות (CTA, כותרות מרכזיות).
- **תכלת** לאוויר, גרפים, פרטים נושמים.
- **טיפוגרפיה ישראלית** — נחרצת, נושמת, לא תוקפנית.
- **חלל לבן (cream space)** — נדיבות במרווחים, לא דחיסות.
- **קישורים משפטיים** — תמיד `target="_blank" rel="noopener noreferrer"`, נפתחים בחלון חדש.

---

## מצב מודל התשלום

- **תקופת התנסות:** 21 יום ללא עלות, ללא צורך בכרטיס אשראי בהתחלה.
- **לאחר 21 יום:** המשתמש מזין פרטי אשראי דרך מסך סליקה.
- **מחיר:** 47 ₪ לחודש, כולל מע"מ.
- **חיוב מתחדש אוטומטית** — עם הסכמה מפורשת בעת הזנת פרטי האשראי.
- **ביטול** — בלחיצה. אפשר דרך הבוט, דרך האתר, או במייל.

**הקופי הציבורי על התשלום:**
- "21 יום התנסות ללא עלות. אחר כך 47 ₪ לחודש — אפשר לבטל בלחיצה."
- **לא** "חודש חינם". לא "ניסיון חופשי". לא "בלי חיוב".

---

## מיתוג מול שפת קופי

| כן | לא |
|----|-----|
| "21 יום התנסות ללא עלות" | "חודש חינם!" |
| "קלטתי" | "מעולה!!! נרשם בהצלחה!" |
| "בלי בולשיט" | "פתרון מתקדם מבוסס AI" |
| "אנחנו לא נחפור בך" | "המאמן הדיגיטלי האישי שלך" |
| "חבר" | "מאמן" / "אפליקציה" / "פלטפורמה" |

---

## אזורים רגישים שדורשים זהירות

### בריאות נפשית והפרעות אכילה
דוגרי נוגע במשקל ובאכילה. זה תחום שיכול לפגוע. **בכל החלטת מוצר** — לבדוק שהיא לא דוחפת לכיוון אובססיבי, לא חוגגת ירידה במשקל מהירה, לא מעודדת ספירת קלוריות כפייתית.

**דוגרי הוא כלי למודעות, לא להקצנה.** אם פיצ'ר עלול להזיק למישהי עם הפרעת אכילה — לא להוסיף אותו.

### פרטיות
- נתוני בריאות נחשבים מידע רגיש לפי חוק הגנת הפרטיות הישראלי.
- כל אינטגרציה חדשה צריכה הסכמה מפורשת.
- שמירת מידע: עד 18 חודשים אחרי חוסר פעילות. אחר כך נמחק אוטומטית.

### תוכן שיווקי
- אסור לשלוח דברי פרסומת ללא הסכמה מפורשת, או בלי לעמוד בתנאי החריג של "לקוח קיים" (סעיף 30א(ג) לחוק התקשורת).
- כל מייל שיווקי חייב לכלול: המילה "פרסומת" בכותרת, פרטי המפרסם, וקישור הסרה.

---

## תהליך עבודה עם Claude Code

### לפני כל שינוי משמעותי
1. לקרוא את הקובץ הזה (CLAUDE.md).
2. לבדוק תחת `docs/decisions/` אם יש החלטה רלוונטית.
3. אם השינוי סותר משהו פה — לעצור ולשאול את המשתמש.

### אחרי כל שינוי משמעותי
- לעדכן את `docs/decisions/` אם זה רלוונטי.
- לא לעדכן את CLAUDE.md אלא אם המשתמש ביקש במפורש (זה ההקשר הקבוע, לא יומן).

### תיעוד החלטות
החלטות נקודתיות נכתבות לקובץ נפרד בפורמט:
```
docs/decisions/YYYY-MM-DD-short-topic.md
```

לדוגמה:
- `docs/decisions/2026-05-20-signup-page-legal-and-copy.md`
- `docs/decisions/2026-05-22-onboarding-flow.md`

---

## אנשי קשר ואחריות

- **מייסד ובעלים:** שי בן-דור מאיר
- **תפקידו של Claude Code:** מימוש טכני בלבד. החלטות מוצריות, שיווקיות, ומשפטיות — דרך השיחה עם שי.
- **דברים שמחייבים אישור מפורש משי לפני שינוי:**
  - תוכן צ'קבוקסים משפטיים.
  - מספר ההרגלים.
  - מודל התמחור.
  - פלטת הצבעים.
  - הסלוגן והפוזיציה.

---

---

## Technical orientation

### Tech stack

- **Bot framework:** python-telegram-bot 21.6 (async, webhook on Railway / polling locally)
- **AI:** OpenAI GPT-4o (photos), GPT-4o-mini (text analysis, coaching)
- **Data log:** Google Sheets (gspread) — one row per food entry
- **Database:** MongoDB (pymongo) — `user_profiles`, `weekly_feedback`, `error_logs`
- **Validation:** Pydantic v2 for structured GPT response parsing
- **Scheduling:** Built-in job queue for eating window alerts
- **Deployment:** Docker + Railway (webhook mode via `RAILWAY_PUBLIC_DOMAIN`)

### Project structure

```
health_tracker/
├── main.py                 # Entry point: loads config, inits services, runs bot
├── bot.py                  # Creates Application with all handlers
├── handlers/
│   ├── base.py             # HealthHandlers — all command/message/callback handlers (~1000 lines)
│   └── utils.py            # Helpers: send_long_text, safe_react, safe_answer
├── analyzer.py             # FoodAnalyzer — OpenAI wrapper for food analysis, corrections, feedback
├── storage.py              # MongoStorage — MongoDB for profiles, feedback, errors
├── sheets.py               # SheetsClient — Google Sheets read/write (source of truth for food log)
├── scheduler.py            # Eating window scheduled jobs (30-min warning, window close summary)
├── keyboards.py            # Inline keyboard definitions + formatting helpers
├── prompts.py              # GPT system prompts (reusable building blocks)
├── parsing.py              # Timezone, eating window logic utilities
├── config/
│   ├── config.json         # Runtime config (tokens, API keys, sheet ID)
│   ├── config.example.json
│   └── google_credentials.json
├── start.sh                # Startup script (extracts env vars to config files)
├── Dockerfile
├── requirements.txt
└── tests/
```

### Current state: single-user

The bot currently has a **hardcoded `chat_id`** in config. All messages from other users are silently ignored. The grand refactor plan (see `../plans/`) will make it multi-user.

### Core food logging flow

1. User sends text ("שווארמה בלאפה") or photo of food
2. `FoodAnalyzer` calls GPT → returns structured items (calories, protein per item)
3. Bot appends row to Google Sheets (columns: date, time, description, calories, protein, in-window)
4. Bot reads back daily totals from sheet and displays progress vs targets
5. User can edit, delete, duplicate entries via inline buttons

### Critical concept: eating day

An "eating day" is **not** a calendar day — it's defined by the eating window (e.g., 08:00-20:00). A meal at 22:00 still belongs to "today's" eating day. The method `get_entries_for_eating_day()` in `sheets.py` is the source of truth for this logic.

### Message handling & state

`context.chat_data` stores pending states with 5-minute TTL:
- `pending_edit` — awaiting profile field input
- `pending_question` — awaiting Q&A
- `pending_correction` — awaiting food edit text
- `pending_bulk_fix` — awaiting bulk correction description
- `correction_histories[row]` — tracks chained corrections per sheet row

### Scheduled jobs

- **30 min before eating window close:** Shows current daily totals vs targets
- **At window close:** Final summary + AI coaching feedback from the full week's data

### GPT integration patterns

- All calls use `beta.chat.completions.parse()` with Pydantic response models
- Temperature 0 for analysis/corrections (deterministic), 0.7 for feedback/suggestions (creative)
- System prompts built from composable blocks in `prompts.py`
- Photo analysis uses GPT-4o; text analysis uses GPT-4o-mini

### Google Sheets schema (columns A-F)

| Column | Header | Content |
|--------|--------|---------|
| A | תאריך | DD/MM/YYYY |
| B | שעה | HH:MM |
| C | תיאור | Food description in Hebrew |
| D | קלוריות | Calories (integer) |
| E | חלבון | Protein in grams (integer) |
| F | בחלון אכילה | "כן" or "לא" |

### Config format (`config/config.json`)

```json
{
  "telegram": { "bot_token": "...", "chat_id": 2145100468 },
  "openai": { "api_key": "..." },
  "google_sheets": { "credentials_file": "config/google_credentials.json", "sheet_id": "...", "tab_name": "Sheet1" },
  "mongodb": { "uri": "mongodb://...", "db_name": "health_tracker" }
}
```

On Railway: injected via `CONFIG2_JSON` and `GOOGLE_CREDENTIALS_JSON` env vars, extracted by `start.sh`.

### Interaction with dashboard

Bot reads `dashboard_users` collection to link Telegram users via `signup_session_token`. When a user sends `/start {token}`, the bot looks up the token, retrieves the email, and stores `telegram_user_id` on the dashboard user record.

---

## עדכון אחרון

21.05.2026
