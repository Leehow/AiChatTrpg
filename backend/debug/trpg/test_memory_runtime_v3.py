from services.trpg_context.block_store import InMemoryBlockStore
from services.trpg_context.context_builder import ContextBuilder
from services.trpg_context.models import (
    ActorScope,
    ContextProfile,
    ContextRequest,
    DynamicContext,
    Provider,
    Visibility,
)
from services.trpg_memory.memory_identity import stable_idempotency_key
from services.trpg_memory.memory_models import (
    EvidenceRole,
    MemoryIdentityScope,
    MemoryKind,
    MemoryOperation,
    MemoryProposal,
    SourceEvidence,
    TruthStatus,
)
from services.trpg_memory.proposal_validator import MemoryProposalValidator


def _proposal(text: str, turn: str, *, scope=MemoryIdentityScope.DURABLE_FACT):
    return MemoryProposal(
        operation=MemoryOperation.ADD,
        kind=MemoryKind.CLUE,
        text=text,
        visibility=Visibility.PARTY_KNOWN,
        owner_id=None,
        subject_ids=("party", "silver_key"),
        source_turn_ids=(turn,),
        source_quote="银钥匙在203房床垫下。",
        source_quotes=(SourceEvidence(text="银钥匙在203房床垫下。", role=EvidenceRole.GM, source_turn_id=turn),),
        truth_status=TruthStatus.TRUE,
        identity_scope=scope,
    )


def test_durable_memory_identity_ignores_source_turns():
    a = _proposal("银钥匙藏在203房床垫下。", "turn_1")
    b = _proposal("银钥匙藏在203房床垫下。", "turn_2")
    assert stable_idempotency_key("camp", a) == stable_idempotency_key("camp", b)


def test_event_memory_identity_keeps_source_turns():
    a = _proposal("调查员进入旅馆。", "turn_1", scope=MemoryIdentityScope.EVENT)
    b = _proposal("调查员进入旅馆。", "turn_2", scope=MemoryIdentityScope.EVENT)
    assert stable_idempotency_key("camp", a) != stable_idempotency_key("camp", b)


def test_validator_checks_per_proposal_evidence_span():
    proposal = _proposal("银钥匙藏在203房床垫下。", "turn_1")
    issues = MemoryProposalValidator().validate(
        proposal,
        transcript_text="玩家打开窗户，GM描述雨声。",
        confirmed_state_change_ids=(),
    )
    assert any(issue.code == "source_quote_not_in_transcript" for issue in issues)


def test_npc_context_receives_current_observed_turn_text():
    request = ContextRequest(
        actor=ActorScope(profile=ContextProfile.NPC, campaign_id="camp", session_id="sess", scene_id="scene", npc_id="npc_guard"),
        provider=Provider.OPENAI,
        model="test",
        ruleset_id="rules",
        campaign_id="camp",
        dynamic=DynamicContext(
            turn_id="turn_1",
            world_state={"public_fact": "door open", "gm_secret_truth": "killer is butler"},
            recent_transcript=({"role": "user", "content": "我向守卫打招呼。"},),
            current_input="我向守卫打招呼。",
        ),
    )
    compiled = ContextBuilder(InMemoryBlockStore(())).build(request)
    kinds = {block.kind.value for block in compiled.dynamic_blocks}
    assert "current_input" in kinds
    assert "recent_transcript" in kinds
    assert "killer is butler" not in compiled.dynamic_text
