"""Post-generation runtime pipeline.

Order:
1. validate TurnOutputContract
2. apply confirmed state changes
3. audit narration/state consistency
4. commit valid memory proposals
5. save trace
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from services.trpg_memory.memory_commit_gate import MemoryCommitGate
from services.trpg_memory.memory_models import MemoryCommitResult
from .narrative_state_auditor import AuditWarning, NarrativeStateAuditor
from .state_change_applier import StateApplyResult, StateChangeApplier, WorldStateStore
from .turn_output_contract import TurnOutputContract, validate_turn_contract
from .turn_trace import TurnTrace, TurnTraceStore


@dataclass(frozen=True)
class RuntimePipelineResult:
    contract_issues: tuple[str, ...]
    state_result: StateApplyResult
    audit_warnings: tuple[AuditWarning, ...]
    memory_result: MemoryCommitResult
    trace: TurnTrace | None


class TurnRuntimePipeline:
    def __init__(
        self,
        *,
        world_state_store: WorldStateStore,
        memory_commit_gate: MemoryCommitGate,
        trace_store: TurnTraceStore | None = None,
        state_applier: StateChangeApplier | None = None,
        auditor: NarrativeStateAuditor | None = None,
    ) -> None:
        self.world_state_store = world_state_store
        self.memory_commit_gate = memory_commit_gate
        self.trace_store = trace_store
        self.state_applier = state_applier or StateChangeApplier()
        self.auditor = auditor or NarrativeStateAuditor()

    def process(
        self,
        *,
        campaign_id: str,
        player_input: str,
        contract: TurnOutputContract,
        context_cache_key: str | None = None,
        context_prefix_hash: str | None = None,
        retrieved_context_block_ids: tuple[str, ...] = (),
        visibility_signature: str | None = None,
        cache_metrics: dict[str, object] | None = None,
    ) -> RuntimePipelineResult:
        contract_issues = validate_turn_contract(contract)
        state_result = self.state_applier.apply_and_save(
            store=self.world_state_store,
            campaign_id=campaign_id,
            changes=contract.state_changes,
        )
        audit_warnings = self.auditor.audit(contract.narration, contract.state_changes)
        if contract_issues or state_result.errors:
            confirmed_change_ids = ()
        else:
            confirmed_change_ids = tuple(applied.change.change_id for applied in state_result.applied)
        transcript_text = contract.transcript_text_for_validation(player_input=player_input)
        memory_result = self.memory_commit_gate.commit(
            campaign_id=campaign_id,
            proposals=contract.memory_proposals,
            transcript_text=transcript_text,
            confirmed_state_change_ids=confirmed_change_ids,
        )

        trace: TurnTrace | None = None
        if self.trace_store is not None:
            trace = TurnTrace(
                turn_id=contract.turn_id,
                campaign_id=campaign_id,
                player_input=player_input,
                context_cache_key=context_cache_key,
                context_prefix_hash=context_prefix_hash,
                retrieved_context_block_ids=retrieved_context_block_ids,
                visibility_signature=visibility_signature,
                model_raw_output=contract.raw_model_output,
                parsed_contract_summary={
                    "next_actor": contract.next_actor.value,
                    "waiting_for": contract.waiting_for,
                    "state_change_count": len(contract.state_changes),
                    "npc_message_count": len(contract.npc_messages),
                },
                state_change_ids=confirmed_change_ids,
                memory_proposal_count=len(contract.memory_proposals),
                committed_memory_ids=tuple(item.memory_id for item in memory_result.committed),
                rejected_memory_count=len(memory_result.rejected),
                audit_warnings=tuple(asdict(w) for w in audit_warnings),
                cache_metrics=cache_metrics or {},
            )
            self.trace_store.save(trace)

        return RuntimePipelineResult(
            contract_issues=contract_issues,
            state_result=state_result,
            audit_warnings=audit_warnings,
            memory_result=memory_result,
            trace=trace,
        )
