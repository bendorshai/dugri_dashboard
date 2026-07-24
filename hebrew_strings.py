"""Hebrew UI strings for new onboarding functionality.

Existing landing page copy (hero, problem/solution, features, about)
stays inline in the templates. This module covers only the new
consent, post-signup, legal, and error strings.
"""

from __future__ import annotations

# -- Consent checkboxes (landing page) --
CONSENT_TERMS = 'אני מסכים/ה ל<a href="/terms" target="_blank" rel="noopener noreferrer">תנאי השימוש</a> ול<a href="/privacy" target="_blank" rel="noopener noreferrer">מדיניות הפרטיות</a>, ומאשר/ת שאני בן/בת 18 ומעלה.'
CONSENT_MEDICAL = "אני מבין/ה שדוגרי הוא כלי למודעות, לא תחליף לייעוץ רפואי או תזונתי, ומסכים/ה לעיבוד מידע בריאותי (משקל, תזונה, שינה, פעילות גופנית) לצורך מתן השירות."
CONSENT_REQUIRED_LABEL = "חובה"

# -- Signup page micro-FAQ (between title and trial kicker) --
SIGNUP_FAQ_LINES = [
    "כותבים או מצלמים לדוגרי את מה שאתם אוכלים",
    "דוגרי עוקב ומכניס אתכם לעניינים לאט לאט",
    "תנו לדוגרי חודש והוא כבר יקלוט אתכם בקטע מפתיע",
]

# -- Error messages --
ERROR_MISSING_CONSENT = "כדי להמשיך, צריך לאשר את כל התנאים"
ERROR_OAUTH_FAILED = "ההתחברות נכשלה. נסה שוב."

# -- Post-signup zone --
POST_SIGNUP_WELCOME = "יופי, {name}. בוא נפתח את דוגרי בטלגרם."
POST_SIGNUP_CTA = "פתח את דוגרי בטלגרם"
POST_SIGNUP_FALLBACK = "אם הכפתור לא נפתח אצלך, לחץ כאן להעתקת הקישור"

# -- Home screen tip (welcome page) --
HOME_TIP_BADGE = "💡 טיפ שעושה את כל ההבדל"
HOME_TIP_INTRO = "רגע לפני - איך לשים את דוגרי כאייקון נפרד בפלאפון?"
HOME_TIP_TAB_ANDROID = "אנדרואיד"
HOME_TIP_TAB_IPHONE = "אייפון"
HOME_TIP_ANDROID_STEPS = [
    "פתחו את הצ׳אט עם דוגרי בטלגרם",
    "לחצו על ⋮ (שלוש נקודות למעלה)",
    'בחרו "הוספה למסך הבית" - וזהו!',
]
HOME_TIP_IPHONE_STEPS = [
    "פתחו את הקישור t.me/{bot_username} בדפדפן Safari",
    "לחצו על כפתור השיתוף ⎋ למטה",
    'בחרו "הוסף למסך הבית"',
]
HOME_TIP_IPHONE_ALT = "או: פתחו את הצ׳אט בטלגרם, לחצו ארוך והצמידו אותו למעלה."
HOME_TIP_SEGUE = "עכשיו, בואו נתחיל 👇"

# -- Footer --
FOOTER_ABOUT_LINK = "מי עומד מאחורי דוגרי"
FOOTER_TERMS_LINK = "תנאי שימוש"
FOOTER_PRIVACY_LINK = "מדיניות פרטיות"
FOOTER_CONTACT_LINK = "יצירת קשר"

# -- About page --
ABOUT_HEADLINE = "מי עומד מאחורי דוגרי"
ABOUT_BODY = (
    "היי, אני שי בן-דור מאיר. בניתי את דוגרי כי הייתי צריך אותו בעצמי. "
    "רציתי כלי שיעזור לי להיות \"על זה\" בלי לחפור בי, בלי שיהפוך את הבריאות "
    "שלי לעוד פרויקט עם UI לתחזק. דוגרי הוא מה שיצא — בוט בטלגרם שמראה לך "
    "את עצמך, ועוזר לך להישאר קשוב."
)

