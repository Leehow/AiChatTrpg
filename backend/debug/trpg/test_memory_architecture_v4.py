"""Architecture-level regression tests for Memory Runtime V4.

Run from repo root:
    PYTHONPATH=backend python backend/debug/trpg/test_memory_architecture_v4.py
"""

from services.trpg_auto_memory import (
    build_structured_event_auto_memory_result,
    build_structured_event_memory_proposals,
)
from services.trpg_context.models import Visibility
from services.trpg_ic_runner import _llm_cache_metrics_from_usage
from services.trpg_memory.legacy_projection import project_committed_auto_memory_to_legacy_state
from services.trpg_memory.memory_models import (
    EvidenceRole,
    MemoryItem,
    MemoryKind,
    MemoryOperation,
    MemoryProposal,
    SourceEvidence,
    TruthStatus,
)
from services.trpg_memory.proposal_validator import MemoryProposalValidator
from services.trpg_npc.models import GameEvent
from services.trpg_runtime.event_sourcing import (
    semantic_event_view,
    semantic_state_changes_for_event,
)
from services.trpg_runtime.turn_output_contract import StateChangeType
from orm.models.game_session import GameSession


def _event(*, visible: bool, content: str = "管家其实是邪教徒。") -> GameEvent:
    return GameEvent(
        event_id="event_secret_clue",
        type="discovery",
        scene_id="scene_1",
        turn_id=1,
        actor_id=None,
        target_ids=[],
        content=content,
        payload={"clue_id": "butler_cultist"},
        visibility={"player_visible": visible, "gm_visible": True},
    )


def test_hidden_structured_discovery_never_becomes_public_auto_memory():
    event = _event(visible=False)
    result = build_structured_event_auto_memory_result([event])
    assert result.events == []
    assert result.discoveries == []

    proposals = build_structured_event_memory_proposals([event], turn_marker="turn_1")
    assert len(proposals) == 1
    assert proposals[0].kind == MemoryKind.CLUE
    assert proposals[0].visibility == Visibility.GM_ONLY
    assert proposals[0].truth_status == TruthStatus.GM_SECRET
    assert proposals[0].source_quotes[0].role == EvidenceRole.STRUCTURED_EVENT


def test_structured_discovery_creates_canonical_clue_state_change():
    event = _event(visible=True, content="玩家发现银钥匙藏在203房床垫下。")
    view = semantic_event_view(event)
    changes = semantic_state_changes_for_event(view, turn_id="turn_1")
    assert len(changes) == 1
    change = changes[0]
    assert change.type == StateChangeType.CLUE_DISCOVERED
    assert change.path == ("clues", "butler_cultist")
    assert change.value["status"] == "discovered"
    assert change.value["player_visible"] is True
    assert change.visibility == Visibility.PARTY_KNOWN


def test_structured_event_evidence_does_not_need_visible_transcript_quote():
    event = _event(visible=True, content="玩家发现银钥匙藏在203房床垫下。")
    proposal = build_structured_event_memory_proposals([event], turn_marker="turn_1")[0]
    issues = MemoryProposalValidator().validate(
        proposal,
        transcript_text="GM: 你看见房间里光线昏暗。",
        confirmed_state_change_ids=(),
    )
    assert not [issue for issue in issues if issue.severity == "error"], issues


def test_prose_clue_low_overlap_is_blocking():
    proposal = MemoryProposal(
        operation=MemoryOperation.ADD,
        kind=MemoryKind.CLUE,
        text="银钥匙藏在203房床垫下。",
        visibility=Visibility.PARTY_KNOWN,
        owner_id=None,
        subject_ids=("party", "silver_key"),
        source_turn_ids=("turn_1",),
        source_quote="窗外雨声越来越大。",
        source_quotes=(
            SourceEvidence(
                text="窗外雨声越来越大。",
                role=EvidenceRole.GM,
                source_turn_id="turn_1",
            ),
        ),
        truth_status=TruthStatus.TRUE,
        confidence=0.9,
    )
    issues = MemoryProposalValidator().validate(
        proposal,
        transcript_text="窗外雨声越来越大。",
        confirmed_state_change_ids=(),
    )
    codes = {issue.code for issue in issues if issue.severity == "error"}
    assert "clue_source_quote_low_overlap" in codes or "clue_without_strong_evidence" in codes


def test_llm_usage_is_normalized_for_trace_cache_metrics():
    metrics = _llm_cache_metrics_from_usage(
        provider="openai",
        model="gpt-test",
        usage={
            "prompt_tokens": 2000,
            "completion_tokens": 300,
            "prompt_tokens_details": {"cached_tokens": 1200},
        },
    )
    assert metrics["usage_available"] is True
    assert metrics["input_tokens"] == 2000
    assert metrics["cached_tokens"] == 1200
    assert abs(metrics["cache_hit_ratio"] - 0.6) < 0.001


def test_legacy_projection_dedupes_reinforced_clues():
    session = GameSession(
        id="session_1",
        user_id="user_1",
        ruleset_id="rules_1",
        memory_state={"player_discoveries": []},
    )
    item = MemoryItem(
        memory_id="mem_silver_key",
        campaign_id="session_1",
        kind=MemoryKind.CLUE,
        text="玩家发现203房间床垫下藏着一枚银钥匙。",
        visibility=Visibility.PARTY_KNOWN,
        owner_id=None,
        subject_ids=("silver_key",),
        source_turn_ids=("turn_1",),
        truth_status=TruthStatus.TRUE,
        metadata={"legacy_bucket": "player_discoveries"},
    )

    project_committed_auto_memory_to_legacy_state(session, [item], turn_marker="turn_1")
    project_committed_auto_memory_to_legacy_state(session, [item], turn_marker="turn_2")

    discoveries = session.memory_state["player_discoveries"]
    assert len(discoveries) == 1
    assert discoveries[0]["turn"] == "turn_2"
    assert discoveries[0]["memory_id"] == "mem_silver_key"


if __name__ == "__main__":
    test_hidden_structured_discovery_never_becomes_public_auto_memory()
    test_structured_discovery_creates_canonical_clue_state_change()
    test_structured_event_evidence_does_not_need_visible_transcript_quote()
    test_prose_clue_low_overlap_is_blocking()
    test_llm_usage_is_normalized_for_trace_cache_metrics()
    test_legacy_projection_dedupes_reinforced_clues()
    print("PASS memory architecture v4 regression tests")
