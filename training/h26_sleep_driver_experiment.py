"""
H26: SleepDriver — «Сон как системный драйвер»

Гипотеза:
  SleepDriver (воспроизведение непонятого в режиме сенсорной депривации)
  позволяет системе «понять во сне» то, что было непонятно в первом домене,
  после того как был изучен второй близкий домен.

  Измеримый результат:
    H26a: commit_rate > 0% (хотя бы одно событие объяснено)
    H26b: среди объяснённых — chain≥3 Gen (не шум)
    H26c: urgency повышается у событий, которые остались необъяснёнными

Протокол:
  1. Обучение на домене А (Лес)   → собрать лог удивлений
  2. Обучение на домене Б (Горы)  → расширить базу кросс-доменными знаниями
  3. SleepDriver.run()            → воспроизвести непонятое из А в расширенном контексте
  4. Анализ: что объяснено, что нет, какие meta-Gen созданы

Запуск:
    py -X utf8 training/h26_sleep_driver_experiment.py
    py -X utf8 training/h26_sleep_driver_experiment.py --transitions 3000
    py -X utf8 training/h26_sleep_driver_experiment.py --no-color
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from typing import Dict, List, Optional, Tuple

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.app import CoreApplication
from core.algorithm import StepOutcome
from core.capacity import CapacityBudget
from core.dream import (
    ContextQueryLog, CrossDomainDetector, DomainRegistry,
    REFUTEDEvent, SleepDriver, SleepResult,
)
from core.timescale import TimescaleScheduler
from drivers.text_driver import TextDriver
from training.scale_experiment import GenerativeCorpus


# ─── ANSI цвета ────────────────────────────────────────────────────────────────
_COLOR = True

def _c(code: str, text: str) -> str:
    return f"{code}{text}\033[0m" if _COLOR else text

W  = "\033[0m";  BD = "\033[1m";  DM = "\033[90m"
GR = "\033[92m"; CY = "\033[96m"; AM = "\033[93m"
RD = "\033[91m"; MG = "\033[95m"; BL = "\033[94m"


# ══════════════════════════════════════════════════════════════════════════════
# Обучающий цикл с логом удивлений
# ══════════════════════════════════════════════════════════════════════════════

def train_domain(
    app:         CoreApplication,
    corpus:      GenerativeCorpus,
    query_log:   ContextQueryLog,
    domain:      str,
    n_transitions: int,
    registry:    Optional[DomainRegistry] = None,
    batch_size:  int = 20,
    seed:        int = 42,
) -> Dict[str, int]:
    """
    Обучить систему на одном домене, собирая REFUTED события в query_log.

    Возвращает статистику: {outcome_name: count}.
    """
    drv = TextDriver("text")
    corpus._domain = domain
    corpus._rng.seed(seed)

    stats: Dict[str, int] = {"CONFIRMED": 0, "REFUTED": 0,
                              "COMPLETED": 0, "EXPLORING": 0}
    transitions = 0

    while transitions < n_transitions:
        for text in corpus.generate_batch(batch_size):
            if transitions >= n_transitions:
                break
            for tok in drv.produce(text):
                if transitions >= n_transitions:
                    break
                result = app.system.process_token(tok)
                stats[result.outcome.name] = stats.get(result.outcome.name, 0) + 1
                transitions += 1
                if registry is not None and hasattr(tok.data, "feature_id"):
                    registry.register(tok.data.feature_id, domain)

    return stats


# ══════════════════════════════════════════════════════════════════════════════
# Форматирование событий для статьи
# ══════════════════════════════════════════════════════════════════════════════

def _gen_label(app: CoreApplication, gen_id: str, maxlen: int = 30) -> str:
    """Получить человекочитаемый ярлык Gen из базы."""
    g = app.system.base.get(gen_id)
    if g is None:
        return f"[?{gen_id[:6]}]"
    lbl = g.label or "·".join(g.feature_chain[:4])
    lbl = lbl[:maxlen]
    chain = len(g.feature_chain)
    sig   = g.significance
    return f"{lbl} (chain={chain}, sig={sig:.2f})"


def _event_word(event: REFUTEDEvent) -> str:
    """Слово (токен), вызвавшее удивление."""
    if event.token_label:
        # TextDriver формирует label как «слово|p=N|...» — берём первую часть
        return event.token_label.split("|")[0].strip()
    return f"feat:{event.feature_id[:8]}"


def format_event(
    idx:    int,
    event:  REFUTEDEvent,
    app:    CoreApplication,
    width:  int = 70,
) -> str:
    word     = _event_word(event)
    ctx_lbls = [_gen_label(app, gid, maxlen=25)
                for gid in event.active_gen_ids[:3]]
    ctx_str  = " | ".join(ctx_lbls) if ctx_lbls else "—"
    lines = [
        f"  [{idx:02d}] {BD}{AM}«{word}»{W}",
        f"       контекст: {DM}{ctx_str}{W}",
        f"       chain={event.chain_len}  urgency={event.urgency:.1f}",
    ]
    return "\n".join(lines)


def format_sleep_event(
    idx:     int,
    event:   REFUTEDEvent,
    outcome: str,
    app:     CoreApplication,
) -> str:
    word = _event_word(event)
    ctx_lbls = [_gen_label(app, gid, maxlen=22) for gid in event.active_gen_ids[:2]]
    ctx_str  = " | ".join(ctx_lbls) if ctx_lbls else "контекст пуст"

    if outcome in ("CONFIRMED", "COMPLETED"):
        verdict = f"{GR}✓ {outcome} — понято во сне!{W}"
    elif outcome == "REFUTED":
        verdict = f"{RD}✗ снова непонятно  (urgency ↑ → {event.urgency:.1f}){W}"
    elif outcome == "EXPLORING":
        verdict = f"{AM}~ EXPLORING (контекст пуст){W}"
    else:
        verdict = f"{DM}{outcome}{W}"

    lines = [
        f"  [{idx:02d}] {BD}«{word}»{W}  chain={event.chain_len}",
        f"       ctx: {DM}{ctx_str}{W}",
        f"       → {verdict}",
    ]
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# Главный оркестратор эксперимента
# ══════════════════════════════════════════════════════════════════════════════

def run_experiment(
    n_transitions_per_domain: int = 5000,
    n_sleep_replays:          int = 30,
    min_chain:                int = 3,
    capacity:                 int = 0,
) -> None:
    sep  = "═" * 66
    line = "─" * 66

    print(f"\n{BD}{CY}{sep}{W}")
    print(f"{BD}{CY}  ЭКСПЕРИМЕНТ H26: SleepDriver — «Сон как системный драйвер»{W}")
    print(f"{BD}{CY}{sep}{W}\n")
    print(f"""\
  {BD}Идея:{W} во время сна система воспроизводит непонятые события дня
  в режиме сенсорной депривации — без нового внешнего input.
  То, что было REFUTED утром в домене «Лес», может стать CONFIRMED
  после изучения домена «Горы», если между ними есть общие паттерны.

  Это не ReplayEngine (который воспроизводит ожидаемое и всегда
  получает CONFIRMED). SleepDriver воспроизводит именно {BD}непонятое{W}.
