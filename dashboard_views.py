from __future__ import annotations

import hmac
import logging
from datetime import datetime, timedelta, timezone

import requests
from flask import (
    Blueprint, flash, jsonify, render_template, redirect, url_for, request, session, current_app,
)

from auth import login_required
from storage import DashboardStorage
from services.green_invoice import GreenInvoiceService, GreenInvoiceError
from supported_timezones import SUPPORTED_TIMEZONES, DEFAULT_TIMEZONE, is_valid_timezone

logger = logging.getLogger(__name__)

dashboard_bp = Blueprint("dashboard_views", __name__, url_prefix="/dashboard")


def _get_storage() -> DashboardStorage:
    cfg = current_app.config["APP_CONFIG"]
    mongo_cfg = cfg["mongodb"]
    return DashboardStorage(uri=mongo_cfg["uri"], db_name=mongo_cfg["db_name"])


@dashboard_bp.route("/")
@login_required
def index():
    return redirect(url_for("dashboard_views.home"))


@dashboard_bp.route("/home")
@login_required
def home():
    cfg = current_app.config["APP_CONFIG"]
    bot_username = cfg.get("dugri_bot_username", "")
    return render_template(
        "dashboard/home.html", active_tab="home",
        telegram_bot_url=f"https://t.me/{bot_username}",
    )


# ------------------------------------------------------------------
# Preferences (merged toggles + targets)
# ------------------------------------------------------------------

@dashboard_bp.route("/preferences", methods=["GET"])
@login_required
def preferences():
    storage = _get_storage()
    user = storage.get_user(session["user_email"])
    return render_template("dashboard/preferences.html", user=user, active_tab="preferences")


@dashboard_bp.route("/preferences", methods=["POST"])
@login_required
def preferences_post():
    # ---------------------------------------------------------------
    # IMPORTANT: Toggle state invariants
    #
    # The bot's ToggleService (health_tracker/services/toggle_service.py)
    # enforces these invariants when changing toggle status:
    #
    #   activate_toggle() sets: status="active", activated_at=now,
    #                           consecutive_unanswered=0
    #   reveal_toggle()   sets: revealed_at=now
    #   cancel_toggle()   sets: status="cancelled"
    #
    # The dashboard writes directly to MongoDB (no shared service layer
    # with the bot), so it MUST maintain these invariants manually.
    # Failing to do so creates impossible states that break the bot's
    # lazy opt-in flow (e.g. status="active" with activated_at=None
    # makes the bot think a goal flow is pending that was never started).
    #
    # When changing toggle status here, always use _apply_toggle_status()
    # to ensure the right timestamp fields are set.
    # ---------------------------------------------------------------
    storage = _get_storage()
    email = session["user_email"]

    user = storage.get_user(email)
    existing_toggles = user.get("toggles", {}) if user else {}

    toggle_names = ["sleep", "eating_window", "workouts", "self_care", "nutrition", "weekly_summary"]
    toggles = {}
    for name in toggle_names:
        existing = existing_toggles.get(name, {})
        status = request.form.get(f"{name}_status")
        if status in ("dormant", "active", "cancelled"):
            toggles[name] = _apply_toggle_status(existing, status)
        else:
            enabled = request.form.get(f"{name}_enabled")
            if enabled:
                toggles[name] = _apply_toggle_status(existing, "active")
            else:
                toggles[name] = existing or {"status": "dormant"}

    storage.update_user_toggles(email, toggles)

    # Build targets
    cal_str = request.form.get("calories", "").strip()
    prot_str = request.form.get("protein", "").strip()
    calories = int(cal_str) if cal_str else None
    protein = int(prot_str) if prot_str else None

    old_targets = storage.update_user_targets(email, calories, protein)

    # Additional targets: weight_goal, sleep_time, workouts_per_week
    extra = {}
    weight_goal = request.form.get("weight_goal", "").strip()
    if weight_goal in ("lose", "maintain", "gain"):
        extra["targets.weight_goal"] = weight_goal
    elif weight_goal == "":
        extra["targets.weight_goal"] = None

    sleep_target = request.form.get("sleep_target", "").strip()
    if sleep_target:
        extra["targets.sleep_time"] = sleep_target
    workouts_str = request.form.get("workouts_per_week", "").strip()
    if workouts_str:
        extra["targets.workouts_per_week"] = int(workouts_str)

    # Eating window
    ew_start = request.form.get("eating_window_start", "").strip()
    ew_end = request.form.get("eating_window_end", "").strip()
    if ew_start and ew_end and toggles.get("eating_window", {}).get("status") == "active":
        extra["eating_window"] = {"start": ew_start, "end": ew_end}

    if extra:
        storage.update_user_profile(email, extra)

    # Notify bot if calorie/protein targets changed
    new_targets = {"calories": calories, "protein": protein}
    if old_targets.get("calories") != calories or old_targets.get("protein") != protein:
        _notify_bot_target_change(email, old_targets, new_targets)

    return redirect(url_for("dashboard_views.preferences"))


