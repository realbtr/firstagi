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
    resolution_attempts: int = 0       # executed + refused resolution requests at this cue
    resolution_refused: int = 0

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


def process_views(system, resolution_operation_gen_id: Optional[str] = None
                  ) -> Tuple[ProcessView, ...]:
    """One view per point that has at least one observed or cancelled operation.

    If the protocol's resolution request is named, its attempts from the same
    cue are counted for every other point of that cue: executed requests and
    requests the driver refused. A request that found no slot is not an attempt.
    """
    system._operation_state()
    refused_keys = {(r.instance_id, r.channel_id, r.seq)
                    for r in system._operation_deliveries.values()
                    if r.status == "unavailable"}
    points = {}
    for (instance_id, channel_id, seq), record in sorted(
            system._operation_records.items(), key=lambda item: item[0][2]):
        pending = record.pending
        key = (instance_id, channel_id, pending.cue_gen_id, pending.operation_gen_id)
        points.setdefault(key, []).append((seq, record))

    attempts = {}
    if resolution_operation_gen_id is not None:
        for (instance_id, channel_id, cue, operation), rows in points.items():
            if operation != resolution_operation_gen_id:
                continue
            refused = sum((instance_id, channel_id, seq) in refused_keys for seq, _ in rows)
            executed = sum(r.status == "observed" for _, r in rows)
            attempts[(instance_id, channel_id, cue)] = (executed + refused, refused)

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
            resolution_attempts=(0 if operation == resolution_operation_gen_id
                                 else attempts.get((instance_id, channel_id, cue), (0, 0))[0]),
            resolution_refused=(0 if operation == resolution_operation_gen_id
                                else attempts.get((instance_id, channel_id, cue), (0, 0))[1]),
        ))
    return tuple(views)


def resolution_due(system, *, instance_id: str, channel_id: str, cue_gen_id: str,
                   operation_gen_id: str) -> bool:
    """P1-b bid rule: request a nested region when the command is about to run
    from a bifurcation point.

    The condition is the point itself (different observed outcomes), not the
    ambiguous-command predicate: with balanced branches only one of the two
    Gens stays admitted, so no admitted forecasts conflict. Terminations
    (resolved, suppressed) belong to P1-c; here a point never stops being due.
    The scan is over the whole ledger: a metered full read, not a local index.
    """
    for view in process_views(system):
        if (view.instance_id, view.channel_id, view.cue_gen_id, view.operation_gen_id) == (
                instance_id, channel_id, cue_gen_id, operation_gen_id):
            return view.is_bifurcation
    return False