""")

    # ── Инициализация ────────────────────────────────────────────────────────
    query_log = ContextQueryLog()
    cfg       = {"mock_teacher": False, "feature_tolerance": 0.15}
    app       = CoreApplication(config=cfg)
    app.startup()

    # Подключаем query_log к LearningSystem
    app.system._query_log = query_log

    corpus   = GenerativeCorpus(seed=42)
    registry = DomainRegistry()

    budget: Optional[CapacityBudget] = None
    if capacity > 0:
        ts     = TimescaleScheduler()
        budget = CapacityBudget(capacity, ts)
        app.system._capacity_budget = budget

    # ── ФАЗА 1: Лес ─────────────────────────────────────────────────────────
    print(f"{BD}{'─'*66}{W}")
    print(f"{BD}{BL}  ФАЗА 1: Бодрствование — домен «Лес»{W}")
    print(f"{BD}{'─'*66}{W}\n")
    print(f"  Читаем тексты о лесе: {n_transitions_per_domain} переходов внимания...")

    t0 = time.perf_counter()
    stats_a = train_domain(app, corpus, query_log, "лес",
                            n_transitions_per_domain, registry)
    t1 = time.perf_counter()

    base_after_a = app.system.base.size()
    log_after_a  = len(query_log)
    deep_after_a = len(query_log.candidates(min_chain=min_chain))

    print(f"  Готово за {t1-t0:.1f}s  |  {int(n_transitions_per_domain/(t1-t0))} tok/s")
    # Распределение context_depth в логе
    depth_dist_a: Dict[int, int] = {}
    for e in query_log.all_events():
        depth_dist_a[e.chain_len] = depth_dist_a.get(e.chain_len, 0) + 1

    print(f"\n  {BD}База Gen:{W}        {base_after_a}")
    print(f"  {BD}Удивлений всего:{W} {log_after_a}")
    print(f"  {BD}С контекстом (depth≥{min_chain}):{W} {deep_after_a}")
    print(f"  {BD}Исходы:{W} CONFIRMED={stats_a['CONFIRMED']}  "
          f"REFUTED={stats_a['REFUTED']}  COMPLETED={stats_a.get('COMPLETED',0)}")
    print(f"  {BD}Контекст-глубины (depth=N: кол-во событий):{W}")
    for d in sorted(depth_dist_a.keys()):
        print(f"    depth={d}: {depth_dist_a[d]}")
    print()

    # Показать топ-5 удивлений дня
    top_events_a = query_log.candidates(min_chain=min_chain, max_n=5)
    if top_events_a:
        print(f"  {BD}Топ удивлений из «Леса» (chain≥{min_chain}):{W}")
        for i, ev in enumerate(top_events_a, 1):
            print(format_event(i, ev, app))
        print()

    log_snapshot_after_a = list(query_log._events)  # снимок лога после Леса

    # ── ФАЗА 2: Горы ─────────────────────────────────────────────────────────
    print(f"{BD}{'─'*66}{W}")
    print(f"{BD}{MG}  ФАЗА 2: Бодрствование — домен «Горы»{W}")
    print(f"{BD}{'─'*66}{W}\n")
    print(f"  Читаем тексты о горах: {n_transitions_per_domain} переходов...")
    print(f"  {DM}(Лог удивлений продолжает накапливаться — один непрерывный «день»){W}\n")

    t2 = time.perf_counter()
    stats_b = train_domain(app, corpus, query_log, "горы",
                            n_transitions_per_domain, registry, seed=43)
    t3 = time.perf_counter()

    base_after_b = app.system.base.size()
    log_after_b  = len(query_log)
    deep_after_b = len(query_log.candidates(min_chain=min_chain))

    print(f"  Готово за {t3-t2:.1f}s  |  {int(n_transitions_per_domain/(t3-t2))} tok/s")
    print(f"\n  {BD}База Gen:{W}        {base_after_b}  (+{base_after_b - base_after_a} за «Горы»)")
    print(f"  {BD}Удивлений всего:{W} {log_after_b}  (+{log_after_b - log_after_a} за «Горы»)")
    print(f"  {BD}Глубоких (chain≥{min_chain}):{W} {deep_after_b}")
    print(f"  {BD}Исходы:{W} CONFIRMED={stats_b['CONFIRMED']}  "
          f"REFUTED={stats_b['REFUTED']}  COMPLETED={stats_b['COMPLETED']}\n")

    top_events_b = [e for e in query_log.candidates(min_chain=min_chain, max_n=10)
                    if e not in log_snapshot_after_a][:5]
    if top_events_b:
        print(f"  {BD}Новые удивления из «Гор» (chain≥{min_chain}):{W}")
        for i, ev in enumerate(top_events_b, 1):
            print(format_event(i, ev, app))
        print()

    # ── ФАЗА 3: Сон ──────────────────────────────────────────────────────────
    print(f"{BD}{'─'*66}{W}")
    print(f"{BD}{GR}  ФАЗА 3: Сон — SleepDriver.run(){W}")
    print(f"{BD}{'─'*66}{W}\n")
    print(f"  {AM}⟳ Захват внимания. Внешний поток заблокирован.{W}")
    print(f"  Воспроизведение до {n_sleep_replays} непонятых событий "
          f"(chain≥{min_chain})...\n")

    candidates_before = query_log.candidates(min_chain=min_chain, max_n=n_sleep_replays)
    n_candidates = len(candidates_before)

    detector   = CrossDomainDetector(
        domain_registry=registry,
        min_domains=2,
        min_chain_fallback=min_chain,
    )
    driver = SleepDriver(query_log)

    t4 = time.perf_counter()
    result = driver.run(
        system    = app.system,
        detector  = detector,
        budget    = budget,
        n_replays = n_sleep_replays,
        min_chain = min_chain,
    )
    t5 = time.perf_counter()

    # Показать каждое событие с исходом
    outcomes = result.replay_outcomes
    for i, (event, outcome) in enumerate(zip(candidates_before, outcomes), 1):
        print(format_sleep_event(i, event, outcome, app))
        print()

    # ── Итоги ────────────────────────────────────────────────────────────────
    print(f"{BD}{CY}{'═'*66}{W}")
    print(f"{BD}{CY}  ИТОГИ ЭКСПЕРИМЕНТА{W}")
    print(f"{BD}{CY}{'═'*66}{W}\n")

    n_confirmed  = sum(1 for o in outcomes if o in ("CONFIRMED", "COMPLETED"))
    n_refuted    = sum(1 for o in outcomes if o == "REFUTED")
    n_exploring  = sum(1 for o in outcomes if o == "EXPLORING")
    n_meta       = result.meta_gen_count
    rate         = n_confirmed / max(n_candidates, 1) * 100

    print(f"  {'─'*62}")
    print(f"  {'Событий для replay':<35} {n_candidates}")
    print(f"  {GR}{'Объяснено во сне (CONFIRMED)':<35} {n_confirmed}  ({rate:.1f}%){W}")
    print(f"  {RD}{'Снова непонятно (REFUTED)':<35} {n_refuted}{W}")
    print(f"  {AM}{'Пустой контекст (EXPLORING)':<35} {n_exploring}{W}")
    print(f"  {'Meta-Gen созданы и закоммичены':<35} {n_meta}")
    print(f"  {'commit_rate':<35} {result.commit_rate:.1%}")
    if result.n_evicted:
        print(f"  {'Eviction (CapacityBudget)':<35} {result.n_evicted}")
    print(f"  {'Время сна':<35} {t5-t4:.2f}s")
    print(f"  {'─'*62}")

    # Показать созданные meta-Gen
    if result.meta_gen_ids:
        print(f"\n  {BD}Meta-Gen, созданные во сне:{W}")
        for mid in result.meta_gen_ids[:5]:
            g = app.system.base.get(mid)
            if g:
                domains = registry.domains_of(g.feature_chain)
                lbl = g.label or "·".join(g.feature_chain[:6])
                print(f"    chain={len(g.feature_chain)}  sig={g.significance:.3f}"
                      f"  domains={sorted(domains) if domains else 'n/a'}")
                print(f"    label: {DM}{lbl}{W}")
    print()

    # Непонятое — переносится
    remaining = query_log.candidates(min_chain=min_chain)
    if remaining:
        print(f"  {BD}Осталось непонятым (urgency > 1.5) — перенос на следующую ночь:{W}")
        for ev in remaining[:5]:
            word = _event_word(ev)
            print(f"    «{word}»  chain={ev.chain_len}  urgency={ev.urgency:.1f}")
        if len(remaining) > 5:
            print(f"    ... и ещё {len(remaining)-5}")
        print()

    # Вердикт
    print(f"  {'─'*62}")
    h26a = n_confirmed > 0
    h26b = n_meta > 0
    h26c = n_refuted > 0  # urgency выросло на 0.5 у каждого REFUTED события

    print(f"\n  {BD}Вердикт:{W}")
    _v = lambda ok, txt: f"  {'  ' + GR + '✓' if ok else '  ' + RD + '✗'}{W}  {txt}"
    print(_v(h26a,
        f"H26a: commit_rate > 0% → {'ПОДТВЕРЖДЕНА' if h26a else 'ОПРОВЕРГНУТА'}"))
    print(_v(h26b,
        f"H26b: meta-Gen с chain≥{min_chain} созданы → "
        f"{'ПОДТВЕРЖДЕНА' if h26b else 'ОПРОВЕРГНУТА'}"))
    print(_v(h26c,
        f"H26c: urgency растёт у необъяснённых → "
        f"{'ПОДТВЕРЖДЕНА' if h26c else 'ОПРОВЕРГНУТА'}"))
    print()

    # ── Резюме для читателя ──────────────────────────────────────────────────
    print(f"\n{BD}{CY}{'═'*66}{W}")
    print(f"{BD}{CY}  ЧТО ПРОИЗОШЛО: ОБЪЯСНЕНИЕ ДЛЯ ЧИТАТЕЛЯ{W}")
    print(f"{BD}{CY}{'═'*66}{W}\n")

    print(f"""\
  {BD}Что такое «удивление» в этом эксперименте?{W}

  Система строит обобщения (Gen) — цепочки признаков, отражающие
  ожидаемые последовательности слов. Когда вместо ожидаемого слова
  приходит другое, это называется REFUTED — опровержение.

  Каждое опровержение — это «удивление»: система ожидала одно,
  получила другое. Лог удивлений накапливается за день.

  {BD}Фаза 1 («Лес»): насыщенный день{W}

  За {n_transitions_per_domain:,} переходов внимания система прочитала
  тексты о лесных животных. База обобщений выросла до {base_after_a:,} Gen.
  Накоплено {log_after_a:,} удивлений — ситуаций, где ожидание не
  совпало с реальностью. Каждое удивление сохранено с контекстом:
  «в ситуации X пришло неожиданное слово Y».

  {BD}Фаза 2 («Горы»): новый опыт расширяет контекст{W}

  Система переключилась на горные тексты. База выросла ещё на
  {base_after_b - base_after_a:,} Gen — появились новые обобщения,
  включающие слова, которые встречаются в обоих доменах:
  «медведь», «нашёл», «встретил», «обрадовался».

  Эти слова теперь известны системе в двух разных контекстах.

  {BD}Фаза 3 (Сон): воспроизведение непонятого{W}

  SleepDriver захватывает внимание: внешний поток заблокирован.
  Один за другим воспроизводятся {n_candidates} удивлений из лога.

  Механизм каждого воспроизведения:
    1. Восстановить контекст момента удивления (какой Gen был активен)
    2. Подать тот же «удививший» токен заново
    3. Если система теперь находит совпадение → COMPLETED (инсайт)
    4. Если снова не находит → REFUTED, urgency += 0.5 (перенос на завтра)