# Legacy redirects
@dashboard_bp.route("/toggles", methods=["GET", "POST"])
@login_required
def toggles():
    return redirect(url_for("dashboard_views.preferences"))


@dashboard_bp.route("/targets", methods=["GET", "POST"])
@login_required
def targets():
    return redirect(url_for("dashboard_views.preferences"))


def _apply_toggle_status(existing: dict, new_status: str) -> dict:
    """Build a toggle dict with the correct timestamp fields for a status change.

    Mirrors the invariants from the bot's ToggleService:
    - dormant:   clear revealed_at, activated_at; reset edu_intro_shown
    - active:    set activated_at (and revealed_at if missing); set edu_intro_shown
    - cancelled: keep timestamps as-is (for historical record)

    Always preserves goal_value, goal_status, and other fields from existing.
    """
    toggle = {**existing, "status": new_status}
    now = datetime.now(timezone.utc).isoformat()

    if new_status == "dormant":
        toggle["revealed_at"] = None
        toggle["activated_at"] = None
        toggle["edu_intro_shown"] = False
        toggle["consecutive_unanswered"] = 0
    elif new_status == "active":
        # Only set timestamps if transitioning TO active (not already active)
        if existing.get("status") != "active":
            toggle["activated_at"] = now
            if not toggle.get("revealed_at"):
                toggle["revealed_at"] = now
            toggle["consecutive_unanswered"] = 0
        toggle["edu_intro_shown"] = True
    # cancelled: preserve existing timestamps, no special fields needed

    return toggle


def _notify_bot_target_change(email: str, old_targets: dict, new_targets: dict):
    """Send target change notification to bot's internal webhook."""
    cfg = current_app.config["APP_CONFIG"]
    bot_url = cfg.get("bot_internal_url", "")
    secret = cfg.get("internal_secret", "")

    if not bot_url:
        return

    user = _get_storage().get_user(email)
    if not user or not user.get("telegram_user_id"):
        return

    try:
        requests.post(
            f"{bot_url}/internal/notify-target-update",
            json={
                "telegram_user_id": user["telegram_user_id"],
                "old_targets": old_targets,
                "new_targets": new_targets,
            },
            headers={"X-Internal-Secret": secret},
            timeout=5,
        )
    except Exception:
        logger.exception("Failed to notify bot about target change")


def _notify_bot_subscription_event(email: str, event: str, user: dict | None = None):
    """Fire an instant, authenticated POST telling the bot to send the subscribe
    ("purchase") or "cancel" lifecycle message in Telegram. Best-effort: the bot
    also has a 72h idempotent scheduler backstop that resends if this POST is
    lost, and dedupes via a sent-flag so nothing double-sends. Non-fatal."""
    cfg = current_app.config["APP_CONFIG"]
    bot_url = cfg.get("bot_internal_url", "")
    secret = cfg.get("internal_secret", "")
    if not bot_url:
        return
    user = user or _get_storage().get_user(email)
    try:
        requests.post(
            f"{bot_url}/internal/notify-subscription-event",
            json={
                "email": email,
                "telegram_user_id": (user or {}).get("telegram_user_id"),
                "event": event,
            },
            headers={"X-Internal-Secret": secret},
            timeout=5,
        )
    except Exception:
        logger.warning("Failed to notify bot about subscription %s event", event,
                       exc_info=True)


# ------------------------------------------------------------------
# Activity history
# ------------------------------------------------------------------

@dashboard_bp.route("/history")
@login_required
def history():
    return render_template("dashboard/history.html", active_tab="history")


# ------------------------------------------------------------------
# Weekly summaries archive
# ------------------------------------------------------------------

