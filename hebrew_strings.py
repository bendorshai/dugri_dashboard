"""Hebrew UI strings for new onboarding functionality.

Existing landing page copy (hero, problem/solution, features, about)
stays inline in the templates. This module covers only the new
consent, post-signup, legal, and error strings.
"""

from __future__ import annotations

# -- Consent checkboxes (landing page) --
CONSENT_TERMS = 'אני מסכים/ה ל<a href="/terms">תנאי השימוש</a> ול<a href="/privacy">מדיניות הפרטיות</a>'
CONSENT_MEDICAL = (
    "אני מבין/ה שדוגרי הוא כלי לעקיבות הרגלים ולא תחליף לייעוץ רפואי "
    "או תזונתי מקצועי, ושהמספרים שמוצגים הם הערכות מבוססות-AI שעלי לבדוק בעצמי"
)
CONSENT_MARKETING = "אני מסכים/ה לקבל דברי פרסומת משי או מצוות דוגרי במייל"
CONSENT_REQUIRED_LABEL = "חובה"
CONSENT_OPTIONAL_LABEL = "אופציונלי"

# -- Error messages --
ERROR_MISSING_CONSENT = "כדי להמשיך, צריך לאשר את תנאי השימוש ואת ההצהרה הרפואית"
ERROR_OAUTH_FAILED = "ההתחברות נכשלה. נסה שוב."

# -- Post-signup zone --
POST_SIGNUP_WELCOME = "יופי, {name}. בוא נפתח את דוגרי בטלגרם."
POST_SIGNUP_CTA = "פתח את דוגרי בטלגרם"
POST_SIGNUP_FALLBACK = "אם הכפתור לא נפתח אצלך, לחץ כאן להעתקת הקישור"

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

# -- Terms page --
TERMS_TITLE = "תנאי שימוש"
TERMS_LAST_UPDATED = "עדכון אחרון: {date}"

# -- Privacy page --
PRIVACY_TITLE = "מדיניות פרטיות"
PRIVACY_SUBTITLE = (
    "עדכון אחרון: {date}. "
    "בהתאם לחוק הגנת הפרטיות (ישראל) וסעיף 30א לחוק התקשורת (בזק ושידורים)"
)

# -- Payment placeholder --
PAYMENT_PLACEHOLDER = "בקרוב"