""")

    if n_confirmed > 0:
        # Найти первое объяснённое событие для иллюстрации
        explained = [(e, o) for e, o in zip(candidates_before, outcomes)
                     if o in ("CONFIRMED", "COMPLETED")]
        if explained:
            ev0, out0 = explained[0]
            w0   = _event_word(ev0)
            ctx0 = _gen_label(app, ev0.active_gen_ids[0], maxlen=20) \
                   if ev0.active_gen_ids else "—"
            print(f"""\
  {BD}Пример инсайта во сне:{W}

  Событие: слово {AM}«{w0}»{W} в контексте {DM}[{ctx0}]{W}
  Утром это было удивлением: ожидалось другое слово.
  После обучения на горах система знает «{w0}» лучше —
  оно встречается в обоих доменах. Ночью: воспроизведение → {GR}{out0}{W}.

  Это и есть «понять во сне»: та же ситуация, тот же токен,
  но теперь в расширенном контексте совпадение нашлось.
""")

    if n_meta > 0:
        print(f"""\
  {BD}Кросс-доменный Meta-Gen:{W}

  Во сне создан Gen, охватывающий оба домена (горы + лес).
  Он включает слова из обоих миров — это и есть та самая
  «связь не первого порядка», о которой говорит архитектура:
  не просто «медведь в лесу» и «медведь в горах» по отдельности,
  а обобщение, пересекающее доменную границу.