# -- Legal document version (single source of truth; also written to consents.doc_version) --
DOC_VERSION = 1
DOC_VERSION_DATE = "12.07.2026"

# -- Terms page --
TERMS_TITLE = "תנאי שימוש"
TERMS_LAST_UPDATED = "גרסה {version} · בתוקף מ-{date}"

# -- Privacy page --
PRIVACY_TITLE = "מדיניות פרטיות"
PRIVACY_SUBTITLE = (
    "גרסה {version} · בתוקף מ-{date}. "
    "בהתאם לחוק הגנת הפרטיות (ישראל)"
)

# -- Subscription page --
SUB_TITLE = "מנוי"
SUB_TRIAL_ACTIVE_HEADING = "14 יום ניסיון חינם"
# Dynamic trial-remaining headings (chosen by days left; see subscription.html).
SUB_TRIAL_DAYS_LEFT = "נשארו לך {} ימים בתקופת הניסיון"
SUB_TRIAL_LAST_DAY = "היום האחרון של תקופת הניסיון"
SUB_TRIAL_ENDING_TODAY = "תקופת הניסיון מסתיימת היום"
SUB_TRIAL_ACTIVE_BODY = "אתה כרגע בתקופת ניסיון חינמית. בסיומה תוכל להמשיך עם מנוי."
SUB_TRIAL_ENDED_HEADING = "תקופת הניסיון הסתיימה"
SUB_TRIAL_ENDED_BODY = "כדי להמשיך לתעד ולקבל אימון מדוגרי, הפעל מנוי."
SUB_SUBSCRIBE_CTA = "להתחיל מנוי - {} ₪ לחודש"
SUB_ACTIVE_HEADING = "מנוי פעיל"
SUB_ACTIVE_BODY = "המנוי שלך פעיל."
# Transparency block: exactly what we charge, how much, and when.
SUB_DETAIL_WHAT_LABEL = "מה נחייב"
SUB_DETAIL_WHAT_VALUE = "מנוי חודשי לדוגרי"
SUB_DETAIL_AMOUNT_LABEL = "כמה"
SUB_DETAIL_AMOUNT_VALUE = "{} ₪"
SUB_DETAIL_WHEN_LABEL = "החיוב הבא"
SUB_CANCEL_BTN = "ביטול מנוי"
SUB_CANCEL_CONFIRM = "בטוח? הגישה תישאר עד {}."
SUB_CANCELLED_HEADING = "המנוי בוטל"
SUB_CANCELLED_BODY = "הגישה לדוגרי ממשיכה עד {}. אחרי זה אפשר תמיד לחדש."
SUB_RESUBSCRIBE_CTA = "לחדש מנוי"
SUB_ENDED_HEADING = "המנוי שלך הסתיים"
SUB_ENDED_BODY = "הנתונים שלך שמורים ומחכים. הפעל מנוי כדי להמשיך."
# Billing history + download
SUB_HISTORY_HEADING = "היסטוריית חיובים"
SUB_HISTORY_DOWNLOAD = "הורדה (CSV)"
SUB_HISTORY_COL_DATE = "תאריך"
SUB_HISTORY_COL_AMOUNT = "סכום"
SUB_HISTORY_COL_STATUS = "סטטוס"
SUB_HISTORY_OK = "שולם"
SUB_HISTORY_FAIL = "נכשל"
SUB_HISTORY_RECEIPT = "קבלה"
SUB_RECEIPT_NOTE = "קבלה על כל תשלום נשלחת אוטומטית למייל שלך."
SUB_SUCCESS_FLASH = "המנוי הופעל בהצלחה. תודה!"
SUB_FAILURE_FLASH = "התשלום לא הושלם. נסה שוב."
SUB_CONTACT = "שאלות? צור קשר ב-{}"
