"""
test_gem_catalog.py - Tests for wisdom gem data models and catalog.

Expected behavior:
- GemState, GemDelivery, GemFeedback models serialize/deserialize cleanly
- User model with gem_state defaults correctly (no migration needed)
- Catalog loads all 52 gems from wisdom_gems.json
- Every gem has valid categories from the allowed set
- All 5 leagues are populated
- Lookup by id works
- Filter by category returns correct subsets
- Multi-category gems appear in all their categories
"""

from datetime import datetime, timezone

from models.profile import User, GemState, GemDelivery, GemFeedback


# ---------------------------------------------------------------------------
# GemState model tests
# ---------------------------------------------------------------------------

class TestGemStateModel:

    def test_defaults(self):
        gs = GemState()
        assert gs.used_gem_ids == []
        assert gs.cycle_number == 1
        assert gs.last_delivered_at is None
        assert gs.deliveries == []
        assert gs.feedbacks == []
        assert gs.threshold_adjustment == 0.0
        assert gs.week_start_iso is None
        assert gs.gem_delivered_this_week is False
        assert gs.silent_week is False

    def test_delivery_model(self):
        d = GemDelivery(
            gem_id="gem_01",
            category="momentum",
            pattern_key="consistent_logging",
            delivered_at=datetime(2026, 6, 15, tzinfo=timezone.utc),
        )
        assert d.gem_id == "gem_01"
        assert d.category == "momentum"
        assert d.pattern_key == "consistent_logging"

    def test_delivery_model_no_pattern(self):
        d = GemDelivery(
            gem_id="gem_48",
            category="general",
            delivered_at=datetime(2026, 6, 15, tzinfo=timezone.utc),
        )
        assert d.pattern_key is None

    def test_feedback_model(self):
        f = GemFeedback(
            gem_id="gem_01",
            reaction="like",
            reacted_at=datetime(2026, 6, 15, tzinfo=timezone.utc),
        )
        assert f.gem_id == "gem_01"
        assert f.reaction == "like"

    def test_gem_state_serialization(self):
        gs = GemState(
            used_gem_ids=["gem_01", "gem_02"],
            cycle_number=2,
            threshold_adjustment=-0.05,
            gem_delivered_this_week=True,
        )
        d = gs.model_dump(mode="json")
        restored = GemState(**d)
        assert restored.used_gem_ids == ["gem_01", "gem_02"]
        assert restored.cycle_number == 2
        assert restored.threshold_adjustment == -0.05
        assert restored.gem_delivered_this_week is True


class TestUserGemState:

    def test_user_has_gem_state_default(self):
        user = User(email="test@test.com")
        assert isinstance(user.gem_state, GemState)
        assert user.gem_state.cycle_number == 1
        assert user.gem_state.used_gem_ids == []

    def test_user_roundtrip_with_gem_state(self):
        user = User(email="test@test.com")
        user.gem_state.used_gem_ids.append("gem_01")
        user.gem_state.threshold_adjustment = -0.03
        d = user.to_mongo_dict()
        restored = User.from_mongo_dict(d)
        assert restored.gem_state.used_gem_ids == ["gem_01"]
        assert restored.gem_state.threshold_adjustment == -0.03

    def test_user_from_mongo_without_gem_state(self):
        """Legacy docs without gem_state should get clean defaults."""
        doc = {"_id": "test@test.com", "created_at": "2026-01-01T00:00:00+00:00",
               "updated_at": "2026-01-01T00:00:00+00:00"}
        user = User.from_mongo_dict(doc)
        assert isinstance(user.gem_state, GemState)
        assert user.gem_state.cycle_number == 1


# ---------------------------------------------------------------------------
# Gem catalog tests
# ---------------------------------------------------------------------------

VALID_CATEGORIES = {"momentum", "return", "compassion", "streak", "measurement", "general"}


class TestGemCatalog:

    def test_loads_52_gems(self):
        from gem_catalog import ALL_GEMS
        assert len(ALL_GEMS) == 52

    def test_all_gems_have_valid_categories(self):
        from gem_catalog import ALL_GEMS
        for gem in ALL_GEMS:
            for cat in gem.categories:
                assert cat in VALID_CATEGORIES, f"Gem {gem.id} has invalid category '{cat}'"

    def test_all_gems_have_unique_ids(self):
        from gem_catalog import ALL_GEMS
        ids = [g.id for g in ALL_GEMS]
        assert len(ids) == len(set(ids)), "Duplicate gem IDs found"

    def test_all_leagues_populated(self):
        from gem_catalog import ALL_GEMS
        leagues = {g.league for g in ALL_GEMS}
        assert leagues == {1, 2, 3, 4, 5}

    def test_all_gems_have_text(self):
        from gem_catalog import ALL_GEMS
        for gem in ALL_GEMS:
            assert gem.text.strip(), f"Gem {gem.id} has empty text"

    def test_lookup_by_id(self):
        from gem_catalog import get_gem_by_id
        gem = get_gem_by_id("gem_01")
        assert gem is not None
        assert gem.id == "gem_01"

    def test_lookup_by_id_missing(self):
        from gem_catalog import get_gem_by_id
        assert get_gem_by_id("nonexistent") is None

    def test_filter_by_category(self):
        from gem_catalog import get_gems_for_category, ALL_GEMS
        momentum_gems = get_gems_for_category("momentum")
        assert len(momentum_gems) > 0
        for gem in momentum_gems:
            assert "momentum" in gem.categories

    def test_multi_category_gem_appears_in_all(self):
        from gem_catalog import get_gems_for_category, ALL_GEMS
        # Find a gem with multiple categories
        multi = [g for g in ALL_GEMS if len(g.categories) > 1]
        assert len(multi) > 0, "Should have multi-category gems"
        gem = multi[0]
        for cat in gem.categories:
            cat_gems = get_gems_for_category(cat)
            assert gem.id in [g.id for g in cat_gems]

    def test_league_distribution(self):
        """Leagues 1-5 should have 10 gems each (10+10+10+10+12=52)."""
        from gem_catalog import ALL_GEMS
        from collections import Counter
        counts = Counter(g.league for g in ALL_GEMS)
        assert counts[1] == 10
        assert counts[2] == 10
        assert counts[3] == 10
        assert counts[4] == 10
        assert counts[5] == 12
