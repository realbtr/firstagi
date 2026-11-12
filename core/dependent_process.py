"""Derived view of dependent processes over the operation ledger.

Design: docs/design/DEPENDENT_PROCESS_v0_1.md, section 2 (package P1-a).

A pure read. Nothing is stored and no behaviour of the core changes: the view
is recomputed from observed operation records and the actual evidence of Gens.
A bifurcation point is a (instance, channel, cue, operation) with observed
executions that reached different outcomes.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass(frozen=True)
class ProcessView:
    instance_id: str
    channel_id: str
    cue_gen_id: str
    operation_gen_id: str
    executions: int                    # observed executions at this point
    cancelled: int                     # begun and cancelled, no evidence
    outcomes: Tuple[str, ...]          # distinct outcome Gen ids, first-seen order
    detected_seq: Optional[int]        # first execution whose outcome differed
    hidden_executions: int             # observed executions before detection
    failed_forecasts_at_detection: int
    failed_admitted_at_detection: int  # of those, from Gens admitted at that time
    resolution_attempts: int           # P1-a has no resolution rule: always 0

    @property
    def is_bifurcation(self) -> bool:
        return len(self.outcomes) > 1

    @property
    def status(self) -> str:
        """P1-a knows only whether a process exists; terminations come later."""
        return "active" if self.is_bifurcation else "none"


def _admitted_before(gen, scope, seq) -> bool:
    """N3a admission recomputed from evidence strictly earlier than seq."""
    entries = [e for (inst, chan, s), e in getattr(gen, "actual_evidence", {}).items()
               if (inst, chan) == scope and s < seq]
    positive = sum(e.positive for e in entries)
    return (sum(e.origin for e in entries) == 1 and positive >= 2
            and positive / len(entries) > 0.5)


def process_views(system) -> Tuple[ProcessView, ...]:
    """One view per point that has at least one observed or cancelled operation."""
    system._operation_state()
    points = {}
    for (instance_id, channel_id, seq), record in sorted(
            system._operation_records.items(), key=lambda item: item[0][2]):
        pending = record.pending
        key = (instance_id, channel_id, pending.cue_gen_id, pending.operation_gen_id)
        points.setdefault(key, []).append((seq, record))

    views = []
    for (instance_id, channel_id, cue, operation), rows in points.items():
        scope = (instance_id, channel_id)
        observed = [(seq, r) for seq, r in rows if r.status == "observed"]
        outcomes = tuple(dict.fromkeys(r.receipt.outcome_gen_id for _, r in observed))
        detected = failed = failed_admitted = None
        if len(outcomes) > 1:
            detected, record = next(
                (seq, r) for seq, r in observed if r.receipt.outcome_gen_id != outcomes[0])
            wrong = [gid for gid, goal, _, _ in record.pending.forecasts
                     if goal != record.receipt.outcome_gen_id]
            failed = len(wrong)
            failed_admitted = sum(
                _admitted_before(system.base.get(gid), scope, detected)
                for gid in wrong if system.base.get(gid) is not None)
        views.append(ProcessView(
            instance_id, channel_id, cue, operation,
            executions=len(observed),
            cancelled=sum(r.status == "cancelled" for _, r in rows),
            outcomes=outcomes,
            detected_seq=detected,
            hidden_executions=(sum(seq < detected for seq, _ in observed)
                               if detected is not None else len(observed)),
            failed_forecasts_at_detection=failed or 0,
            failed_admitted_at_detection=failed_admitted or 0,
            resolution_attempts=0,
        ))
    return tuple(views)
