"""
feedback_service.py — weekly feedback with all-habit coverage and pattern detection.

Generates feedback for the last 7 days in the context of the last 30 days.
Covers food, eating window, sleep, workouts, and self-care.
Detects behavioral patterns and stores them on the user document.
Includes malicious prompt detection for feedback reactions.

Depends on: analyzer, repositories (food, user, feedback, sleep, workout, self_care).
Used by: handlers/base.py.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

from analyzer import FoodAnalyzer
from models.profile import DiscoveredPattern, Strike, User
from parsing import hebrew_day_name
from repositories.food_repository import FoodRepository
from repositories.user_repository import UserRepository
from repositories.feedback_repository import WeeklyFeedbackRepository
from repositories.sleep_repository import SleepRepository
from repositories.workout_repository import WorkoutRepository
from repositories.self_care_repository import SelfCareRepository


class FeedbackService:
    def __init__(
        self,
        analyzer: FoodAnalyzer,
        food_repo: FoodRepository,
        user_repo: UserRepository,
        feedback_repo: WeeklyFeedbackRepository,
        sleep_repo: SleepRepository | None = None,
        workout_repo: WorkoutRepository | None = None,
        self_care_repo: SelfCareRepository | None = None,
    ):
        self._analyzer = analyzer
        self._food_repo = food_repo
        self._user_repo = user_repo
        self._feedback_repo = feedback_repo
        self._sleep_repo = sleep_repo
        self._workout_repo = workout_repo
        self._self_care_repo = self_care_repo

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def give_feedback(
        self,
        telegram_user_id: int,
        today_str: str,
        profile: User,
        is_first_feedback: bool,
    ) -> str:
        """Generate weekly feedback with all-habit coverage and pattern detection."""
        today = datetime.strptime(today_str, "%d/%m/%Y").date()
        all_dates = [(today - timedelta(days=i)).strftime("%d/%m/%Y") for i in range(30)]
        focus_dates = all_dates[:7]

        # --- Gather raw entries ---
        food_entries = self._food_repo.get_by_user_and_dates(telegram_user_id, all_dates)
        if not food_entries:
            return "אין נתונים מהשבוע האחרון לתת עליהם משוב."

        sleep_logs = []
        if self._sleep_repo and profile.toggles.sleep.status == "active":
            sleep_logs = self._sleep_repo.get_recent(telegram_user_id, limit=30)

        workout_logs = []
        if self._workout_repo and profile.toggles.workouts.status == "active":
            workout_logs = self._workout_repo.get_recent(telegram_user_id, limit=30)

        self_care_logs = []
        if self._self_care_repo and profile.toggles.self_care.status == "active":
            self_care_logs = self._self_care_repo.get_recent(telegram_user_id, limit=30)

        # --- Build raw entries for GPT (Layer 1) ---
        raw_entries = self._build_raw_entries(
            food_entries, sleep_logs, workout_logs, self_care_logs, profile,
        )

        # --- Pre-compute summaries (Layer 2) ---
        summaries = self._build_summaries(
            food_entries, sleep_logs, workout_logs, self_care_logs,
            profile, today, focus_dates, all_dates,
        )

        # --- Targets and active toggles ---
        targets = {
            "calories": profile.targets.calories,
            "protein": profile.targets.protein,
            "sleep_time": profile.targets.sleep_time,
            "workouts_per_week": profile.targets.workouts_per_week,
            "weight_goal": profile.targets.weight_goal,
        }

        active_toggles = []
        for name in ["sleep", "eating_window", "workouts", "self_care", "nutrition"]:
            toggle = getattr(profile.toggles, name)
            if toggle.status == "active":
                active_toggles.append(name)

        eating_window = None
        if profile.eating_window:
            eating_window = {"start": profile.eating_window.start, "end": profile.eating_window.end}

        month_stats = {
            "raw_entries": raw_entries,
            "summaries": summaries,
            "targets": targets,
            "active_toggles": active_toggles,
            "eating_window": eating_window,
        }

        # --- Past feedbacks and discovered patterns ---
        past_fb = [
            f.get("feedback_text", "")
            for f in self._feedback_repo.get_recent(telegram_user_id, limit=7)
        ]
        past_patterns = [p.summary for p in profile.discovered_patterns]

        # --- Generate feedback via GPT ---
        feedback_result = self._analyzer.generate_weekly_feedback(
            month_stats, past_fb, past_patterns, profile.feedback_steering_prompt,
        )
        feedback_text = (feedback_result or {}).get("feedback_text", "")
        if not feedback_text:
            return "לא הצלחתי לייצר משוב כרגע."

        # --- Save discovered pattern ---
        discovered_pattern = (feedback_result or {}).get("discovered_pattern")
        pattern_summary = (feedback_result or {}).get("pattern_summary")
        if discovered_pattern and pattern_summary:
            new_pattern = DiscoveredPattern(
                pattern=discovered_pattern,
                summary=pattern_summary,
            )
            self._user_repo.update_fields(telegram_user_id, {
                "discovered_patterns": [
                    p.model_dump(mode="json") for p in profile.discovered_patterns
                ] + [new_pattern.model_dump(mode="json")],
            })

        # --- Save to database ---
        self._feedback_repo.save(
            telegram_user_id=telegram_user_id,
            date_str=today_str,
            feedback_text=feedback_text,
            week_summary=month_stats,
        )

        # --- Closing question ---
        if is_first_feedback:
            closing = (
                "\n\nאיך זה בשבילך? אנחנו עדיין לומדים להכיר - "
                "מה שתגיד לי אחרי פידבקים יכול לשנות גם את הטון וגם את התוכן."
            )
        else:
            closing = "\n\nעבד לך? משהו שהיית רוצה שאתמקד בו יותר או פחות?"

        return f"💬 {feedback_text}{closing}"

    def process_reaction(
        self, telegram_user_id: int, reaction_text: str, current_steering: str | None,
    ) -> str:
        """Process user's reaction to feedback. Detect malicious prompts, then rewrite steering."""
        from prompts import STEERING_REWRITE_PROMPT

        prompt = STEERING_REWRITE_PROMPT.format(
            current_steering=current_steering or "(אין היגוי קיים - זה הפידבק הראשון)",
            user_reaction=reaction_text,
        )

        try:
            response = self._analyzer.client.beta.chat.completions.parse(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": prompt},
                ],
                response_format=SteeringRewriteResult,
                temperature=0,
            )
            result = response.choices[0].message.parsed
            if result is None:
                return "תודה, רשמתי."

            if result.is_malicious:
                # Record strike silently
                strike = Strike(
                    reason="malicious_feedback_reaction",
                    detail=reaction_text,
                    source="feedback_service",
                )
                self._user_repo.push_to_list(telegram_user_id, "strikes", strike.model_dump(mode="json"))
                return "תודה, רשמתי."

            if result.new_steering:
                self._user_repo.update_fields(telegram_user_id, {
                    "feedback_steering_prompt": result.new_steering,
                })
            return "תודה, רשמתי. הפידבק הבא יהיה מותאם יותר."
        except Exception:
            return "תודה, רשמתי."

    def should_offer_weekly(self, last_offered_at: datetime | None, now: datetime) -> bool:
        """Check if it's time for the weekly feedback offer."""
        if last_offered_at is None:
            return True
        return (now - last_offered_at).days >= 7

    def is_first_feedback(self, telegram_user_id: int) -> bool:
        """Check if this is the user's first feedback interaction."""
        recent = self._feedback_repo.get_recent(telegram_user_id, limit=1)
        return len(recent) == 0

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_raw_entries(self, food_entries, sleep_logs, workout_logs, self_care_logs, profile):
        """Build raw entry lists for GPT (Layer 1)."""
        raw = {
            "food": [
                {
                    "date": e.date,
                    "time": e.time,
                    "description": e.description,
                    "calories": e.calories,
                    "protein": e.protein,
                    "within_window": e.within_window,
                }
                for e in food_entries
            ],
        }

        if sleep_logs:
            raw["sleep"] = [
                {"date": l.date, "sleep_time": l.sleep_time}
                for l in sleep_logs
            ]

        if workout_logs:
            raw["workouts"] = [
                {"date": l.date, "note": l.note}
                for l in workout_logs
            ]

        if self_care_logs:
            raw["self_care"] = [
                {"week_id": l.week_id, "description": l.description}
                for l in self_care_logs
            ]

        if profile.eating_window:
            # Per-day eating window compliance from food entries
            by_date = defaultdict(list)
            for e in food_entries:
                by_date[e.date].append(e.within_window)
            raw["eating_window_compliance"] = [
                {"date": date, "kept": all(flags)}
                for date, flags in sorted(by_date.items())
            ]

        return raw

    def _build_summaries(self, food_entries, sleep_logs, workout_logs, self_care_logs,
                         profile, today, focus_dates, all_dates):
        """Build pre-computed summaries for GPT (Layer 2). All arithmetic done here."""
        summaries = {}

        # --- Food summaries per week ---
        by_date = defaultdict(lambda: {"calories": 0, "protein": 0, "meals": 0})
        for e in food_entries:
            by_date[e.date]["calories"] += e.calories
            by_date[e.date]["protein"] += e.protein
            by_date[e.date]["meals"] += 1

        weeks = self._split_into_weeks(all_dates, by_date)
        summaries["food_weekly"] = weeks

        # vs targets (only if set)
        if profile.targets.calories and weeks:
            focus = weeks[0]
            if focus["days_tracked"] > 0:
                summaries["focus_week_cal_pct"] = round(
                    (focus["avg_calories"] / profile.targets.calories) * 100
                )
        if profile.targets.protein and weeks:
            focus = weeks[0]
            if focus["days_tracked"] > 0:
                summaries["focus_week_prot_pct"] = round(
                    (focus["avg_protein"] / profile.targets.protein) * 100
                )

        # --- Eating window compliance per week ---
        if profile.eating_window:
            ew_by_date = defaultdict(list)
            for e in food_entries:
                ew_by_date[e.date].append(e.within_window)

            ew_weeks = []
            for week_dates in self._chunk_dates(all_dates):
                days_with_data = 0
                days_kept = 0
                for d in week_dates:
                    if d in ew_by_date:
                        days_with_data += 1
                        if all(ew_by_date[d]):
                            days_kept += 1
                if days_with_data > 0:
                    ew_weeks.append(f"{days_kept}/{days_with_data}")
                else:
                    ew_weeks.append(None)
            summaries["eating_window_weekly_kept"] = ew_weeks

        # --- Sleep summaries ---
        if sleep_logs:
            sleep_by_week = self._group_logs_by_week(sleep_logs, all_dates, lambda l: l.date)
            sleep_weekly = []
            for week_logs in sleep_by_week:
                if week_logs:
                    times = [l.sleep_time for l in week_logs]
                    sleep_weekly.append({
                        "count": len(times),
                        "avg_sleep_time": self._avg_time(times),
                    })
                else:
                    sleep_weekly.append(None)
            summaries["sleep_weekly"] = sleep_weekly

            if profile.targets.sleep_time and sleep_weekly and sleep_weekly[0]:
                summaries["focus_week_sleep_target"] = profile.targets.sleep_time

        # --- Workout summaries ---
        if workout_logs:
            workout_by_week = self._group_logs_by_week(workout_logs, all_dates, lambda l: l.date)
            workout_weekly = []
            for week_logs in workout_by_week:
                count = len(week_logs) if week_logs else 0
                workout_weekly.append(count)
            summaries["workout_weekly"] = workout_weekly

            if profile.targets.workouts_per_week and workout_weekly:
                summaries["focus_week_workout_ratio"] = (
                    f"{workout_weekly[0]}/{profile.targets.workouts_per_week}"
                )

        # --- Self-care summaries ---
        if self_care_logs:
            # Self-care uses week_id, so just count per week_id
            sc_by_week = defaultdict(int)
            for l in self_care_logs:
                sc_by_week[l.week_id] += 1
            summaries["self_care_by_week"] = dict(sc_by_week)

        return summaries

    def _split_into_weeks(self, all_dates, by_date):
        """Split 30-day data into weekly summaries (most recent first)."""
        weeks = []
        for week_dates in self._chunk_dates(all_dates):
            days_tracked = 0
            total_cal = 0
            total_prot = 0
            for d in week_dates:
                if d in by_date:
                    days_tracked += 1
                    total_cal += by_date[d]["calories"]
                    total_prot += by_date[d]["protein"]
            weeks.append({
                "days_tracked": days_tracked,
                "avg_calories": round(total_cal / days_tracked) if days_tracked else 0,
                "avg_protein": round(total_prot / days_tracked) if days_tracked else 0,
            })
        return weeks

    @staticmethod
    def _chunk_dates(all_dates):
        """Chunk a list of dates into weeks of 7 (last chunk may be shorter)."""
        for i in range(0, len(all_dates), 7):
            yield all_dates[i:i + 7]

    @staticmethod
    def _group_logs_by_week(logs, all_dates, date_fn):
        """Group logs into weekly buckets based on all_dates chunking."""
        date_set_per_week = []
        for i in range(0, len(all_dates), 7):
            date_set_per_week.append(set(all_dates[i:i + 7]))

        result = [[] for _ in date_set_per_week]
        for log in logs:
            log_date = date_fn(log)
            for idx, week_set in enumerate(date_set_per_week):
                if log_date in week_set:
                    result[idx].append(log)
                    break
        return result

    @staticmethod
    def _avg_time(times: list[str]) -> str:
        """Average HH:MM times. Handles midnight crossing (times > 20:00 are 'previous day')."""
        if not times:
            return "00:00"
        total_minutes = 0
        for t in times:
            h, m = int(t.split(":")[0]), int(t.split(":")[1])
            mins = h * 60 + m
            # Treat early morning (0-6) as next-day minutes for averaging
            if h < 6:
                mins += 24 * 60
            total_minutes += mins
        avg = total_minutes // len(times)
        avg = avg % (24 * 60)
        return f"{avg // 60:02d}:{avg % 60:02d}"


# Structured output for steering rewrite with malicious detection
from pydantic import BaseModel


class SteeringRewriteResult(BaseModel):
    is_malicious: bool
    new_steering: str | None = None
    malicious_reason: str | None = None
