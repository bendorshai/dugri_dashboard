# Legal Documents Review & Edit Plan (Terms + Privacy)

- **Date:** 2026-07-09
- **Scope:** `dashboard/templates/terms.html` and `dashboard/templates/privacy.html`
- **Jurisdiction:** Israeli law. Operator is a named individual (שי בן-דור מאיר), sole proprietor, personal Gmail as sole contact.
- **Product context:** "דוגרי" - Hebrew Telegram health-habit bot + web dashboard. Collects health data (meals, calories, protein, weight, height, age, sleep, eating-window, workouts, meal photos). Processors: OpenAI, Telegram, Google, Railway, MongoDB. 14/21-day free trial then 47₪/month auto-renew.
- **Method:** Four-lens council review (privacy law / consumer-protection / medical-liability / contract-enforceability). This file consolidates all findings and the phased edit plan.

> **DISCLAIMER:** This plan is a risk review, not legal advice. Enforceability calls (esp. the liability-cap items) must be confirmed with an Israeli-licensed attorney before relying on them. Founder-sign-off items are marked.

---

## One-line verdict

The **Terms** are a competent generic template but wrong on several Israel-specific points. The **Privacy policy** is a decent *consumer-app* policy but **non-compliant as a sensitive-health-data policy** under Privacy Protection Law Amendment 13 (in force ~Aug 2025). Two findings are code/config bugs, not just text. Several "protections" in the Terms (the 500₪ liability cap over bodily harm) are likely void exactly where they are needed, giving false comfort.

---

## PART 1 - FINDINGS (severity-ranked, deduplicated)

Reviewer tags: [PRIV] privacy, [CONS] consumer, [MED] medical, [ENF] enforceability.

### CRITICAL

- **C1. Trial length: Terms say 14 days, everything else says 21.** [ALL]
  `terms.html §6` = "14 ימים". CLAUDE.md, marketing copy, and mandated public copy = 21. Binding contract contradicts the promise the user saw. Misleading practice (הטעיה, חוק הגנת הצרכן §2) + contract-formation defect (ambiguity construed against drafter) + poisons credibility on every other clause. **Verify billing code's actual trial window.** Founder decision.

  **DECISION (2026-07-10): Trial is 14 days.** Terms §6 already correct - no change to `terms.html`. Fix flows outward: align to "14 ימים" in landing/marketing copy and CLAUDE.md payment model (currently 21 in 4 places); verify billing code trial window = 14. CLAUDE.md pricing change authorized by founder here.

- **C2. Liability cap over bodily/mental harm is largely void and gives false comfort.** [MED][ENF][CONS]
  `terms.html §11(ד)+(ה)` excludes and caps liability for "נזק גוף, נזק בריאותי, נזק נפשי" at 500₪ / 3 months' fees. Cannot contract out of negligence liability for personal injury in a consumer adhesion contract. §11(ז) carves out only זדון/רשלנות חמורה, narrower than the law requires (ordinary negligence causing bodily injury is also non-excludable). Court will strike this for the exact ED-harm scenario the product most plausibly causes. Compounded by no severability clause (H9) and no limited-liability entity (H10).

  **DECISION (2026-07-10): Approved - narrow the cap to economic loss, remove the bodily/mental-harm disclaimer.** Executable:
  - §11(ד): remove "נזק גוף, נזק בריאותי, נזק נפשי, או החמרה של מצב רפואי קיים" from the excluded-damages list. Keep exclusions for economic/consequential/reliance loss (lost time/profit/data, reliance on AI estimates, third-party outages, indirect/special damage).
  - §11(ה): reframe cap to apply to **economic/consequential loss only** (not personal injury).
  - §11(ז): broaden carve-out from "זדון/רשלנות חמורה" to also cover any personal-injury (גוף/נפש) liability that cannot be excluded by law.
  - Keep §11(ב) reliance-on-numbers disclaimer (valid, protective).
  - Real mental-harm mitigation handled separately via safety scaffolding (H11), not this clause.