@dashboard_bp.route("/weekly-summaries")
@login_required
def weekly_summaries():
    storage = _get_storage()
    email = session["user_email"]
    summaries = storage.get_weekly_summaries(email)
    trend = storage.get_trend_data(email, days=30)
    return render_template(
        "dashboard/weekly_summaries.html",
        summaries=summaries,
        trend_days=trend["days"],
        trend_targets=trend["targets"],
        active_tab="weekly_summaries",
    )


@dashboard_bp.route("/api/trend")
@login_required
def trend_api():
    """JSON endpoint for trend data (calories, protein, workouts)."""
    storage = _get_storage()
    try:
        days = int(request.args.get("days", 30))
    except (ValueError, TypeError):
        days = 30
    if days < 0:
        days = 30
    data = storage.get_trend_data(session["user_email"], days=days)
    return jsonify(data)


# ------------------------------------------------------------------
# Profile (unchanged)
# ------------------------------------------------------------------

@dashboard_bp.route("/profile", methods=["GET"])
@login_required
def profile():
    storage = _get_storage()
    user = storage.get_user(session["user_email"])
    # Dropdown options: the curated list, plus the user's current zone if it was
    # auto-detected to something we don't list (so it still displays as selected).
    current_tz = (user or {}).get("timezone") or DEFAULT_TIMEZONE
    tz_options = list(SUPPORTED_TIMEZONES)
    if current_tz not in tz_options:
        tz_options.insert(0, current_tz)
    return render_template(
        "dashboard/profile.html",
        user=user,
        active_tab="profile",
        timezone_options=tz_options,
        current_timezone=current_tz,
    )


@dashboard_bp.route("/profile", methods=["POST"])
@login_required
def profile_post():
    storage = _get_storage()
    email = session["user_email"]

    profile_data = {}
    name = request.form.get("name", "").strip()
    birth_year = request.form.get("birth_year", "").strip()
    weight_kg = request.form.get("weight_kg", "").strip()
    height_cm = request.form.get("height_cm", "").strip()

    gender = request.form.get("gender", "").strip()

    if name:
        profile_data["name"] = name
        profile_data["onboarding.name_collected"] = True
    else:
        profile_data["name"] = None
    if gender in ("male", "female", "other"):
        profile_data["gender"] = gender
    else:
        profile_data["gender"] = None
    address_form = request.form.get("address_form", "").strip()
    if gender == "other" and address_form in ("male", "female"):
        profile_data["address_form"] = address_form
    elif gender in ("male", "female"):
        profile_data["address_form"] = None
    if birth_year:
        profile_data["birth_year"] = int(birth_year)
    else:
        profile_data["birth_year"] = None
    if weight_kg:
        profile_data["weight_kg"] = int(weight_kg)
    else:
        profile_data["weight_kg"] = None
    if height_cm:
        profile_data["height_cm"] = int(height_cm)
    else:
        profile_data["height_cm"] = None

    # Timezone: written only when the submitted zone actually DIFFERS from the
    # stored one. Diffing (rather than trusting the JS-set source field) means a
    # manual dropdown change persists even if client JS failed to set the source,
    # while an unrelated profile save (unchanged zone) never clobbers the stored
    # provenance/updated_at. The source refines manual vs the banner's confirmed;
    # anything else is treated as manual. Invalid values are silently ignored
    # (house rule: silent errors, server log only).
    tz = request.form.get("timezone", "").strip()
    if tz and is_valid_timezone(tz):
        # Compare against the SAME effective zone the page rendered in the dropdown
        # (a legacy user with no stored timezone key renders the default), so an
        # unrelated save that submits the unchanged default is not misread as a
        # deliberate change that fabricates 'user_manual' provenance.
        stored_tz = (storage.get_user(email) or {}).get("timezone") or DEFAULT_TIMEZONE
        if tz != stored_tz:
            tz_source = request.form.get("timezone_source", "").strip()
            if tz_source not in ("user_manual", "user_confirmed"):
                tz_source = "user_manual"
            profile_data["timezone"] = tz
            profile_data["timezone_source"] = tz_source
            profile_data["timezone_updated_at"] = datetime.now(timezone.utc).isoformat()
    elif tz:
        logger.warning("profile_post: ignoring invalid timezone %r for %s", tz, email)

    storage.update_user_profile(email, profile_data)
    return redirect(url_for("dashboard_views.profile"))


# ------------------------------------------------------------------
# Subscription
# ------------------------------------------------------------------

