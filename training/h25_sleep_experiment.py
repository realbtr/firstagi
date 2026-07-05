"""
h25_sleep_experiment.py — Целевой тест гипотезы H25.

H25: sleep_cycle() после плато →
  • chain≥3 count растёт ≥ 20%
  • появляются новые кросс-доменные Gen (DomainRegistry span ≥ 2)
  • без sleep: chain≥3 не растёт

Структура эксперимента:
  Фаза 1. Обучение на 4 доменах до плато (n_new ≈ 0).
          Каждому feature_id присваивается метка домена через DomainRegistry.
  Фаза 2. Измерение baseline: chain_dist, avg_sig, cross-domain-Gen.
  Фаза 3. N циклов sleep_cycle() с CrossDomainDetector.
          После каждого цикла: измерение chain_dist, meta_gen_count.
  Фаза 4. Контроль (без sleep): такое же дообучение — chain≥3 не должен расти.
  Фаза 5. Итоговый отчёт + проверка H25.

Запуск:
    py -X utf8 training/h25_sleep_experiment.py
    py -X utf8 training/h25_sleep_experiment.py --sleep-cycles 10
    py -X utf8 training/h25_sleep_experiment.py --train-transitions 50000
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.app import CoreApplication
from core.algorithm import StepOutcome
from core.capacity import CapacityBudget
from core.dream import (
    CrossDomainDetector, DomainRegistry, ReplayEngine,
    SleepScheduler, SleepResult, sleep_cycle,
)
from core.generalization import Generalization
from core.timescale import TimescaleScheduler
from drivers.text_driver import TextDriver
from training.scale_experiment import GenerativeCorpus, _DOMAIN_SPECS, _TEMPLATES
import random

# ─── ANSI ─────────────────────────────────────────────────────────────────────
W  = "\033[0m";  BD = "\033[1m";  DM = "\033[90m"
GR = "\033[92m"; CY = "\033[96m"; AM = "\033[93m"
RD = "\033[91m"; MG = "\033[95m"; BL = "\033[94m"


# ══════════════════════════════════════════════════════════════════════════════
# Утилиты
# ══════════════════════════════════════════════════════════════════════════════

def hdr(t: str) -> None:
    print(f"\n{BD}{CY}{'═'*68}{W}")
    print(f"{BD}{CY}  {t}{W}")
    print(f"{BD}{CY}{'═'*68}{W}\n")

def sub(t: str) -> None:
    print(f"  {BL}▶ {t}{W}")

def ok(t: str) -> None:
    print(f"  {GR}✓ {t}{W}")

def fail(t: str) -> None:
    print(f"  {RD}✗ {t}{W}")

def dim(k: str, v) -> None:
    print(f"  {DM}{k:<40}{W} {BD}{v}{W}")


@dataclass
class ChainProfile:
    """Снапшот распределения цепочек."""
    base_size:   int
    chain_dist:  Dict[int, int]
    avg_sig:     float
    cross_domain_ids: List[str] = field(default_factory=list)

    @property
    def chain3plus(self) -> int:
        return sum(v for k, v in self.chain_dist.items() if k >= 3)

    @property
    def chain3plus_frac(self) -> float:
        return self.chain3plus / max(self.base_size, 1)

    def report(self, label: str) -> None:
        c3 = self.chain3plus
        frac = self.chain3plus_frac
        c1 = self.chain_dist.get(1, 0)
        print(
            f"  {label:<20}  "
            f"base={self.base_size:>5,}  "
            f"chain3+={c3:>4,} ({frac:.1%})  "
            f"chain1={c1:>3,}  "
            f"avg_sig={self.avg_sig:.4f}  "
            f"cross_domain={len(self.cross_domain_ids)}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# Обучение с регистрацией доменов
# ══════════════════════════════════════════════════════════════════════════════

def train_with_domain_registry(
    app:       CoreApplication,
    corpus:    GenerativeCorpus,
    registry:  DomainRegistry,
    n_transitions: int,
    domain_switch_every: int = 15_000,
    batch_size: int = 50,
    seed: int = 42,
) -> Dict[str, int]:
    """
    Обучение text_system с параллельной регистрацией feature_id → домен.

    После каждого process_token() — регистрируем feature_id нового токена
    (взятый из token.data.feature_id) под текущим доменом.

    Возвращает: {домен → число переходов}.
    """
    drv = TextDriver("h25_td")
    rng = random.Random(seed)
    domain_counts: Dict[str, int] = {}
    transitions_done = 0
    next_domain_switch = domain_switch_every

    while transitions_done < n_transitions:
        texts = corpus.generate_batch(batch_size)
        for text in texts:
            if transitions_done >= n_transitions:
                break
            current_domain = corpus.domain
            domain_counts[current_domain] = domain_counts.get(current_domain, 0)

            for tok in drv.produce(text):
                r = app.system.process_token(tok)
                # Регистрируем feature_id токена под текущим доменом
                if hasattr(tok.data, "feature_id"):
                    registry.register(tok.data.feature_id, current_domain)
                transitions_done += 1
                domain_counts[current_domain] += 1
            app.system.reset_context()

            if transitions_done >= next_domain_switch:
                corpus.switch_domain()
                next_domain_switch += domain_switch_every

    return domain_counts


# ══════════════════════════════════════════════════════════════════════════════
# Снапшот базы
# ══════════════════════════════════════════════════════════════════════════════

def snapshot(app: CoreApplication, registry: DomainRegistry, detector: CrossDomainDetector) -> ChainProfile:
    all_gen = app.system.base.all()
    n = len(all_gen)
    chain_dist: Dict[int, int] = {}
    sig_sum = 0.0
    cross_ids: List[str] = []

    for g in all_gen:
        c = len(g.feature_chain)
        chain_dist[c] = chain_dist.get(c, 0) + 1
        sig_sum += g.significance
        if detector.is_meta_candidate(g):
            cross_ids.append(g.gen_id)

    return ChainProfile(
        base_size=n,
        chain_dist=chain_dist,
        avg_sig=sig_sum / max(n, 1),
        cross_domain_ids=cross_ids,
    )


# ══════════════════════════════════════════════════════════════════════════════
# Один sleep-цикл с замером
# ══════════════════════════════════════════════════════════════════════════════

def run_sleep_cycle(
    app:       CoreApplication,
    registry:  DomainRegistry,
    detector:  CrossDomainDetector,
    budget:    Optional[CapacityBudget],
    n_replays: int,
    replay_steps: int,
    cycle_num: int,
) -> Tuple[SleepResult, ChainProfile]:
    """Запустить один цикл сна, вернуть результат + новый профиль."""
    replay_engine = ReplayEngine(app.system.engine._features)
    result = sleep_cycle(
        system        = app.system,
        replay_engine = replay_engine,
        detector      = detector,
        budget        = budget,
        n_replays     = n_replays,
        replay_steps  = replay_steps,
    )
    profile = snapshot(app, registry, detector)
    return result, profile


# ══════════════════════════════════════════════════════════════════════════════
# Главная функция
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(description="H25: Sleep → chain≥3 рост")
    parser.add_argument("--train-transitions", type=int, default=80_000,
                        help="Число переходов обучения до сна")
    parser.add_argument("--domain-switch",     type=int, default=20_000,
                        help="Переходов до смены домена")
    parser.add_argument("--sleep-cycles",      type=int, default=5,
                        help="Число циклов sleep_cycle()")
    parser.add_argument("--n-replays",         type=int, default=20,
                        help="Replays в каждом sleep_cycle()")
    parser.add_argument("--replay-steps",      type=int, default=30,
                        help="Шагов replay в каждом replay")
    parser.add_argument("--capacity",          type=int, default=8_000,
                        help="CapacityBudget (0=без лимита). > 6000 чтобы meta-Gen выжили")
    parser.add_argument("--min-chain-fallback",type=int, default=3,
                        help="Fallback порог для CrossDomainDetector")
    parser.add_argument("--min-domains",       type=int, default=2,
                        help="Мин число доменов для кросс-доменного Gen")
    parser.add_argument("--seed",              type=int, default=42)
    parser.add_argument("--tol",               type=float, default=0.15)
    args = parser.parse_args()

    hdr("H25: Sleep/Dream → рост chain≥3 и кросс-доменных Gen")

    # ── Инициализация ───────────────────────────────────────────────────────
    corpus   = GenerativeCorpus(seed=args.seed)
    registry = DomainRegistry()

    cfg = {"mock_teacher": False, "feature_tolerance": args.tol}
    app = CoreApplication(config=cfg)
    app.startup()

    # CrossDomainDetector: с реестром (если домены заполнены) + fallback
    detector = CrossDomainDetector(
        domain_registry    = registry,
        min_domains        = args.min_domains,
        min_chain_fallback = args.min_chain_fallback,
    )

    # CapacityBudget (мягкий — больше 6K чтобы meta-Gen выжили)
    budget: Optional[CapacityBudget] = None
    if args.capacity > 0:
        sched  = TimescaleScheduler()
        budget = CapacityBudget(max_gens=args.capacity, scheduler=sched)
        budget.attach_vitality(app.system.vitality)

    # ── Фаза 1: Обучение до плато ────────────────────────────────────────────
    hdr(f"Фаза 1: Обучение ({args.train_transitions:,} переходов, 4 домена)")
    t0 = time.perf_counter()

    domain_counts = train_with_domain_registry(
        app, corpus, registry,
        n_transitions       = args.train_transitions,
        domain_switch_every = args.domain_switch,
        seed                = args.seed,
    )

    elapsed = time.perf_counter() - t0
    tok_s   = args.train_transitions / max(elapsed, 1e-9)
    print(f"  Время: {elapsed:.1f}s  ({tok_s:.0f} tok/s)")
    print(f"  Домены: { {k: f'{v:,}' for k, v in domain_counts.items()} }")
    dim("DomainRegistry size:", f"{registry.size():,} features")
    dim("Известных доменов:",   registry.known_domains())

    # ── Фаза 2: Baseline ─────────────────────────────────────────────────────
    hdr("Фаза 2: Baseline до сна")

    baseline = snapshot(app, registry, detector)
    baseline.report("BASELINE")

    print()
    sub("Chain distribution baseline:")
    total = sum(baseline.chain_dist.values())
    for c in sorted(baseline.chain_dist.keys()):
        n   = baseline.chain_dist[c]
        pct = n / max(total, 1)
        bar = "█" * int(pct * 35)
        col = GR if c >= 3 else AM if c == 2 else DM
        print(f"  chain={c:>2}: {col}{n:>5,} ({pct:5.1%}){W}  {bar}")

    # Проверяем SleepScheduler
    sched = SleepScheduler(plateau_threshold=5, plateaus_required=1,
                           urgency_threshold=0.5, min_knock_fraction=0.0)
    decision = sched.tick(app.system.base, app.system.vitality, current_step=args.train_transitions)
    dim("SleepScheduler decision:", decision)

    # ── Фаза 3: sleep_cycle() × N ───────────────────────────────────────────
    hdr(f"Фаза 3: {args.sleep_cycles} цикла(ов) sleep_cycle()")
    print(f"  n_replays={args.n_replays}  replay_steps={args.replay_steps}\n")

    profiles: List[Tuple[SleepResult, ChainProfile]] = []
    prev_c3 = baseline.chain3plus

    print(f"  {'Цикл':>5}  {'meta_gen':>8}  {'committed':>9}  {'rollback':>8}  "
          f"{'commit%':>7}  {'chain3+':>7}  {'delta_c3':>8}  {'cross_dom':>9}")
    print("  " + "─" * 70)

    for i in range(args.sleep_cycles):
        result, profile = run_sleep_cycle(
            app, registry, detector, budget,
            n_replays    = args.n_replays,
            replay_steps = args.replay_steps,
            cycle_num    = i + 1,
        )
        profiles.append((result, profile))

        delta_c3 = profile.chain3plus - prev_c3
        prev_c3  = profile.chain3plus
        delta_col = GR if delta_c3 > 0 else DM if delta_c3 == 0 else RD

        print(
            f"  {i+1:>5d}  {result.meta_gen_count:>8d}  "
            f"{result.total_committed:>9d}  {result.total_rolled_back:>8d}  "
            f"{result.commit_rate:>7.1%}  {profile.chain3plus:>7,}  "
            f"{delta_col}{delta_c3:>+8,}{W}  "
            f"{len(profile.cross_domain_ids):>9,}"
        )

    # ── Фаза 4: Контроль (дообучение без сна) ───────────────────────────────
    hdr("Фаза 4: Контроль — дообучение без сна")
    print("  Ожидаем: chain≥3 НЕ растёт (плато уже достигнуто)\n")

    control_app = CoreApplication(config=cfg)
    control_app.startup()
    control_corpus = GenerativeCorpus(seed=args.seed)
    control_registry = DomainRegistry()

    # Обучаем контрольную систему теми же данными
    train_with_domain_registry(
        control_app, control_corpus, control_registry,
        n_transitions       = args.train_transitions,
        domain_switch_every = args.domain_switch,
        seed                = args.seed,
    )
    ctrl_before = snapshot(control_app, control_registry, detector)

    # Дообучаем ещё на 20% без сна (эквивалент времени sleep)
    extra_trans = args.train_transitions // 5
    train_with_domain_registry(
        control_app, control_corpus, control_registry,
        n_transitions       = extra_trans,
        domain_switch_every = args.domain_switch,
        seed                = args.seed + 1,
    )
    ctrl_after = snapshot(control_app, control_registry, detector)

    ctrl_before.report("CONTROL before")
    ctrl_after.report("CONTROL after")
    ctrl_delta = ctrl_after.chain3plus - ctrl_before.chain3plus
    col = GR if ctrl_delta > 0 else DM
    print(f"  Контроль chain3+ delta: {col}{ctrl_delta:+d}{W}  "
          f"(ожидается ≈ 0 или небольшой рост из-за дообучения)")

    # ── Фаза 5: Итог + H25 ──────────────────────────────────────────────────
    hdr("Итог: проверка H25")

    final_profile    = profiles[-1][1] if profiles else baseline
    total_meta_gen   = sum(r.meta_gen_count for r, _ in profiles)
    total_committed  = sum(r.total_committed for r, _ in profiles)
    total_rolled     = sum(r.total_rolled_back for r, _ in profiles)
    avg_commit_rate  = sum(r.commit_rate for r, _ in profiles) / max(len(profiles), 1)

    delta_c3_abs = final_profile.chain3plus - baseline.chain3plus
    delta_c3_pct = delta_c3_abs / max(baseline.chain3plus, 1) * 100

    delta_cross = len(final_profile.cross_domain_ids) - len(baseline.cross_domain_ids)
    delta_sig   = final_profile.avg_sig - baseline.avg_sig

    print()
    print(f"  {'Метрика':<35}  {'До сна':>10}  {'После сна':>10}  {'Δ':>10}")
    print("  " + "─" * 68)
    print(f"  {'base_size':<35}  {baseline.base_size:>10,}  "
          f"{final_profile.base_size:>10,}  "
          f"{final_profile.base_size - baseline.base_size:>+10,}")
    print(f"  {'chain≥3 count':<35}  {baseline.chain3plus:>10,}  "
          f"{final_profile.chain3plus:>10,}  "
          f"{delta_c3_abs:>+10,}")
    print(f"  {'chain≥3 fraction':<35}  {baseline.chain3plus_frac:>10.1%}  "
          f"{final_profile.chain3plus_frac:>10.1%}  "
          f"{final_profile.chain3plus_frac - baseline.chain3plus_frac:>+10.1%}")
    print(f"  {'cross-domain Gen count':<35}  {len(baseline.cross_domain_ids):>10,}  "
          f"{len(final_profile.cross_domain_ids):>10,}  "
          f"{delta_cross:>+10,}")
    print(f"  {'avg_sig':<35}  {baseline.avg_sig:>10.4f}  "
          f"{final_profile.avg_sig:>10.4f}  "
          f"{delta_sig:>+10.4f}")
    print()
    dim("Всего meta_gen_count (через все циклы):", total_meta_gen)
    dim("Всего committed:",                        total_committed)
    dim("Всего rolled_back:",                      total_rolled)
    dim("Avg commit_rate:",                        f"{avg_commit_rate:.1%}")
    dim("Контроль chain3+ delta:",                 f"{ctrl_delta:+d}")
    print()

    # Проверка H25
    h25_c3       = delta_c3_pct >= 20.0
    h25_cross    = delta_cross > 0
    h25_control  = ctrl_delta <= delta_c3_abs  # sleep > дообучение

    if h25_c3 and h25_control:
        ok(f"H25 ПОДТВЕРЖДЕНА: chain≥3 вырос на {delta_c3_pct:+.1f}% "
           f"(порог ≥20%), контроль Δ={ctrl_delta:+d}")
    elif h25_c3:
        ok(f"H25 ЧАСТИЧНО: chain≥3 вырос на {delta_c3_pct:+.1f}%, "
           f"но контроль Δ={ctrl_delta:+d} тоже вырос")
    elif delta_c3_abs > 0:
        fail(f"H25 СЛАБО: chain≥3 вырос на {delta_c3_pct:+.1f}% "
             f"(< 20% порога). meta_gen={total_meta_gen}")
    else:
        fail(f"H25 ОПРОВЕРГНУТА: chain≥3 не вырос (Δ={delta_c3_abs:+d}). "
             f"meta_gen={total_meta_gen}, commit_rate={avg_commit_rate:.1%}")

    if h25_cross:
        ok(f"Кросс-доменных Gen: +{delta_cross} (было {len(baseline.cross_domain_ids)})")
    else:
        print(f"  {DM}Кросс-доменных Gen: {delta_cross:+d}{W}")

    # Детальный профиль после сна
    print()
    sub("Chain distribution после сна:")
    total = sum(final_profile.chain_dist.values())
    for c in sorted(final_profile.chain_dist.keys()):
        n   = final_profile.chain_dist[c]
        pct = n / max(total, 1)
        bar = "█" * int(pct * 35)
        col = GR if c >= 3 else AM if c == 2 else DM

        b_n   = baseline.chain_dist.get(c, 0)
        delta = n - b_n
        dstr  = f"({delta:+d})" if delta != 0 else ""
        print(f"  chain={c:>2}: {col}{n:>5,} ({pct:5.1%}){W}  {bar}  {DM}{dstr}{W}")

    # Анализ кросс-доменных Gen (топ-5 по sig)
    if final_profile.cross_domain_ids and registry.size() > 0:
        print()
        sub(f"Топ кросс-доменных Gen (из {len(final_profile.cross_domain_ids)}):")
        gens_by_sig = sorted(
            (app.system.base.get(gid) for gid in final_profile.cross_domain_ids
             if app.system.base.get(gid) is not None),
            key=lambda g: g.significance,
            reverse=True,
        )
        for g in gens_by_sig[:8]:
            domains = registry.domains_of(g.feature_chain)
            print(
                f"  chain={len(g.feature_chain):>2}  "
                f"sig={g.significance:.3f}  "
                f"label={str(g.label or '')[:30]:<30}  "
                f"domains={sorted(domains)}"
            )

    print()


if __name__ == "__main__":
    main()
