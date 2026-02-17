"""Tests for story-domain DAOs (Phase S0)."""

import pytest
from data.db import get_initialized_connection
from data.dao_story_worlds import (
    insert_world,
    get_world,
    update_world,
    increment_episode_number,
)
from data.dao_characters import (
    insert_character,
    get_character,
    get_characters_for_world,
    update_character,
    update_arc_stage,
    VALID_ARC_STAGES,
)
from data.dao_threads import (
    insert_thread,
    get_thread,
    get_threads_for_world,
    get_open_threads,
    resolve_thread,
    add_escalation_point,
    update_thread_status,
)
from data.dao_episodes import (
    insert_episode,
    get_episode,
    get_episodes_for_world,
    get_latest_episode,
    update_episode_status,
    update_episode,
)


@pytest.fixture
def conn():
    c = get_initialized_connection(":memory:")
    yield c
    c.close()


# ------------------------------------------------------------------
# Schema migration test
# ------------------------------------------------------------------

def test_schema_creates_story_tables(conn):
    """Verify get_initialized_connection creates story tables alongside existing ones."""
    tables = {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    for expected in ("story_worlds", "characters", "narrative_threads", "episodes"):
        assert expected in tables, f"Missing table: {expected}"
    # Also verify existing tables still exist
    for expected in ("source_docs", "claims", "entities"):
        assert expected in tables, f"Missing existing table: {expected}"


# ------------------------------------------------------------------
# dao_story_worlds tests
# ------------------------------------------------------------------

def _make_world(conn, world_id="w1", **overrides):
    defaults = dict(
        world_id=world_id,
        name="Eldoria",
        genre="fantasy",
        tone="whimsical",
        setting={"geography": "floating islands"},
        thematic_constraints=["friendship", "courage"],
        audience_profile={"age_range": "8-12", "vocabulary_level": "intermediate"},
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
    )
    defaults.update(overrides)
    insert_world(conn, **defaults)


def test_insert_and_get_world(conn):
    _make_world(conn)
    w = get_world(conn, "w1")
    assert w is not None
    assert w["name"] == "Eldoria"
    assert w["genre"] == "fantasy"
    assert w["tone"] == "whimsical"
    assert w["current_episode_number"] == 0
    assert w["current_timeline_position"] == "start"


def test_get_missing_world(conn):
    assert get_world(conn, "nope") is None


def test_world_audience_profile_deserialization(conn):
    _make_world(conn, audience_profile={"age_range": "8-12", "vocabulary_level": "intermediate", "tolerance_for_violence": "mild"})
    w = get_world(conn, "w1")
    assert isinstance(w["audience_profile_json"], dict)
    assert w["audience_profile_json"]["age_range"] == "8-12"
    assert w["audience_profile_json"]["tolerance_for_violence"] == "mild"


def test_world_setting_deserialization(conn):
    _make_world(conn, setting={"geography": "islands", "magic": True})
    w = get_world(conn, "w1")
    assert isinstance(w["setting_json"], dict)
    assert w["setting_json"]["magic"] is True


def test_world_thematic_constraints_deserialization(conn):
    _make_world(conn, thematic_constraints=["friendship", "courage", "sacrifice"])
    w = get_world(conn, "w1")
    assert isinstance(w["thematic_constraints_json"], list)
    assert len(w["thematic_constraints_json"]) == 3


def test_update_world(conn):
    _make_world(conn)
    update_world(conn, "w1", name="New Eldoria", tone="dark", updated_at="2026-02-01T00:00:00Z")
    w = get_world(conn, "w1")
    assert w["name"] == "New Eldoria"
    assert w["tone"] == "dark"
    assert w["genre"] == "fantasy"  # unchanged


def test_update_world_no_fields(conn):
    _make_world(conn)
    update_world(conn, "w1")  # no-op, should not raise


def test_increment_episode_number(conn):
    _make_world(conn)
    assert get_world(conn, "w1")["current_episode_number"] == 0
    n = increment_episode_number(conn, "w1")
    assert n == 1
    n = increment_episode_number(conn, "w1")
    assert n == 2
    assert get_world(conn, "w1")["current_episode_number"] == 2


# ------------------------------------------------------------------
# dao_characters tests
# ------------------------------------------------------------------

def _make_character(conn, character_id="c1", world_id="w1", **overrides):
    defaults = dict(
        character_id=character_id,
        world_id=world_id,
        name="Aria",
        role="protagonist",
        traits=["brave", "curious"],
        goals=["find the lost gem"],
        fears=["darkness"],
        beliefs=["magic is real"],
    )
    defaults.update(overrides)
    insert_character(conn, **defaults)


def test_insert_and_get_character(conn):
    _make_world(conn)
    _make_character(conn)
    c = get_character(conn, "c1")
    assert c is not None
    assert c["name"] == "Aria"
    assert c["role"] == "protagonist"
    assert c["arc_stage"] == "introduction"
    assert c["alive"] is True
    assert c["traits_json"] == ["brave", "curious"]
    assert c["goals_json"] == ["find the lost gem"]
    assert c["fears_json"] == ["darkness"]
    assert c["beliefs_json"] == ["magic is real"]


def test_get_characters_for_world(conn):
    _make_world(conn)
    _make_character(conn, character_id="c1", name="Aria")
    _make_character(conn, character_id="c2", name="Bram", role="supporting")
    chars = get_characters_for_world(conn, "w1")
    assert len(chars) == 2
    names = [c["name"] for c in chars]
    assert "Aria" in names
    assert "Bram" in names


def test_get_characters_empty_world(conn):
    _make_world(conn)
    assert get_characters_for_world(conn, "w1") == []


def test_update_character(conn):
    _make_world(conn)
    _make_character(conn)
    update_character(conn, "c1", name="Aria the Bold", goals=["save the kingdom"])
    c = get_character(conn, "c1")
    assert c["name"] == "Aria the Bold"
    assert c["goals_json"] == ["save the kingdom"]
    assert c["traits_json"] == ["brave", "curious"]  # unchanged


def test_update_character_alive(conn):
    _make_world(conn)
    _make_character(conn)
    update_character(conn, "c1", alive=False)
    c = get_character(conn, "c1")
    assert c["alive"] is False


def test_arc_stage_valid_transitions(conn):
    _make_world(conn)
    _make_character(conn)  # starts at "introduction"
    update_arc_stage(conn, "c1", "rising")
    assert get_character(conn, "c1")["arc_stage"] == "rising"
    update_arc_stage(conn, "c1", "crisis")
    assert get_character(conn, "c1")["arc_stage"] == "crisis"
    update_arc_stage(conn, "c1", "resolution")
    assert get_character(conn, "c1")["arc_stage"] == "resolution"
    update_arc_stage(conn, "c1", "transformed")
    assert get_character(conn, "c1")["arc_stage"] == "transformed"


def test_arc_stage_skip_disallowed(conn):
    _make_world(conn)
    _make_character(conn)  # starts at "introduction"
    with pytest.raises(ValueError, match="Invalid arc transition"):
        update_arc_stage(conn, "c1", "crisis")  # skips "rising"


def test_arc_stage_backward_disallowed(conn):
    _make_world(conn)
    _make_character(conn)
    update_arc_stage(conn, "c1", "rising")
    with pytest.raises(ValueError, match="Invalid arc transition"):
        update_arc_stage(conn, "c1", "introduction")  # going backwards


def test_arc_stage_same_disallowed(conn):
    _make_world(conn)
    _make_character(conn)
    with pytest.raises(ValueError, match="Invalid arc transition"):
        update_arc_stage(conn, "c1", "introduction")  # same stage


def test_arc_stage_invalid_value(conn):
    _make_world(conn)
    _make_character(conn)
    with pytest.raises(ValueError, match="Invalid arc_stage"):
        update_arc_stage(conn, "c1", "bogus")


def test_arc_stage_missing_character(conn):
    _make_world(conn)
    with pytest.raises(ValueError, match="Character not found"):
        update_arc_stage(conn, "c999", "rising")


def test_insert_character_invalid_arc_stage(conn):
    _make_world(conn)
    with pytest.raises(ValueError, match="Invalid arc_stage"):
        _make_character(conn, arc_stage="bogus")


# ------------------------------------------------------------------
# dao_threads tests
# ------------------------------------------------------------------

def _make_thread(conn, thread_id="t1", world_id="w1", **overrides):
    defaults = dict(
        thread_id=thread_id,
        world_id=world_id,
        title="The Missing Gem",
        introduced_in_episode=1,
        thematic_tag="mystery",
        related_character_ids=["c1"],
    )
    defaults.update(overrides)
    insert_thread(conn, **defaults)


def test_insert_and_get_thread(conn):
    _make_world(conn)
    _make_thread(conn)
    t = get_thread(conn, "t1")
    assert t is not None
    assert t["title"] == "The Missing Gem"
    assert t["status"] == "open"
    assert t["introduced_in_episode"] == 1
    assert t["resolved_in_episode"] is None
    assert t["thematic_tag"] == "mystery"
    assert t["related_character_ids_json"] == ["c1"]
    assert t["escalation_points_json"] == []


def test_get_threads_for_world(conn):
    _make_world(conn)
    _make_thread(conn, thread_id="t1", introduced_in_episode=1)
    _make_thread(conn, thread_id="t2", title="The Dark Forest", introduced_in_episode=2)
    threads = get_threads_for_world(conn, "w1")
    assert len(threads) == 2
    assert threads[0]["introduced_in_episode"] == 1
    assert threads[1]["introduced_in_episode"] == 2


def test_get_open_threads(conn):
    _make_world(conn)
    _make_thread(conn, thread_id="t1")
    _make_thread(conn, thread_id="t2", title="Resolved Thread")
    resolve_thread(conn, "t2", resolved_in_episode=3)
    open_threads = get_open_threads(conn, "w1")
    assert len(open_threads) == 1
    assert open_threads[0]["thread_id"] == "t1"


def test_thread_lifecycle(conn):
    """Test: open -> escalating -> climax -> resolved."""
    _make_world(conn)
    _make_thread(conn)
    t = get_thread(conn, "t1")
    assert t["status"] == "open"

    update_thread_status(conn, "t1", status="escalating")
    t = get_thread(conn, "t1")
    assert t["status"] == "escalating"

    update_thread_status(conn, "t1", status="climax")
    t = get_thread(conn, "t1")
    assert t["status"] == "climax"

    resolve_thread(conn, "t1", resolved_in_episode=5)
    t = get_thread(conn, "t1")
    assert t["status"] == "resolved"
    assert t["resolved_in_episode"] == 5


def test_add_escalation_point(conn):
    _make_world(conn)
    _make_thread(conn)
    add_escalation_point(conn, "t1", escalation_point={"episode": 2, "event": "gem discovered to be fake"})
    add_escalation_point(conn, "t1", escalation_point={"episode": 3, "event": "real gem found in cave"})
    t = get_thread(conn, "t1")
    assert len(t["escalation_points_json"]) == 2
    assert t["escalation_points_json"][0]["episode"] == 2
    assert t["escalation_points_json"][1]["episode"] == 3


def test_add_escalation_point_missing_thread(conn):
    _make_world(conn)
    with pytest.raises(ValueError, match="Thread not found"):
        add_escalation_point(conn, "t999", escalation_point={"episode": 1, "event": "test"})


# ------------------------------------------------------------------
# dao_episodes tests
# ------------------------------------------------------------------

def _make_episode(conn, episode_id="ep1", world_id="w1", **overrides):
    defaults = dict(
        episode_id=episode_id,
        world_id=world_id,
        episode_number=1,
        title="The Journey Begins",
        act_structure=[{"act": 1, "scenes": ["s1", "s2"]}, {"act": 2, "scenes": ["s3"]}],
        scene_count=3,
        word_count=2500,
        tension_curve=[{"scene": "s1", "tension": 0.3}, {"scene": "s2", "tension": 0.6}, {"scene": "s3", "tension": 0.9}],
        created_at="2026-01-01T00:00:00Z",
    )
    defaults.update(overrides)
    insert_episode(conn, **defaults)


def test_insert_and_get_episode(conn):
    _make_world(conn)
    _make_episode(conn)
    ep = get_episode(conn, "ep1")
    assert ep is not None
    assert ep["title"] == "The Journey Begins"
    assert ep["episode_number"] == 1
    assert ep["scene_count"] == 3
    assert ep["word_count"] == 2500
    assert ep["status"] == "draft"
    assert isinstance(ep["act_structure_json"], list)
    assert len(ep["act_structure_json"]) == 2
    assert isinstance(ep["tension_curve_json"], list)
    assert len(ep["tension_curve_json"]) == 3


def test_get_episodes_for_world(conn):
    _make_world(conn)
    _make_episode(conn, episode_id="ep1", episode_number=1)
    _make_episode(conn, episode_id="ep2", episode_number=2, title="The Dark Cave")
    eps = get_episodes_for_world(conn, "w1")
    assert len(eps) == 2
    assert eps[0]["episode_number"] == 1
    assert eps[1]["episode_number"] == 2


def test_get_latest_episode(conn):
    _make_world(conn)
    _make_episode(conn, episode_id="ep1", episode_number=1)
    _make_episode(conn, episode_id="ep2", episode_number=2, title="The Dark Cave")
    latest = get_latest_episode(conn, "w1")
    assert latest is not None
    assert latest["episode_id"] == "ep2"
    assert latest["episode_number"] == 2


def test_get_latest_episode_empty(conn):
    _make_world(conn)
    assert get_latest_episode(conn, "w1") is None


def test_update_episode_status(conn):
    _make_world(conn)
    _make_episode(conn)
    update_episode_status(conn, "ep1", status="final")
    ep = get_episode(conn, "ep1")
    assert ep["status"] == "final"


def test_update_episode(conn):
    _make_world(conn)
    _make_episode(conn)
    update_episode(conn, "ep1", title="New Title", word_count=3000, snapshot_id="snap-1")
    ep = get_episode(conn, "ep1")
    assert ep["title"] == "New Title"
    assert ep["word_count"] == 3000
    assert ep["snapshot_id"] == "snap-1"
    assert ep["scene_count"] == 3  # unchanged


def test_update_episode_no_fields(conn):
    _make_world(conn)
    _make_episode(conn)
    update_episode(conn, "ep1")  # no-op, should not raise
