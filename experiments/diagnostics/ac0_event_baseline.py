"""AC0 debug scaffold: opaque two-channel operations and independent outcomes.

Controllers are fixed/random/oracle fixtures. LearningSystem only OBSERVES
completed transitions; no learned operation choice or AC0 pass is claimed.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import random
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from core.learning import LearningSystem
from drivers.text_driver import TextDriver

UNKNOWN = {'interrupted', 'unavailable', 'cancelled'}


@dataclass(frozen=True)
class TransitionEvent:
    run_id: str
    instance_id: str
    channel_id: str
    driver_version: str
    base_revision: str
    seq: int
    event_id: str
    causal_parents: tuple[str, ...]
    observation_id: str
    observation_source: str
    available_operations: tuple[str, ...]
    chosen_operation: str
    operation_cost: int
    expected_observation: str
    actual_observation: str | None
    completion: str
    prediction_support: str
    prediction_source: str = 'fixture_task_target_not_a_learned_Gen'


class TwoChannelWorld:
    """Sandbox driver/evaluator. Hidden answers are never in controller views."""

    def __init__(self, seed: int, run_id: str = 'ac0-debug'):
        self.run_id = run_id
        rng = random.Random(seed)
        opaque = lambda: f'{rng.getrandbits(64):016x}'
        self.channels = tuple(opaque() for _ in range(2))
        self.operations = tuple(opaque() for _ in range(2))
        self._cues = {c: (opaque(), opaque()) for c in self.channels}
        self._targets = {c: opaque() for c in self.channels}
        self._divergences = {c: opaque() for c in self.channels}
        self._answers = {(c, phase): rng.choice(self.operations)
                         for c in self.channels for phase in (0, 1)}
        self._phase = dict.fromkeys(self.channels, 0)
        self._last: dict[str, str] = {}
        self._events: list[TransitionEvent] = []

    def view(self, channel: str) -> dict:
        return {'channel_id': channel,
                'observation_id': self._cues[channel][self._phase[channel]],
                'available_operations': self.operations}

    def oracle_operation(self, channel: str) -> str:
        """Evaluator-only upper bound, explicitly privileged."""
        return self._answers[channel, self._phase[channel]]

    def act(self, channel: str, operation: str, *, forced_status: str | None = None) -> TransitionEvent:
        view = self.view(channel)
        if operation not in self.operations:
            raise ValueError('operation is not available')
        if forced_status is not None and forced_status not in UNKNOWN:
            raise ValueError('only unknown outcomes can be injected')
        actual = None
        completion = forced_status
        if completion is None:
            success = operation == self._answers[channel, self._phase[channel]]
            actual = self._targets[channel] if success else self._divergences[channel]
            completion = 'success' if success else 'observed_divergence'
            if success:
                self._phase[channel] = 1 - self._phase[channel]
        support = ('unknown' if completion in UNKNOWN else
                   'positive' if actual == self._targets[channel] else 'negative')
        seq = len(self._events) + 1
        event = TransitionEvent(
            run_id=self.run_id, instance_id='observer-0', channel_id=channel,
            driver_version='opaque-two-channel/0.1', base_revision='unpublished-debug',
            seq=seq, event_id=f'e{seq:04d}',
            causal_parents=(self._last[channel],) if channel in self._last else (),
            observation_id=view['observation_id'], observation_source='sandbox-driver',
            available_operations=self.operations, chosen_operation=operation,
            operation_cost=1, expected_observation=self._targets[channel],
            actual_observation=actual, completion=completion, prediction_support=support)
        self._events.append(event)
        self._last[channel] = event.event_id
        return event


class CoreObserver:
    """Existing text driver + LearningSystem; the kernel does not pick actions.

    Unknown outcomes are NOT converted into core REFUTED tokens. This tests
    the adapter boundary only, not kernel-level interruption/resume semantics.
    """

    def __init__(self):
        self.system = LearningSystem(feature_tolerance=.15)
        self.drivers: dict[str, TextDriver] = {}
        self.seen: set[tuple[str, str]] = set()

    def observe(self, event: TransitionEvent) -> dict:
        key = (event.run_id, event.event_id)
        if key in self.seen:
            raise ValueError('duplicate event delivery')
        self.seen.add(key)
        outcomes, references = [], []
        before = self.system.engine.step_count
        if event.completion not in UNKNOWN:
            driver = self.drivers.setdefault(event.channel_id, TextDriver(event.channel_id))
            driver.set_text(' '.join([event.observation_id, event.chosen_operation,
                                      event.actual_observation]))
            for token in driver.produce():
                result = self.system.process_token(token)
                outcomes.append(result.outcome.name)
                references.extend([g for g in [result.new_gen_id, *result.completed_gen_ids] if g])
        return {'kernel_role': 'observer_only', 'core_step_outcomes': outcomes,
                'referenced_gen_ids': references, 'gen_support_evaluated': False,
                'processed_tokens': self.system.engine.step_count - before,
                'node_count': self.system.base.size()}


def validate_trace(events: list[dict]) -> None:
    """Reject dangling/cross-channel causal parents and coerced unknowns."""
    seen = {}
    last = {}
    for index, e in enumerate(events, 1):
        if e['seq'] != index or e['event_id'] in seen:
            raise ValueError('non-monotonic or duplicate event')
        expected_parent = [last[e['channel_id']]] if e['channel_id'] in last else []
        if list(e['causal_parents']) != expected_parent:
            raise ValueError('broken channel causal chain')
        if e['chosen_operation'] not in e['available_operations'] or e['operation_cost'] != 1:
            raise ValueError('invalid operation or cost')
        if e['completion'] in UNKNOWN:
            if e['actual_observation'] is not None or e['prediction_support'] != 'unknown':
                raise ValueError('unknown must not become negative evidence')
        elif e['completion'] in {'success', 'observed_divergence'}:
            if e['actual_observation'] is None:
                raise ValueError('completed operation needs an observed outcome')
            support = 'positive' if e['actual_observation'] == e['expected_observation'] else 'negative'
            if e['prediction_support'] != support:
                raise ValueError('support disagrees with external observation')
            if (e['completion'] == 'success') != (support == 'positive'):
                raise ValueError('task verdict disagrees with external observation')
        else:
            raise ValueError('unknown completion status')
        seen[e['event_id']] = e
        last[e['channel_id']] = e['event_id']


def run_debug(seed: int, controller: str, attempts: int = 48) -> dict:
    if controller not in {'fixed', 'random', 'oracle'} or attempts < 1:
        raise ValueError('invalid controller or attempt budget')
    world, observer = TwoChannelWorld(seed, f'ac0-debug-{seed}-{controller}'), CoreObserver()
    rng = random.Random(seed + 1000)
    events, updates = [], []
    for step in range(attempts):
        channel = world.channels[step % 2]  # declared fixed scheduler, not learned
        view = world.view(channel)
        operation = (world.oracle_operation(channel) if controller == 'oracle' else
                     rng.choice(view['available_operations']) if controller == 'random' else
                     view['available_operations'][0])
        injected = {3: 'interrupted', 5: 'unavailable', 7: 'cancelled'}.get(step % 12)
        event = world.act(channel, operation, forced_status=injected)
        events.append(asdict(event))
        updates.append({'event_id': event.event_id, **observer.observe(event)})
    validate_trace(events)
    observed = [e for e in events if e['completion'] not in UNKNOWN]
    return {'schema': 'firstagi.ac0-debug/v0.1', 'status': 'debug_scaffold_not_gate',
            'seed': seed, 'controller': controller, 'scheduler': 'fixed_alternating',
            'attempt_budget': attempts, 'operation_cost': sum(e['operation_cost'] for e in events),
            'observed_outcomes': len(observed), 'unknown_outcomes': attempts - len(observed),
            'task_successes': sum(e['completion'] == 'success' for e in observed),
            'events': events, 'core_updates': updates, 'gate_passed': False,
            'limitations': ['no learned action/channel selection', 'no Gen-specific support updates',
                            'no held-out competence or preregistered thresholds',
                            'no full runtime persistence or inheritance',
                            'no local-frontier work counters; kernel may scan globally']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--seed', type=int, default=41)
    parser.add_argument('--attempts', type=int, default=48)
    args = parser.parse_args()
    if args.out.exists():
        parser.error('output directory already exists; use a fresh path')
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    dirty = bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True).strip())
    args.out.mkdir(parents=True)
    hashes, summaries = {}, []
    for controller in ('fixed', 'random', 'oracle'):
        result = run_debug(args.seed, controller, args.attempts)
        result['source_commit'], result['source_dirty'] = commit, dirty
        filename = f'{controller}.json'
        raw = (json.dumps(result, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
        (args.out / filename).write_bytes(raw)
        hashes[filename] = hashlib.sha256(raw).hexdigest()
        summaries.append({k: result[k] for k in ['controller','attempt_budget','operation_cost',
                          'observed_outcomes','unknown_outcomes','task_successes','gate_passed']})
    (args.out / 'SHA256SUMS.json').write_text(json.dumps(hashes, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(summaries, indent=2))


if __name__ == '__main__':
    main()