- **C3. Privacy policy never acknowledges it holds special-sensitivity health data (מידע בעל רגישות מיוחדת).** [PRIV]
  Root defect under Amendment 13. Cascades into: wrong security tier (§8 says only "אמצעים סבירים", not "רמת אבטחה גבוהה"), likely-required database registration, possibly-required DPO (ממונה על הגנת הפרטיות), stricter/granular consent. These are *existence* questions a regulator checks first, backed by expanded administrative-fine powers.

  **DECISION (2026-07-10):**
  - **Wording approved, refined.** Add clause acknowledging this is מידע בעל רגישות מיוחדת. For security (§8): do NOT use the regulatory label "רמת אבטחה גבוהה" (we don't meet that defined tier); instead state "אמצעים ההולמים את רגישות המידע" and describe only what actually exists. Final §8 security wording:
    > "אנו נוקטים באמצעי אבטחה ההולמים את רגישות המידע: התקשורת אל השרתים שלנו מוצפנת (HTTPS/TLS), והגישה למסד הנתונים מוגבלת ומוגנת באמצעי הזדהות. ההזדהות לחשבון מתבצעת באמצעות Google (OAuth). שירותי צד שלישי (כגון Google ו-Telegram) כפופים לאמצעי האבטחה שלהם, שאינם בשליטתנו ובאחריותם בלבד. עם זאת, אין מערכת מאובטחת לחלוטין..."
    - REMOVE "גיבויים שוטפים" (operator does not commit to backups).
    - Third-party disclaimer for BOTH Google (auth) and Telegram (transport) - operator not liable for their infrastructure.
    - Do NOT claim registration/DPO that do not exist.
  - **Database registration + DPO: DEFERRED (confirmed by web search).** Amendment 13: **registration duty does NOT apply at all** to דוגרי - it applies only to databases whose main purpose is collecting data to sell/transfer (>10k people) or to public bodies; דוגרי does neither. The relevant threshold is the **notification** duty to the Authority for special-sensitivity data on **>100,000 data subjects** - far above current scale. Revisit near 100k. Not a blocker; no registration/DPO language in the doc now.
  - Breach-notification-to-Authority duty (M3) applies regardless of size - keep.

- **C4. Eating-disorder "detection-without-response" trap.** [MED]
  `terms.html §8(ב)` reserves a *right* to suspend on "סימנים להפרעת אכילה"; §8(ד) calls it "operational, not medical". This proves foreseeability/knowledge of harm (duty-of-care multiplier), the "not medical" label won't hold when the trigger is a clinical inference, and framing action as optional invites an "assumed duty - you saw the signs and did nothing" claim. Detection + discretion + inaction is the worst posture. Product decision.

  **DECISION (2026-07-10): Reframe to a care-pathway (operator already HAS a response - not the trap).** Operator's real practice: exceptional cases are encouraged to reach out personally, and operator personally refers relevant cases to specialist eating-disorder bodies = demonstrable standard of care, his strongest defense. Executable §8 wording:
  - Replace clinical-label trigger ("סימנים להפרעת אכילה") with observable "דפוסי שימוש חריגים שעשויים להצביע על שימוש שאינו מיטיב עם המשתמש".
  - State the RESPONSE explicitly (this is the protection): encourage the user to seek appropriate professional help, and where appropriate refer to specialist bodies.
  - Keep the suspension/limitation right for exceptional cases where continued use may harm the user.
  - Non-clinical caveat: outreach/referral is not diagnosis, medical advice, or professional assessment (keeps §8(ד)).
  - **Abusive/offensive/violent language = explicit enumerated suspension ground** (operator treats cursing as a red flag for self-harm risk).
  - Draft §8 block:
    > "אם אנו מזהים דפוסי שימוש חריגים שעשויים להצביע על שימוש שאינו מיטיב עם המשתמש, אנו עשויים לפנות אליו, לעודד אותו לפנות לעזרה מקצועית מתאימה, ובמקרים המתאימים להפנות אותו לגורמים מקצועיים המתמחים בכך. שמורה לנו הזכות להגביל או להשעות שימוש במקרים חריגים שבהם אנו סבורים כי המשך השימוש עלול לפגוע במשתמש. פנייה או הפנייה כאמור אינן מהוות אבחון, ייעוץ רפואי, או הערכה מקצועית."
  - **Feeds H8:** enumerated grounds must include abusive/offensive/violent language; harmful-to-self usage patterns; misuse/fraud/unauthorized automation; breach of terms/law; unauthorized commercial use. Drop "מכל סיבה שייראה לו".
  - Connects to H11 (signposting line in §4).

### HIGH

- **H1. Blank-contract render bug (CODE, verified).** [ENF]
  `app.py` defaults `contact_email` to `""`; both templates wrap the entire contact/data-rights block in `{% if contact_email %}`. One missing config key ships a contract + privacy policy with **no contact address and no DSAR channel** - a per-se compliance failure. Easiest to fix.

  **DECISION (2026-07-10): Official contact = `support@dugri.life`.** Executable:
  - Set `contact_email` to `support@dugri.life` in config (prod + `config.example.json`).
  - Remove the `{% if contact_email %}` gates around legally-required contact info in `terms.html` and `privacy.html` - contact must always render.
  - Keep a hard, non-empty fallback constant (`support@dugri.life`) in `app.py` so a missing config key can never blank the contact block; consider failing the render loudly if unset rather than silently hiding.
  - Replaces the personal Gmail as the public legal contact (also resolves the personal-Gmail concern in H10/E3). Verify the mailbox actually exists and is monitored.

- **H2. Cross-border transfer of health data + unverifiable DPA claims.** [PRIV]
  `privacy.html §5` asserts all processors are "כפופים לחוזי עיבוד מידע"; no international-transfer clause exists. Telegram almost certainly does not sign a DPA with a solo operator (data flows under Telegram's own consumer terms). Claiming non-existent DPAs is testable with one document request. Needs a transfer-basis clause + honest processor-vs-independent-service distinction.

  **DECISION (2026-07-10): No DPAs signed with anyone - so claim none. Use general, non-exhaustive, non-committal wording.** Operator wants freedom to add/swap providers (e.g. replace OpenAI) without the doc committing that any specific provider is currently in use. Executable §5:
  - Remove the false "כפופים לחוזי עיבוד מידע ולהתחייבות לסודיות" claim entirely.
  - List names as illustrative and non-binding as to current use ("בין הספקים שנעשה או עשוי להיעשות בהם שימוש, בין היתר: ..."), keep "רשימה זו אינה ממצה ועשויה להשתנות מעת לעת".
  - State providers may process data outside Israel, each subject to its OWN terms/privacy policy, not under our control.
  - Add cross-border transfer basis: transfer happens "בהסכמתך ומתוך הכרח לאספקת השירות".
  - Keep "איננו מוכרים מידע אישי".
  - Draft §5 block:
    > "מתן השירות מחייב שימוש בספקי שירות טכניים ותפעוליים (תשתית ענן, מסדי נתונים, שירותי בינה מלאכותית, זיהוי, סליקה ודיוור). בין הספקים שנעשה או עשוי להיעשות בהם שימוש, בין היתר: Telegram, OpenAI, Google, Railway, MongoDB. רשימה זו אינה ממצה ועשויה להשתנות מעת לעת. ספקים אלה עשויים לעבד חלק מהמידע גם מחוץ לישראל, וכל אחד מהם כפוף לתנאי השימוש ולמדיניות הפרטיות שלו עצמו, שאינם בשליטתנו. המידע מועבר אליהם בהסכמתך ומתוך הכרח לאספקת השירות. איננו מוכרים מידע אישי."
  - **Action item (not a blocker):** sign the free standard DPAs (OpenAI/Railway/MongoDB) later; then wording can be upgraded from "subject to its terms" to "under a data-processing agreement".

- **H3. AI-training/model-improvement reuse clause.** [PRIV][MED]
  `privacy.html §3` reserves reuse of "אנונימיזציה או פסבדונימיזציה **ככל הניתן**" health data. Pseudonymized data is still personal data; "ככל הניתן" is a weasel word; consent is bundled into the signup checkbox (not separate/opt-in); contradicts the "we don't sell/transfer" promise in the same document.

  **DECISION (2026-07-10): Operator wants full internal freedom over the data; frame it honestly, not as "anonymous".** Operator's real practice: he and his analysts/agents review usage data INCLUDING raw conversations to surface product issues, exceptional cases, and sales-improvement ideas - but detached from direct identifiers (name/phone/email), internal only, never sold/transferred. Executable §3:
  - DELETE "אנונימיזציה או פסבדונימיזציה ככל הניתן" (misleading - it is NOT anonymous; conversation content can be personal data).
  - Do NOT use the word "אנונימי". Use "ללא הצמדה לפרטים מזהים ישירים כגון שם, מספר טלפון או כתובת דוא\"ל".
  - State the internal use explicitly (this transparency is what makes the consent informed/valid): by the operator and those acting on its behalf (analysts + agents), for operating/improving the service, bug-finding, understanding user needs, sales improvement.
  - Reaffirm not sold/transferred to third parties for their purposes; internal only.
  - Legal basis = informed signup consent + necessity for operating the service (covered by keeping the disclosure explicit; no separate opt-in needed per operator's choice).
  - No separate/optional opt-in split (operator rejected that; wants freedom via the main consent).
  - Draft §3 block:
    > "אנו עושים שימוש בנתונים שלך - לרבות תוכן השיחות - לצורך הפעלת השירות, שיפורו, איתור תקלות, הבנת צרכי המשתמשים ושיפור המכירות. העיון נעשה על ידי מפעיל השירות והפועלים מטעמו (אנליסטים וסוכנים), ללא הצמדה לפרטים מזהים ישירים כגון שם, מספר טלפון או כתובת דוא\"ל. השימוש נעשה לצרכים פנימיים בלבד - איננו מוכרים ואיננו מעבירים את נתוניך לצדדים שלישיים לצרכיהם."
  - Note: the OpenAI "does not train on your data" claim (M10) lives in the same §3 - handle there.

- **H4. Cancellation not "as easy as signup" + wrong cancellation-fee formula.** [CONS]
  `terms.html §7`: cancellation "יטופל תוך 3 ימי עסקים" fails the "הסר בקליק"/immediacy duty for an online continuing transaction (עסקה מתמשכת). §7(א)'s "5% or 100₪, lower of" is a mis-imported distance-selling formula; 100₪ can never apply against 47₪/month (5% = 2.35₪). No cancellation-confirmation commitment.

  **DECISION (2026-07-10):**
  - Cancellation is **self-serve via bot/site, effective immediately, stops the next charge**. Remove the "יטופל תוך 3 ימי עסקים" manual-handling framing (confirm the bot/site flow is genuinely self-serve and immediate, not a manual queue).
  - **No cancellation fee at all** - DELETE the "5% או 100 ₪, הנמוך מביניהם" formula from §7(א).
  - Current already-paid month is **not** refunded (Option A model).
  - **Cancellation confirmation sent via the Telegram bot** (valid written confirmation; email optional backup). Confirmation must be **actively sent** (law requires the operator to send confirmation). A dashboard status is a supplement only, NOT a substitute for the sent message.
  - Statutory 14-day cooling-off (§7(א), distance selling) still honored as a SEPARATE case: pro-rata refund for the unused period, **no fee** (more generous than the law = safe). Finalized in the M7 refund matrix.

- **H5. Marketing consent contradicts itself and fails §30א.** [CONS][PRIV][ENF]
  `terms.html §13` is opt-out ("מיודע... ייתכן שיישלחו"); `privacy.html §3/§4` is opt-in ("הסכמה נפרדת"). §30א חוק התקשורת needs prior opt-in + the word "פרסומת" + sender details + one-click unsubscribe. None committed in §13.

  **DECISION (2026-07-10): Rely on the existing-customer exception (§30א(ג)).** [SUPERSEDED 2026-07-12 by R2-15 - marketing dropped entirely; see below. Founder chose not to take any §30א risk. Remove marketing clauses from docs + remove CONSENT_MARKETING_NOTICE from signup; only operational messages remain.] Original decision text kept for history:
  Operator has no separate marketing checkbox and does not want one (fears it deters signups). The exception fits: customer gave details at signup, marketing is about the same service, provided we notify + give a refusal opportunity + format messages correctly. Executable:
  - **Align both docs to the existing-customer basis, not "separate explicit opt-in".** In `privacy.html §3/§4`: remove "בכפוף להסכמה נפרדת" / "רק למשתמשים שסימנו הסכמה מפורשת"; instead state that, as a customer, we may send marketing about our own service, and you may opt out at any time.
  - **`terms.html §13`:** reframe to the existing-customer model - notify that details may be used to send marketing about the service; opportunity to refuse; commit that every marketing message carries the word "פרסומת", sender details, and one-click unsubscribe.
  - Operational/transactional messages remain consent-free (keep that distinction).
  - **Companion signup-page task (NOT legal text):** add a small NON-blocking notice at signup ("בהרשמתך אנו עשויים לשלוח עדכונים שיווקיים על השירות; תוכל להסיר את עצמך בכל עת") + a non-blocking refusal option, to satisfy the §30א(ג) "notice + opportunity to refuse at collection" condition. Lives in `landing.html`/signup flow - flag for implementation alongside the legal edits.

- **H6. "שימוש = הסכמה" undercuts the stronger checkbox proof.** [ENF]
  `terms.html §1` browse-wrap contradicts the click-wrap checkbox flow actually used, handing a plaintiff the "I never agreed to §11" opening. Same problem with "continued use = consent to amendments" (`privacy §11`), a classic תנאי מקפח.

  **DECISION (2026-07-10): Approved.** Executable:
  - `terms.html §1`: base acceptance on the **signup checkbox** (timestamped + versioned in the `consents` object), not on "use". Remove/subordinate "השימוש בשירות מהווה הסכמה" so it doesn't undercut the click-wrap proof.
  - **Material changes require notifying the customer** (active notice), not passive "continued use = consent".
  - `privacy.html §11`: same - passive "continued use = consent" only for non-material changes; material changes need notice.
  - Consent record already exists (DB `consents` object, timestamped+versioned) - no new logging work; just connect the version (see H7).

- **H7. No version string; hardcoded, already-drifting "last updated" date.** [ENF]
  Both docs hardcode `21.05.2026` in-template (CLAUDE.md says 22.05.2026 - drift already real). The `consents` object is versioned, but the rendered document names no version, breaking the evidentiary chain at the last link.

  **DECISION (2026-07-10): Current text = "גרסה 1"; print version + date from one shared source; rely on git history as the version archive.** Executable:
  - Label the current text **גרסה 1** with an effective date; print "גרסה 1 - בתוקף מ-DD.MM.YYYY" (or similar) in both docs' subtitle.
  - Source the version string + date from ONE shared constant (same value written into `consents.version`), not hardcoded per-template. Stop hardcoding `21.05.2026` in the template call.
  - Past versions are already preserved in **git history** (the docs are versioned HTML in git) - sufficient archive; no separate archive folder required.
  - On every future material edit: bump the version + new effective date; the git commit is the archived artifact.
  - Fixes the date drift (was 21.05 in template vs 22.05 in CLAUDE.md) by having a single source.
- **H8. Sole-discretion suspension "מכל סיבה שייראה לו".** [CONS][ENF]
  `terms.html §8(ב)/(ד)` - textbook תנאי מקפח under חוק החוזים האחידים §4(6). Constrain to enumerated objective grounds + notice/cure where appropriate.

  **DECISION (2026-07-10): Replace "מכל סיבה שייראה לו" with enumerated grounds; unified no-refund rule; goodwill kept OUT of the contract.** Executable:
  - **Enumerated suspension/termination grounds** (§8(ב)) - replace open discretion with:
    1. שפה פוגענית, מקללת או אלימה.
    2. דפוסי שימוש שאינם מיטיבים עם המשתמש (protective care-pathway from C4).
    3. שימוש לרעה, הונאה, או אוטומציה לא מורשית.
    4. ניסיון לפגוע במערכת/במשתמשים, לחלץ מידע, לנצל פרצות או חולשות, או לבזות/להשמיץ את השירות.
    5. הפרת תנאי השימוש או החוק.
    6. שימוש מסחרי/מקצועי שלא הותר מראש בכתב.
  - Tie misuse grounds to the operator's **"הערכה סבירה"**, not absolute discretion.
  - **Non-paying (trial/free) users:** operator has a broader right to decline/terminate access (no payment relationship) - state this distinction.
  - **Refund on termination - unified rule (rewrite §8(ג)):** any service termination (by user or operator, any ground) stops the next charge; the current already-paid month is NOT refunded; **no pro-rata refund anywhere**. Delete the existing pro-rata / no-fault-refund language. Gives operator the "penalty" for misconduct; consistent with H4 cancellation model.
  - **Goodwill refund for the protective-suspension case (ground #2, a vulnerable user) = internal discretionary practice, NOT written in the contract.** Legal: a contract sets the floor; being more generous than it is always permitted. Keeping it out of the contract also avoids creating a claimable entitlement. Operator will credit the current month at his discretion in that compassionate case.
  - Keeps §8(ד) non-clinical framing (from C4). Residual minor risk: a court could order pro-rata for a no-fault termination of a blameless payer - covered by severability (H9) + rarity; accepted.
- **H9. Missing severability clause (ביטול חלקי).** [ENF]
  When C2's liability terms get struck, nothing preserves the rest. Highest-value *missing* clause.

  **DECISION (2026-07-10): Approved - add a standard severability clause.** Executable: add to `terms.html` a clause: "אם ייקבע שסעיף כלשהו בתנאים אלה בטל או לא אכיף, ייחשב הסעיף כאילו צומצם למידה המזערית הדרושה כדי להכשירו, ויתר התנאים יישארו בתוקף מלא." Underpins C2 and H8.
- **H10. Entity/identity risk.** [ENF][PRIV]
  Named individual, personal Gmail, no ע.מ./ח.פ./registered address. Full personal liability, no corporate veil. "כולל מע\"מ" implies עוסק status but no business number/address shown - easy consumer-protection formal hook. Founder decision (incorporation).

  **DECISION (2026-07-10):**
  - **Incorporation (בע"מ): DEFERRED** - operator is at ~0 revenue as **עוסק פטור**; no company now, revisit when revenue grows. Action item, not a doc change.
  - **CRITICAL FIX - remove "כולל מע\"מ".** An עוסק פטור does NOT charge/add VAT, so "47 ₪ כולל מע\"מ" is both a tax error and a consumer misrepresentation. Change all occurrences to plain **"47 ₪"** (terms §6, §7, and check CLAUDE.md payment model + `subscription.html` for consistency - ties to B4). Re-add VAT wording only if/when he becomes עוסק מורשה.
  - **Add business identity to both docs' contact section:** name **שי בן-דור מאיר** + address **הזית 28ה, זכרון יעקב**. 
  - **Do NOT publish the ת.ז. publicly** (identity-theft risk; not strictly required in-doc). Instead state that the עוסק number is available on request. (Status: עוסק פטור; ת.ז. held by operator, deliberately NOT stored in this repo file.)
- **H11. No safety scaffolding for the named risk group.** [MED]
  Only mitigation is a vague "קו חירום מתאים" on a page users never read. No named ED resource, no in-bot signposting, no self-exclusion/off-ramp, no real age-gate. This is both the strongest legal defense (demonstrable standard of care) and the ethical minimum. Product decision.

  **DECISION (2026-07-10): Add named crisis resource (ער"ן) + broad professional-referral wording to §4.** The real care-pathway is already covered by C4; this strengthens the doc text. Executable - add to `terms.html §4`:
  > "אם את/ה חווה מצוקה נפשית, קושי סביב אכילה או דימוי גוף, או זקוק/ה בתמיכה - מומלץ לפנות לעזרה מקצועית. ניתן לפנות לקו הסיוע הנפשי של ער\"ן (חיוג 1201, זמין בכל שעה), לרופא/ה או לקופת החולים, ולאנשי מקצוע מוסמכים - פסיכולוגים, עובדים סוציאליים קליניים, ודיאטנים - לרבות דרך פורטלים ומאגרים מקצועיים מקוונים."
  - In-bot signposting / age-gate / self-exclusion remain OUT of scope for the HTML edit (product items, not legal text) - noted, not built here.
### MEDIUM

- **M1. Legal basis incoherent** - `privacy §4` leans on "אינטרס לגיטימי" for tech development of health data; can't carry sensitive-data reuse. [PRIV]
  **DECISION (2026-07-10): Approved.** Ground processing in **consent + necessity for performing the service**; remove "פיתוח טכנולוגי" from the "אינטרס לגיטימי" basket where health data is involved. Aligns §4 with the H3 reframe.
- **M2. No profiling/automated-decision disclosure** despite AI insights + §8(ב) suspension logic. [PRIV]
  **DECISION (2026-07-10): Approved.** Add a short privacy clause disclosing automated processing (AI-generated insights, weekly summaries, detection of exceptional usage patterns) and that the user may contact us about it. Transparency backs up C4.
- **M3. Breach notification too vague** - `privacy §8` mentions only user notice, not the Authority + timeline. [PRIV]
  **DECISION (2026-07-10): REVERSED to minimal.** Do NOT add explicit "notify the Authority" language. Keep the existing §8 phrasing "נודיע כנדרש על פי חוק" - it already covers whatever the law requires (incl. Authority reporting if applicable). Rationale: the statutory duty binds the operator regardless of the policy text; omitting it carries near-zero risk (a policy need not recite the duty), while writing it creates a self-imposed commitment. Clarification for the record: privacy-breach reporting goes to the הרשות להגנת הפרטיות, not מערך הסייבר. Net effect: §8 breach sentence stays as-is.
- **M4. Retention** - indefinite for active accounts; 12+6 wording vs CLAUDE.md "18 months"; tax-retention period undefined. **Verify deletion cron matches.** [PRIV][ENF]
  **DECISION (2026-07-10):**
  - **Active account:** keep "נשמר כל עוד החשבון פעיל" (no cap) - simple, fine for an ongoing service.
  - **Payment data:** keep the vague "לפי דרישות חוקי המס" (do NOT write "7 years"). Same logic as M3 - self-updating when the law changes, contract needn't be edited. No wording change.
  - **18-month inactive-deletion rule (12+6): SUPERSEDED by R2-07** - the auto-deletion commitment is being REMOVED (no statutory duty; self-imposed and unnecessary). §6 now says data is kept while the account exists / as long as relevant + deletion on request. No cron. See R2-07.
- **M5. Minors** - "18+, we don't knowingly collect" with zero age verification on Telegram; weak for a weight/eating product. [PRIV][MED]
  **DECISION (2026-07-10): Keep 18+; add a self-declaration 18+ checkbox at signup.** Web-checked law: majority age is 18 (contracts with minors are voidable); under-13 collection is barred without parental consent; 13-18 is a heightened-care grey zone (opt-in preferred for sensitive data). Google OAuth does NOT reliably give age (standard scopes return name/email/photo only; Google's own min age is 13, not 18) - so age-gating via Google is rejected. Executable:
  - Keep the 18+ requirement in `privacy §10` / `terms §11(ו)`.
  - **Companion signup-page task (NOT legal text):** add a **"אני מעל גיל 18" self-declaration checkbox** at signup (`landing.html`/signup flow) - non-blocking friction, industry-standard, shifts responsibility to the user. Timestamp/version it with the other consents.
  - Keep the takedown-if-discovered process.
- **M6. Unilateral service/feature change "בכל עת"** (`§9`) with no cancel-and-refund right for material removal. [CONS][ENF]
  **DECISION (2026-07-10): Full freedom to change the product; NO pro-rata refund; customer's remedy = free exit. Plus: add dormant annual-plan infrastructure now.** Operator's honest position: customers pay for the mindset, not a fixed feature set; he wants to evolve דוגרי freely and not deal with partial refunds on such a small sum; unhappy customers can leave. Legal path to get this:
  - **Reframe the service as evolving by nature** (§9): features/behavior/content change from time to time as part of the product; the user acknowledges this up front (defuses "you sold me something else").
  - **Customer's only remedy for a change they dislike = cancel anytime, next charge stops, NO pro-rata refund** (relies on H4). Defensible because: no lock-in (monthly), free exit, de-minimis sum, backed by severability (H9). Reverses the reviewer's original "add pro-rata" suggestion.
  - Accepted residual risk: a court could order a few days' refund in an extreme mid-month gut - small, acceptable.
  - **Annual-plan infrastructure - ADD TO `terms.html` NOW (dormant; not offered yet).** No penalty (operator agreed). On early cancellation, used period re-priced at the standard monthly rate (loses the discount), balance refunded; no fee; 14-day cooling-off still applies. Draft clause:
    > "מסלול לתקופה קצובה (כגון שנתי): מפעיל השירות עשוי להציע מעת לעת מסלול תשלום מראש לתקופה קצובה במחיר מוזל. הבחירה במסלול כזה היא מרצון. המשתמש רשאי לבטל בכל עת; בביטול לפני תום התקופה, התקופה שנוצלה תחושב לפי המחיר החודשי הרגיל (ללא ההנחה), והיתרה תוחזר למשתמש. לא ייגבו דמי ביטול או קנס. זכות הביטול בתוך 14 ימים לפי חוק הגנת הצרכן חלה גם על מסלול זה."
  - Rejected: an extra ~5% "cashflow" penalty - can't lawfully penalize the exercise of a cancellation right (מקפח risk), off-brand, and the re-pricing already protects more than 5%.
- **M7. Refund mechanics inconsistent** across `§6/§7(א)/§7(ג)/§8(ג)` - needs one coherent refund matrix. [CONS]
  **DECISION (2026-07-10): Consolidate into ONE coherent refund matrix in §7 (no new decisions - unifies H4/H8/M6).** Whole-period billing only - NO half-month/fractional-day math anywhere:
  1. **Cooling-off (14 days from first charge):** contract states **pro-rata refund** of the unused period, **no cancellation fee** (delete the old "5% או 100 ₪" formula). Cannot be waived (mandatory statutory right). This is the lawful minimum and fully compliant. **Implementation at operator's discretion** (pro-rata, or more generous) - text stays "pro-rata". [Round-2: founder insists on keeping pro-rata wording; confirmed no legal problem.]
  2. **Regular cancellation after cooling-off:** service runs to the end of the already-paid period, then stops; current month NOT refunded; no pro-rata.
  3. **Operator-initiated termination:** (a) **conduct-based** (any H8 enumerated ground) → stops next charge, no refund; (b) **no-fault** (operator closes a blameless payer) → **pro-rata refund** [R2-11].
  4. **Product/feature change:** no refund; remedy = free exit.
  5. **Annual/fixed-term plan (dormant, future):** early cancellation calculated in WHOLE months used at the standard monthly rate, balance refunded; no fee; cooling-off applies.
  6. **Goodwill credit** on protective suspension of a vulnerable user: internal practice, NOT in the contract.
  - Contract sets the floor; operator may always be more generous (cooling-off full refund + protective goodwill are both "more than promised").
- **M8. Indemnity clause** (`§11(ח)`) - inert against the direct-injury claim that matters, borderline מקפח; keep narrowly scoped to third-party claims from user's unlawful use/breach. [CONS][MED]
  **DECISION (2026-07-10): Approved - narrow the indemnity.** Keep an indemnity but scope it to **third-party claims arising from the user's unlawful use or material breach** (not a blanket "any claim"). Protects the real case (a third party sues the operator because of the user's conduct) without being struck as מקפח.
- **M9. Extended-cancellation figures (§7(ב))** and the §14ג "conversation" precondition need line-by-line verification vs current statute. [CONS]
  **DECISION (2026-07-10): Option B - general reference, no hardcoded numbers.** Replace the specific figures (age 65 / 5-year / 4-month) with a self-updating general reference: "בהתאם לזכויות הביטול המורחבות הקבועות בחוק הגנת הצרכן לאזרחים ותיקים, אנשים עם מוגבלות ועולים חדשים." Consistent with the operator's "stay vague so it self-updates" principle (cf. M3, M4).
- **M10. OpenAI "doesn't train on your data"** stated as absolute - true only under API terms as configured; verify actual config. [PRIV]
  **DECISION (2026-07-10): REMOVE entirely.** It was a marketing reassurance, not a legal requirement, and it's an absolute claim about a third party's behavior the operator doesn't control (conflicts with H2's no-provider-lock direction). Delete the "OpenAI... אינם משתמשים בנתונים אלה לאימון" statements from §3 and §5. No soft replacement - the general provider wording (H2) + "we don't sell data" already suffice.
- **M11. §8(ב) quasi-diagnostic wording** ("סימנים להפרעת אכילה") risks false-positive/defamation harm - reframe to observable usage patterns. [MED]
  **DECISION (2026-07-10): Already resolved via C4.** The C4 reframe (replace "סימנים להפרעת אכילה" with observable "דפוסי שימוש חריגים") covers this. No separate action - executed together with C4.
- **M12. Missing standard clauses** - entire-agreement, assignment, no-waiver, notices mechanism, amendment effective-date, governing-language. [ENF]
  **DECISION (2026-07-10): Add all four standard clauses to `terms.html`** (severability already added in H9; amendment effective-date handled in H6/H7):
  1. **Entire agreement (מיזוג):** these terms + the privacy policy are the full agreement, superseding prior promises/representations.
  2. **Assignment (המחאת זכויות):** operator may assign its rights/obligations to a third party (e.g. sale of the business); the user may not transfer their account. (Useful for future incorporation/sale.)
  3. **No-waiver (אי-ויתור):** non-enforcement of a right is not a waiver of it.
  4. **Governing language (גרסה קובעת):** the Hebrew version is the binding version.

### LOW / polish

- Typo `privacy §5`: "ויידחקו" should be "ויישלחו". [PRIV][ENF]
  **DECISION (2026-07-10): Approved** - fix the typo "ויידחקו" → "ויישלחו".
- DSAR handling: no identity-verification step, no legal-retention carve-out, 30-day SLA may mismatch Israeli statutory timeline. [PRIV]
  **DECISION (2026-07-10): Approved, refined.** Frame §7 data-rights fulfillment as done **through the logged-in dashboard** (Google login = identity verification; no separate step needed). For requests by email, require they come **from the account's registered email** (reasonable verification, no bureaucracy). Add a **tax-retention carve-out**: data the operator must retain by law (payment data) is not deleted even on an erasure request. (Drop the heavy standalone "identity-verification step" - replaced by the login/registered-email logic.)
- "מפעיל השירות"/"השירות" defined only in Terms, reused untethered in Privacy (add definitions/incorporation clause). [ENF]
  **DECISION (2026-07-10): Approved** - add a short definitions line at the top of `privacy.html` (or a reference to the Terms) so "מפעיל השירות"/"השירות" are grounded within the privacy policy too.
- Brand/legal dissonance: warm "חבר" marketing vs cold total disclaimer reads as knowing-and-disclaiming. [MED]
  **RESOLVED via C4 + H11** - the care-pathway reframe (C4) + named crisis signposting (H11) align the caring brand with the legal posture. No separate action.

---

## PART 2 - DECISIONS REQUIRED (founder sign-off) - ALL RESOLVED 2026-07-10

1. **Trial length → 14 days** (C1). Fix marketing/CLAUDE.md to 14; terms already 14.
2. **Refund model → no cancellation fee; whole-period billing; no pro-rata except statutory cooling-off** (H4/M7).
3. **Incorporate a בע"מ → DEFERRED** (עוסק פטור, ~0 revenue) (H10/C2).
4. **ED handling → reframe to care-pathway (keep detection + response), not remove** (C4/H11).

---

## PART 3 - FACTS TO VERIFY (claims are only honest if the thing exists)

- [x] Database registration / DPO - **N/A now** (Amendment 13: registration doesn't apply to non-selling databases; notification threshold = 100k sensitive-data subjects). Revisit near 100k. (C3)
- [x] **DPAs** - operator confirmed **none signed** with any provider; wording set accordingly (H2). Action item: sign free OpenAI/Railway/MongoDB DPAs later.
- [x] **Deletion cron** - N/A: auto-deletion commitment REMOVED (R2-07). No cron needed.
- [x] **Billing code** trial window = **14 days** - CONFIRMED (2026-07-13): `health_tracker/config/trial_periods.yaml` default cohort `trial_days: 14`; `logic/subscription_logic.py` `DEFAULT_TRIAL_DAYS = 14`. (C1)
- [x] **`subscription.html`** price wording is plain **"47 ₪"** - CONFIRMED (2026-07-13): renders `SUB_SUBSCRIBE_CTA.format(price)` from config, no "כולל מע\"מ" text. Also verified landing/signup copy = 14 days + 47 ₪ no VAT. (H10/B4)
- [ ] **`support@dugri.life`** mailbox exists and is monitored? (H1) - OPERATIONAL, cannot verify from code. Founder to confirm the mailbox is live + monitored before the docs go public.

---

## PART 4 - PHASED EDIT PLAN (updated to final decisions)

Authoritative wording lives in each finding's DECISION block above. This is the execution order.

### Phase 0 - Code/config fixes (no legal judgment)
- **H1:** set `contact_email = support@dugri.life` in config + `config.example.json`; give `app.py` a non-empty fallback constant; **remove the `{% if contact_email %}` gates** around contact info in both templates.
- **H7:** print "גרסה 1 - בתוקף מ-<date>" in both docs' subtitle, sourced from ONE shared constant (aligned with `consents.version`); stop hardcoding the date.
- Typo "ויידחקו" → "ויישלחו" (`privacy §5`).

### Phase 1 - Terms rewrite (`terms.html`)
- **C1:** trial stays **14 days** (no change here; fix marketing/CLAUDE.md instead).
- **C2 §11:** remove bodily/mental-harm from the excluded list; cap = economic/consequential loss only; broaden §11(ז) carve-out to all non-excludable personal-injury liability. Keep §11(ב) reliance disclaimer.
- **C4/M11 §8:** replace clinical label with observable "דפוסי שימוש חריגים" + care-response wording (encourage help / refer); non-clinical caveat; keep suspension right. (Use the C4 draft block.)
- **H4/M7 §6-§7:** self-serve immediate cancellation via bot/site, stops next charge; **no cancellation fee** (delete "5%/100 ₪"); confirmation sent via bot; whole-period billing; unified refund matrix (M7); cooling-off = pro-rata in text / full refund in practice.
- **H5 §13:** existing-customer marketing model (§30א(ג)) - not opt-in checkbox; commit "פרסומת" + sender details + one-click unsubscribe.
- **H6 §1:** acceptance via signup checkbox (not "use"); material changes require notice.
- **H8 §8:** enumerated grounds (incl. abusive language, misuse, exploit/disparage) tied to "הערכה סבירה"; broader right for non-paying users; drop "מכל סיבה שייראה לו".
- **H9:** severability clause.
- **H10:** remove **"כולל מע\"מ"** everywhere → plain "47 ₪"; add name + address (הזית 28ה, זכרון יעקב); עוסק number on request (no public ת.ז.); consumer-complaint escalation reference.
- **H11 §4:** add ער"ן (1201) + broad professional-referral wording.
- **M6 §9:** service framed as evolving; remedy = free exit, no pro-rata; **add dormant annual-plan clause** (whole-month re-pricing, no fee).
- **M8 §11(ח):** narrow indemnity to third-party claims from user's unlawful use/breach.
- **M9 §7(ב):** general reference to statutory extended-cancellation rights (no hardcoded numbers).
- **M12:** add entire-agreement, assignment, no-waiver, governing-language (Hebrew binding).

### Phase 2 - Privacy rewrite (`privacy.html`)
- **C3:** acknowledge special-sensitivity health data; §8 security = "אמצעים ההולמים את רגישות המידע" (NOT "רמה גבוהה"); remove backups; third-party disclaimer (Google + Telegram); use the C3 draft security block. NO registration/DPO language.
- **H2 §5:** general non-exhaustive provider list; no DPA claims; cross-border-transfer basis (consent + necessity); providers under their own terms. Use the H2 draft block.
- **H3/M1 §3-§4:** internal-use wording (analysts/agents, incl. conversations, detached from name/phone/email); delete "ככל הניתן"/"אנונימי"; basis = consent + necessity; drop "פיתוח טכנולוגי" from legitimate-interest. Use the H3 draft block.
- **M2:** add automated-processing/profiling disclosure (insights, summaries, exceptional-pattern detection) + contact channel.
- **M3 §8:** keep minimal "נודיע כנדרש על פי חוק" (no explicit Authority-notification language).
- **M4 §6:** keep "כל עוד פעיל" + 12+6=18mo inactive rule; keep vague "לפי חוקי המס" for payment data.
- **M5 §10:** keep 18+; (companion: 18+ self-declaration checkbox at signup).
- **M10:** remove the OpenAI-training statement entirely (§3 + §5).
- **LOW:** DSAR via logged-in dashboard / registered-email + tax-retention carve-out; add definitions line for "מפעיל השירות"/"השירות".

### Phase 3 - Companion tasks (outside the two HTMLs) - flagged, not built here unless requested
- Signup page (`landing.html`): §30א(ג) marketing notice + non-blocking refusal (H5); 18+ self-declaration checkbox (M5).
- CLAUDE.md: trial 21→14; retention wording alignment.
- Verify items in Part 3 (billing trial=14, deletion cron, subscription.html price, mailbox).

### Phase 4 - Validation
- CLAUDE.md validation protocol: run `pytest` for touched dashboard areas (esp. template render + contact-render); no regressions.
- Re-read both rendered docs end-to-end for internal consistency (version, trial length, marketing basis, refund matrix, price without VAT).
- Council re-review of the actual HTMLs against this plan.

---

## Cross-document consistency checklist (must all agree after edits)

| Item | Terms | Privacy | CLAUDE.md | Code | Marketing |
|------|-------|---------|-----------|------|-----------|
| Trial length | §6 | - | payment model | billing | landing copy |
| Retention | - | §6 | privacy section | deletion cron | - |
| Marketing consent basis | §13 | §3/§4 | §30א note | signup checkbox | - |
| Contact address | §15 | §1/§7/§12 | config | `contact_email` | - |
| Last-updated date + version | subtitle | subtitle | "עדכון אחרון" | `consents.version` | - |
| Price / VAT | §6/§7 | - | payment model | `subscription.html` | landing copy |

---

## Notes

- Do NOT change legal-checkbox text, habit count, pricing model, color palette, slogan/positioning without explicit founder sign-off (CLAUDE.md).
- Hebrew file encoding: never use PowerShell Set-Content on these files (double-encodes); use Edit.

---

## PART 5 - COUNCIL ROUND 2 (audit of the decisions) - findings + resolutions

Second council pass audited the DECISIONS themselves. Refund matrix confirmed coherent; VAT ripple clean; trial-length outward fix mostly already done (landing.html + billing already 14; only CLAUDE.md stale). Real edges below, resolved one-by-one with the founder.

### Resolved
- **R2-02 Cooling-off wording:** KEEP "החזר יחסי" in the contract (founder may implement pro-rata later). Lawful minimum, no problem. (Reverses the earlier "full refund in practice" note.)
- **R2-04 Notices mechanism:** ADD a notices clause (was dropped in M12). Channel = **Telegram bot** in practice (+ registered email as needed). Gives "נודיע לך" a defined delivery channel that H6/M6/§6 rely on.
- **R2-05 §4/§8 bridging line:** add one reconciling sentence so "awareness-tool-only" (§4) and "we notice patterns and reach out" (§8) don't read as contradictory - frame outreach as a goodwill safety gesture, NOT medical monitoring/diagnosis.

### Open (walking through one-by-one)
- **R2-01 [HIGH, code] Consent-version chain broken → RESOLVED (2026-07-10).** `auth.py::_build_consents()` writes `consent_version` = signup DATE, not the doc version. Fix, two sides:
  - **Display side:** shared constant `DOC_VERSION = "גרסה 1"` rendered in both templates' subtitle (with H7).
  - **Application side:** at signup, write a **static per-user field** `consents.doc_version` as an **integer** (`1`) - economical storage, not the string. **Frozen at the moment of consent**, permanently recording which version that user accepted, even after the doc bumps to 2. The display string "גרסה 1" is derived from the number.
  - Add both to Phase 0 (touches `auth.py` + both templates + the shared constant location).
- **R2-03 [MED] Annual-plan vs cooling-off → RESOLVED (2026-07-10):** within the 14-day cooling-off the annual plan follows cooling-off rules (ordinary pro-rata refund, NO upward re-pricing); only AFTER cooling-off does the used period get re-priced at the standard monthly rate, with whole-month rounding **in the consumer's favor**. Update the dormant annual-plan clause accordingly.
- **R2-06 [HIGH] "סוכנים"/H3 vs C4 → RESOLVED (2026-07-10).** Founder clarified "סוכנים" = **AI agents**. Fixes:
  - **Define the actors:** the review is performed by the operator and by **AI agents/tools operating on the operator's behalf, under its instruction and confidentiality**. Some run via the AI service providers already listed in §5. This is consistent with "we don't transfer to third parties **for their purposes**" - a processor acting for us is permitted; a recipient using it for itself is not.
  - **Reconcile detached vs re-identified:** state that most analysis is done detached from direct identifiers (name/phone/email), BUT in **exceptional safety cases** (C4) identified use may occur in order to reach out to the specific user. Disclose this openly (consistent with the M2 automated-processing disclosure).
  - Both are wording precisions; no change to actual practice.
- **R2-07 [HIGH] Inactive-deletion cron does NOT exist → RESOLVED (2026-07-10): REMOVE the auto-deletion commitment.** Law confirmed: no statutory deadline to proactively delete; duties are (a) purpose-limitation/minimization (soft), (b) honor deletion requests, (c) security. The 18-month auto-deletion was self-imposed and unnecessary. Fix §6:
  - Replace "נמחק אוטומטית אחרי 12+6 חודשים" with: data is retained **while the account exists / as long as relevant**, and the user may request deletion at any time.
  - **No cron to build; no misrepresentation.** (Supersedes M4's 18-month rule.)
  - Keep: user's right to request deletion; error logs 30 days; payment data per tax law.
  - Accepted residual: indefinite retention of sensitive data is a soft minimization point - accepted business call; mitigated by deletion-on-request.
  - Align CLAUDE.md (drop its "עד 18 חודשים" line) and remove the deletion-cron verify item from Part 3.
- **R2-08 [HIGH] Care-response discretionary → RESOLVED (2026-07-10): make it a COMMITMENT, keep the mechanism vague.** Change §8 from "אנו **עשויים** לפנות" (discretionary) to "אנו **פועלים לפי נוהל קבוע** כדי להפנות את המשתמש לעזרה מקצועית מתאימה (כגון ער"ן או אנשי מקצוע מוסמכים)". Rationale:
  - Non-discretionary "we act per a standard" closes the detection-without-response trap.
  - Mechanism stays vague/evolvable: currently exceptional cases are encouraged to reach the operator, who advises those within his competence and refers the rest to ער"ן/professionals; this may change - the text commits to *a referral standard*, not a specific channel.
  - ער"ן named as an example, not the exclusive channel.
  - Suspension stays discretionary; the non-clinical caveat stays.
  - **Sequencing satisfied:** a referral standard already exists operationally, so detection already ships WITH a response - no "detection before response" gap.
  - Draft §8 block:
    > "אם אנו מזהים דפוסי שימוש חריגים שעשויים להצביע על שימוש שאינו מיטיב עם המשתמש, אנו פועלים לפי נוהל קבוע כדי להפנות את המשתמש לעזרה מקצועית מתאימה (כגון קו הסיוע של ער\"ן או אנשי מקצוע מוסמכים). שמורה לנו הזכות להגביל או להשעות שימוש במקרים חריגים שבהם אנו סבורים כי המשך השימוש עלול לפגוע במשתמש. פנייה או הפנייה כאמור אינן מהוות אבחון, ייעוץ רפואי, או הערכה מקצועית."
  - Supersedes the C4 draft block (this is the final §8 wording).
- **R2-09 [HIGH] H3 secondary "sales improvement" basis → RESOLVED (2026-07-10): REMOVE "sales improvement" entirely.** Operator confirmed there is no sales-optimization agent; sales improves indirectly from general product understanding. Dropping the commercial secondary purpose removes the weakest link - internal use is now "service/product improvement + understanding user needs (incl. unmet needs)", which is close to the service purpose and well-covered by consent + transparent §3 disclosure. **No signup-checkbox enumeration needed** anymore. Updated §3 draft (also folds in R2-06 agent definition):
  > "אנו עושים שימוש בנתונים שלך - לרבות תוכן השיחות - לצורך הפעלת השירות, שיפורו, איתור תקלות, והבנת צרכי המשתמשים (כולל צרכים שאינם מקבלים מענה). העיון נעשה על ידי מפעיל השירות והפועלים מטעמו (אנליסטים וסוכני AI הפועלים לפי הוראותינו ומחויבי סודיות), ללא הצמדה לפרטים מזהים ישירים כגון שם, מספר טלפון או כתובת דוא\"ל. השימוש נעשה לצרכים פנימיים בלבד - איננו מוכרים ואיננו מעבירים את נתוניך לצדדים שלישיים לצרכיהם."
  - This supersedes the H3 draft block (removes "שיפור מכירות", adds unmet-needs + AI-agent confidentiality wording).
- **R2-10 [MED] H8-#4 "disparage the service" ground → RESOLVED (2026-07-10): replace "לבזות/להשמיץ" with an unlawful-conduct ground.** Founder's real need (block cursing customers + violent red-flag) is already covered by enumerated ground #1. The bare "disparage/defame" wording risked penalizing lawful criticism (מקפח). Fix:
  - Ground #1 (covers cursing/abuse): "שפה פוגענית, מקללת, **מאיימת** או אלימה".
  - Replace the "לבזות/להשמיץ את השירות" clause in ground #4 with: "**הפצת תוכן מאיים, פוגעני, או בלתי חוקי (לרבות לשון הרע)**". Keep the technical part ("לפגוע במערכת, לחלץ מידע, לנצל פרצות וחולשות").
  - Blocks cursers / threats / unlawful defamation - NOT mere criticism.
  - Keep the "cursing = self-harm signal" rationale OUT of the rendered text (behavioral/conduct ground only, no clinical inference).
- **R2-11 [MED] H8(ג) no-fault operator termination → RESOLVED (2026-07-10): ADD the carve-out.** Operator-initiated closure of a **blameless** paying user (no breach/misuse - operator just chose to stop serving them) → **pro-rata refund**. Termination due to the user's conduct (the H8 grounds) → still NO refund. Removes the one genuinely מקפח-flavored asymmetry; doesn't affect the "abusers get nothing" outcome the founder wanted. **Update M7 matrix row 3** to split: operator no-fault closure → pro-rata; conduct-based termination → no refund.
- **R2-12 [MED] Receipt/קבלה duty → RESOLVED (2026-07-10): operational only, no doc wording.** Operator confirmed receipts are issued per charge (via the clearing provider). No clause added to the terms (not required in-doc). Tracked as an operational obligation, not a text change.
- **R2-13 [LOW] Cross-border transfer basis → ACCEPTED (2026-07-12).** No text change. §5 makes NO DPA claim (removed in H2 - none signed); providers are "under their own terms", transfer basis = consent + necessity. Known residual; real fix = sign the free DPAs later (future action item), then upgrade the wording. Confirmed acceptable.
- **R2-14 [LOW] M5 18+ already bundled → RESOLVED (2026-07-12): keep bundled (Option A).** `CONSENT_TERMS` already contains "ומאשר/ת שאני בן/בת 18 ומעלה" - a valid embedded declaration. No new checkbox/field needed. **This SUPERSEDES M5's "add a self-declaration checkbox" companion task** - the declaration already exists; keep the 18+ wording in privacy §10 / terms §11(ו). No code work.
- **R2-15 [LOW] Sequencing → RESOLVED (2026-07-12) by dropping marketing entirely.** Investigation found the marketing notice ALREADY exists at signup (`CONSENT_MARKETING_NOTICE` in `signup.html`/`hebrew_strings.py`), and 18+ is already in `CONSENT_TERMS` (R2-14). But the §30א(ג) "opportunity to refuse **at collection**" is only partially met (current notice offers unsubscribe-in-every-email, not a refuse-at-signup control). **Founder's decision: do NOT take the §30א risk - remove marketing altogether for now.** This SUPERSEDES H5:
  - **Remove marketing clauses from the docs:** `terms.html §13` and the marketing bullets in `privacy.html §3/§4`. Only operational/transactional messages remain (no consent needed).
  - **Remove `CONSENT_MARKETING_NOTICE` from the signup page** (`signup.html` / `hebrew_strings.py`) - added as a companion task.
  - No marketing sent until a proper opt-in is built later.
  - Sequencing concern dissolves (nothing marketing-related asserted in the text anymore). M5/18+ already handled (R2-14); deletion cron dropped (R2-07).
