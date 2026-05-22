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

- **Backend:** Flask 3.1.1 (Python), Blueprints architecture
- **Auth:** Google OAuth 2.0 (Authlib)
- **Database:** MongoDB (pymongo) — unified `users` collection in db `health_tracker` (shared with bot)
- **AI:** OpenAI GPT-4o-mini for calorie/protein target suggestions
- **Frontend:** Jinja2 templates, Alpine.js 3.x for reactivity, vanilla CSS with CSS variables
- **Testing:** pytest
- **Deployment:** Railway (env var `RAILWAY_PUBLIC_DOMAIN` detects prod)

### Project structure

```
dashboard/
├── app.py                  # Flask app factory, blueprint registration
├── auth.py                 # Google OAuth: /auth/login, /auth/callback, /auth/logout
├── dashboard_views.py      # Dashboard routes: /dashboard/home, goals, profile, subscription
├── api.py                  # REST API: /api/suggest-targets, /api/regenerate-bot-link
├── storage.py              # DashboardStorage — MongoDB abstraction layer
├── analyzer.py             # OpenAI integration for suggesting calorie/protein targets
├── hebrew_strings.py       # All Hebrew UI strings (consent text, errors, post-signup)
├── key_generator.py        # MD5-based bot key generation
├── onboarding.py           # Legacy blueprint (redirects to landing)
├── config/
│   ├── config.json         # Runtime config (secrets, OAuth, MongoDB URI)
│   └── config.example.json
├── templates/
│   ├── base.html           # Base layout (RTL, Alpine.js)
│   ├── landing.html        # Landing page with consent checkboxes + Google signup
│   ├── welcome.html        # Post-signup: shows Telegram deep link
│   ├── about.html, terms.html, privacy.html
│   └── dashboard/
│       ├── layout.html     # Dashboard nav + main layout
│       ├── home.html       # Bot usage guide
│       ├── toggles.html    # Habit toggle control (synced with bot)
│       ├── targets.html    # Calorie/protein targets (synced with bot)
│       ├── weekly_summaries.html  # Weekly feedback archive
│       ├── profile.html    # Personal data (age, weight, height)
│       └── subscription.html
├── static/css/style.css
└── tests/
```

### Signup & bot linking flow

1. Landing page (`/`) — user checks consent checkboxes (terms + medical disclaimer)
2. Google OAuth via `/auth/login` → `/auth/callback`
3. On callback: create/update user in `users`, generate `signup_session_token` (24h)
4. Redirect to `/welcome` — shows Telegram deep link: `https://t.me/{bot}?start={token}`
5. When user clicks link → bot receives `/start {token}` → links `telegram_user_id` to profile

### Database schema (`users`)

Primary key: `_id` = user email. Key fields:
- `name`, `photo_url`, `telegram_user_id`
- `signup_session_token`, `signup_session_token_expires_at`
- `consents` object (terms, privacy, medical disclaimer, marketing opt-in — all timestamped + versioned)
- `toggles` object (each toggle: `status` dormant/active/cancelled, timestamps)
- `targets` object (unified: `calories`, `protein` — shared with bot)
- `birth_year`, `height_cm`, `weight_kg` (optional profile data)
- `subscription_status` (`trial_pending` / `active` / `cancelled`)

### Config format (`config/config.json`)

```json
{
  "flask": { "secret_key": "...", "debug": true },
  "google_oauth": { "client_id": "...", "client_secret": "..." },
  "openai": { "api_key": "..." },
  "mongodb": { "uri": "mongodb://...", "db_name": "health_tracker" },
  "dugri_bot_username": "skinny_slimmy_bot",
  "contact_email": "bendorshai@gmail.com"
}
```

On Railway: injected via `DASHBOARD_CONFIG_JSON` env var.

### Key patterns

- **`@login_required` decorator** on all dashboard/API routes — checks `session["user_email"]`
- **Alpine.js** for reactive UI (consent checkboxes, goals toggles)
- **Hebrew strings centralized** in `hebrew_strings.py` — not inline in templates
- **RTL-first** — `dir="rtl"` in base template, no LTR fallback

### Interaction with health_tracker bot

Two connection points:
1. **Signup:** `signup_session_token` in MongoDB. Dashboard writes it; bot reads it to link accounts.
2. **Target changes:** Dashboard calls bot's internal webhook (`POST /internal/notify-target-update`) when targets are updated. Bot generates and sends a GPT-powered validation message to the user. Config keys: `bot_internal_url`, `internal_secret`.

---

## עדכון אחרון

22.05.2026