def _get_gi_service(is_sandbox: bool = False) -> GreenInvoiceService:
    """Build a Green Invoice client for the given environment.

    Test users (user document `sandbox` == True) hit the GI **sandbox** account;
    real users hit the **realdeal** (production) account. Config carries a keyed
    key-set per environment under `green_invoice.sandbox` / `green_invoice.realdeal`.
    Falls back to the legacy flat `api_id`/`api_secret` (+ `sandbox` bool) shape
    when the nested key-sets are absent, so a deploy before the Railway config
    update does not break payments (remove the fallback once Railway is updated).
    """
    gi_cfg = current_app.config["APP_CONFIG"]["green_invoice"]
    env = "sandbox" if is_sandbox else "realdeal"
    keys = gi_cfg.get(env)
    if isinstance(keys, dict) and keys.get("api_id"):
        return GreenInvoiceService(
            api_id=keys["api_id"], api_secret=keys["api_secret"], sandbox=is_sandbox,
        )
    # Legacy flat config (pre-migration).
    return GreenInvoiceService(
        api_id=gi_cfg.get("api_id", ""),
        api_secret=gi_cfg.get("api_secret", ""),
        sandbox=gi_cfg.get("sandbox", True),
    )


def _user_is_sandbox(user: dict | None) -> bool:
    return bool(user and user.get("sandbox", False))


def _subscription_price() -> int:
    cfg = current_app.config["APP_CONFIG"]
    return cfg.get("green_invoice", {}).get("subscription_price_ils", 47)


def _format_date_he(iso_str: str | None) -> str:
    """Format an ISO datetime string as DD/MM/YYYY for Hebrew display."""
    if not iso_str:
        return ""
    try:
        dt = datetime.fromisoformat(str(iso_str))
        return dt.strftime("%d/%m/%Y")
    except (ValueError, TypeError):
        return ""