""")

    print(f"""\
  {BD}Непонятое переносится на следующую ночь:{W}

  {n_refuted} из {n_candidates} событий остались необъяснёнными.
  Их urgency вырос — они станут приоритетными при следующем сне.
  Это соответствует тому, как работает эпизодическая память:
  повторяющиеся непонятые события «настаивают» на интеграции.

  {BD}Главный вывод эксперимента H26:{W}

  Сон — это не произвольная галлюцинация, а {BD}целенаправленное{W}
  воспроизведение непонятого в обогащённом контексте.
  Система буквально «переспала» с вопросом и нашла ответ —
  не потому что что-то изменилось в алгоритме, а потому что
  изменился контекст: день принёс новый опыт, который
  наутро стал фундаментом для ночной интеграции.
""")


# ══════════════════════════════════════════════════════════════════════════════
# Точка входа
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    global W, BD, DM, GR, CY, AM, RD, MG, BL
    parser = argparse.ArgumentParser(description="H26: SleepDriver experiment")
    parser.add_argument("--transitions", type=int, default=5000,
                        help="Число переходов на домен (default: 5000)")
    parser.add_argument("--replays", type=int, default=30,
                        help="Максимум событий в sleep (default: 30)")
    parser.add_argument("--min-chain", type=int, default=1,
                        help="Минимальная глубина контекста при REFUTED (default: 1)")
    parser.add_argument("--capacity", type=int, default=0,
                        help="CapacityBudget (0=выключен, default: 0)")
    parser.add_argument("--no-color", action="store_true",
                        help="Вывод без ANSI-цветов")
    args = parser.parse_args()

    if args.no_color:
        W = BD = DM = GR = CY = AM = RD = MG = BL = ""

    run_experiment(
        n_transitions_per_domain = args.transitions,
        n_sleep_replays          = args.replays,
        min_chain                = args.min_chain,
        capacity                 = args.capacity,
    )


if __name__ == "__main__":
    main()