def _trial_days_left(user: dict | None) -> int | None:
    """Whole days remaining in the trial (ceil, floored at 0), or None when the
    trial expiry is unknown (e.g. trial_pending - not yet started in the bot)."""
    if not user:
        return None
    expiry = user.get("trial_expiry_at")
    if not expiry:
        return None
    try:
        dt = datetime.fromisoformat(str(expiry))
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    secs = (dt - datetime.now(timezone.utc)).total_seconds()
    return max(0, -(-int(secs) // 86400))  # ceil division, never negative


def _activate_paid(storage, email: str, user: dict, gi_document_id: str,
                   amount_shekels, token_id: str | None = None) -> None:
    """Flip a user to a fresh 30-day paid subscription and fire the Meta Purchase
    event. Shared by the IPN webhook and the GI reconcile path so both activate
    identically."""
    now = DashboardStorage._now()
    expires_at = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    fields = {
        "subscription_status": "paid",
        "subscription_gi_document_id": gi_document_id,
        "subscription_started_at": now,
        "subscription_expires_at": expires_at,
        "subscription_last_charged_at": now,
        "subscription_expiry_message_sent": False,
        "subscription_end_acknowledged": False,
        # Genuine non-paid -> paid transition: reset the purchase-message flag so
        # dugri sends the festive congrats (bot dedupes via this flag + a 72h
        # window). _activate_paid is only ever a transition, never a renewal.
        "subscription_purchase_message_sent": False,
    }
    if isinstance(amount_shekels, (int, float)):
        fields["subscription_price_paid"] = int(round(float(amount_shekels) * 100))
    if token_id:
        fields["subscription_token_id"] = token_id
    storage.update_user_profile(email, fields)
    logger.info("Subscription activated for %s (doc %s, token %s)",
                email, gi_document_id, (token_id[:8] if token_id else "none"))

    # Fire the Meta Purchase conversion event (best-effort, deduped by doc/token).
    try:
        import services.meta_capi as meta_capi
        cfg = current_app.config["APP_CONFIG"]
        price = cfg.get("green_invoice", {}).get("subscription_price_ils", 47)
        event_id = meta_capi._sha256(f"purchase:{gi_document_id or token_id or email}")
        outcome = meta_capi.send_event(
            cfg.get("meta", {}),
            email=email,
            event_name="Purchase",
            event_id=event_id,
            user_meta=(user or {}).get("meta"),
            custom_data={"value": price, "currency": "ILS"},
            action_source="website",
        )
        if outcome is not None:
            storage.log_meta_event(
                telegram_user_id=(user or {}).get("telegram_user_id"), user_email=email,
                event_key="paid", event_name="Purchase", action_source="website",
                event_time=None, custom_data={"value": price, "currency": "ILS"},
                **outcome,
            )
    except Exception:
        logger.warning("Meta Purchase event failed (non-fatal)", exc_info=True)

    # Tell the bot to send the festive subscribe message (instant push; the bot
    # has a backstop + dedupe). Fires on first purchase AND re-subscribe, never
    # on a renewal (renewals never call _activate_paid).
    _notify_bot_subscription_event(email, "purchase", user)


def _reconcile_paid_from_gi(storage, user: dict | None) -> bool:
    """Activate a subscription by confirming a settled receipt in GI, WITHOUT
    relying on GI's IPN push (which is not reliably delivered). Runs on the
    subscription page load: if a non-paid user has a fresh receipt for the plan
    price, flip them to paid. Returns True if it activated. Idempotent - once
    paid, the status guard skips it; the doc-id guard prevents re-consuming the
    same receipt."""
    if not user:
        return False
    if user.get("subscription_status") in ("paid", "cancelled"):
        return False
    email = user.get("_id")
    if not email:
        return False
    try:
        gi = _get_gi_service(_user_is_sandbox(user))
        receipt = gi.find_recent_receipt(email, _subscription_price())
    except Exception:
        logger.warning("reconcile: GI lookup failed (non-fatal)", exc_info=True)
        return False
    if not receipt:
        return False
    doc_id = receipt.get("id")
    if doc_id and doc_id == user.get("subscription_gi_document_id"):
        return False  # already consumed this receipt
    _activate_paid(storage, email, user, doc_id, receipt.get("amount"))
    logger.info("Reconciled paid from GI receipt %s for %s", doc_id, email)
    return True


@dashboard_bp.route("/subscription")
@login_required
def subscription():
    import hebrew_strings as hs

    storage = _get_storage()
    email = session["user_email"]
    user = storage.get_user(email)
    # Reconcile a missed activation: if the user paid but GI's IPN never arrived,
    # confirm the payment against GI and activate now, so the page reflects reality
    # instead of showing the trial state after a successful payment.
    if _reconcile_paid_from_gi(storage, user):
        user = storage.get_user(email)

    cfg = current_app.config["APP_CONFIG"]
    price = _subscription_price()
    contact_email = cfg.get("contact_email", "")

    status = user.get("subscription_status", "trial_pending") if user else "trial_pending"
    expires_at = _format_date_he(user.get("subscription_expires_at")) if user else ""

    return render_template(
        "dashboard/subscription.html",
        user=user,
        active_tab="subscription",
        price=price,
        status=status,
        expires_at=expires_at,
        trial_days_left=_trial_days_left(user),
        contact_email=contact_email,
        hs=hs,
    )


@dashboard_bp.route("/subscription/start", methods=["POST"])
@login_required
def subscription_start():
    """Generate Green Invoice payment form URL and redirect user."""
    storage = _get_storage()
    email = session["user_email"]
    user = storage.get_user(email)

    price = _subscription_price()
    is_sandbox = _user_is_sandbox(user)
    env = "sandbox" if is_sandbox else "realdeal"
    base_url = request.url_root.rstrip("/")
    success_url = f"{base_url}{url_for('dashboard_views.subscription_success')}"
    failure_url = f"{base_url}{url_for('dashboard_views.subscription_failure')}"
    # Tag the IPN callback with the environment so the (session-less) webhook
    # verifies against the same GI account this user is paying through.
    notify_url = f"{base_url}{url_for('dashboard_views.subscription_webhook')}?env={env}"

    try:
        gi = _get_gi_service(is_sandbox)
        form_url = gi.get_payment_form_url(
            user_email=email,
            user_name=user.get("name", "") if user else "",
            amount_ils=price,
            success_url=success_url,
            failure_url=failure_url,
            notify_url=notify_url,
        )
        return redirect(form_url)
    except GreenInvoiceError:
        logger.exception("Failed to create payment form")
        import hebrew_strings as hs
        flash(hs.SUB_FAILURE_FLASH, "error")
        return redirect(url_for("dashboard_views.subscription"))


@dashboard_bp.route("/subscription/success")
@login_required
def subscription_success():
    import hebrew_strings as hs
    flash(hs.SUB_SUCCESS_FLASH, "success")
    return redirect(url_for("dashboard_views.subscription"))


@dashboard_bp.route("/subscription/failure")
@login_required
def subscription_failure():
    import hebrew_strings as hs
    flash(hs.SUB_FAILURE_FLASH, "error")
    return redirect(url_for("dashboard_views.subscription"))


@dashboard_bp.route("/subscription/cancel", methods=["POST"])
@login_required
def subscription_cancel():
    """Cancel subscription - keeps access until period ends."""
    storage = _get_storage()
    email = session["user_email"]
    user = storage.get_user(email)

    if user and user.get("subscription_status") == "paid":
        storage.update_user_profile(email, {
            "subscription_status": "cancelled",
            "subscription_cancelled_at": DashboardStorage._now(),
            # Reset so dugri sends the cancel confirmation (bot dedupes + backstop).
            "subscription_cancel_message_sent": False,
        })
        # Tell the bot to send the cancel confirmation message (instant push).
        _notify_bot_subscription_event(email, "cancel", user)

    return redirect(url_for("dashboard_views.subscription"))


@dashboard_bp.route("/subscription/webhook", methods=["POST"])
def subscription_webhook():
    """Green Invoice IPN webhook - called by GI after a payment.

    Hardened + instrumented. The previous version hard-required ``?gi-type=ipn``
    and trusted the body's ``custom``/``tokenId`` with no logging, so any
    format mismatch dropped the call silently - no payment was ever recorded
    (0 paid users, 0 tokens, 0 Purchase events in prod). This version:
      - ALWAYS logs the raw request to ``webhook_logs`` (ground truth on GI's
        real IPN format), so a mismatch is visible and fixable, not invisible.
      - does NOT gate solely on ``gi-type``; it detects a payment by content.
      - VERIFIES a document id against GI's authenticated API before flipping
        anyone to paid: the paying email + amount come from the authoritative
        GI document, never the untrusted IPN body (anti-spoof, Finding #1).
    """
    args = dict(request.args)
    body_json = request.get_json(silent=True)
    body_form = request.form.to_dict()
    data = body_json if isinstance(body_json, dict) else (body_form or {})
    merged = {**args, **data}  # GI may echo fields as query params or body

    def pick(*keys):
        for k in keys:
            v = merged.get(k)
            if v:
                return v
        return ""

    document_id = pick("id", "documentId", "docId", "document_id", "document")
    custom_email = pick("custom", "email")
    token_id = pick("tokenId", "token_id", "token", "cardToken")

    storage = _get_storage()

    # Authoritative check: re-fetch the document from GI's authenticated API. We
    # NEVER flip a user to paid on the untrusted IPN body alone - the paying
    # email, amount and settled-status all come from the verified GI document
    # (review-fixes Finding #1: bind the document to the user + price, else a
    # settled document id presented for custom=<victim> would flip the victim).
    # Route to the GI account this payment went through: the env is tagged on the
    # notifyUrl at form-creation time (?env=sandbox|realdeal); default realdeal.
    is_sandbox = request.args.get("env") == "sandbox"
    verified_doc = None
    try:
        if document_id:
            verified_doc = _get_gi_service(is_sandbox).verify_payment(document_id)
    except Exception:
        logger.warning("verify_payment raised (non-fatal)", exc_info=True)

    outcome = "ignored"
    email = ""
    if verified_doc:
        client = verified_doc.get("client") or {}
        emails = client.get("emails") or []
        email = emails[0] if emails else ""
        # GI `amount` is in major units (shekels), confirmed against a real
        # document. Require it to equal the plan price so an arbitrary settled
        # document cannot activate a subscription (Finding #1 + #4).
        amount = verified_doc.get("amount")
        expected = _subscription_price()
        price_ok = isinstance(amount, (int, float)) and int(amount) == int(expected)
        user = storage.get_user(email) if email else None

        if not email or not user:
            outcome = "user_not_found"
            logger.warning("Payment webhook: no user for GI doc %s email %r",
                           document_id, email)
        elif not price_ok:
            outcome = "amount_mismatch"
            logger.warning("Payment webhook: doc %s amount %r != price %r",
                           document_id, amount, expected)
        else:
            _activate_paid(storage, email, user, document_id, amount, token_id=token_id)
            outcome = "paid"

    # Always record the raw call + what we did, for diagnosis.
    storage.log_webhook(
        args=args, json=body_json, form=body_form,
        headers={k: v for k, v in request.headers.items()
                 if k.lower() not in ("cookie", "authorization")},
        outcome=outcome, matched_email=(email if outcome == "paid" else ""),
        document_id=document_id, verified=bool(verified_doc),
    )
    return jsonify({"status": outcome}), 200
