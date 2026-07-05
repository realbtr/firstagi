"""
Эксперимент «Слепые зоны и учитель внимания».

Три фазы, отражающие воспитательную дугу:

  Фаза 1 «Формирование»:
    Обучить на Матрёшке + Ритме (без Нарратива и Развилок).
    Образуются трансцендентные Gen — «фундамент мировоззрения».
    Обнаруживаем их: chain_len ≤ 2, sig ≥ 0.8, children ≥ 5.

  Фаза 2 «Слепая зона»:
    Предъявляем Нарратив и Развилки. Модель их не знает.
    Фиксируем: urgency нарастает, match_rate низкий.
    Находим «слепые зоны»: тексты где urgency накапливается, но прогресса нет.
    Это паттерн «вижу лес — не замечаю деревьев»:
    трансцендентный Gen «что-то происходит» подтверждается, но детальные
    ветки нарратива вытеснены.

  Фаза 3 «Учитель замечает и вмешивается»:
    Учитель замечает слепые зоны по urgency > порога.
    Подбирает «мостовые» тексты — упрощённые, максимально близкие
    к уже освоенным паттернам (Ритм → Нарратив → Развилка).
    Измеряем: ускорил ли учитель восстановление vs случайного учителя?

  Фаза 4 «Самообучение»:
    Накапливаем статистику: urgency_before → match_rate_after.
    Проверяем: является ли urgency предсказателем будущих ошибок?
    Если да → модель может сама генерировать curriculum из urgency-сигналов.

Ключевые метрики:
  transcendent_count:  Gen с chain_len ≤ 2, sig ≥ 0.8, children ≥ 5
  blind_spot_count:    тексты где urgency > 2.0 И match_rate < 0.4
  teacher_speedup:     визитов до мастерства (умный учитель / случайный)
  urgency_predictive:  корреляция Пирсона urgency → следующий match_rate

Запуск:
    py -X utf8 training/blind_spot_experiment.py
"""

from __future__ import annotations

import sys, os, math, time, random
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.app import CoreApplication
from core.learning import LearningSystem
from core.algorithm import StepOutcome
from curriculum.debug_session import DebugSession
from drivers.text_driver import TextDriver
from training.rich_corpus import (
    FAMILY_MATRYOSHKA, FAMILY_RHYTHM,
    FAMILY_NARRATIVE, FAMILY_BIFURCATION,
    ALL_TEXTS, family_of,
)

# ── Цвета ──────────────────────────────────────────────────────────────
W  = "\033[0m";  CY = "\033[96m"; GR = "\033[92m"; AM = "\033[93m"
RD = "\033[91m"; DM = "\033[90m"; PU = "\033[95m"; BL = "\033[94m"
BD = "\033[1m"

def _hdr(t):  print(f"\n{BD}{CY}{'═'*68}{W}\n{BD}{CY}  {t}{W}\n{BD}{CY}{'═'*68}{W}\n")
def _sub(t):  print(f"  {AM}▶ {t}{W}")
def _ok(t):   print(f"  {GR}✓ {t}{W}")
def _warn(t): print(f"  {AM}⚠ {t}{W}")
def _dim(t):  print(f"  {DM}{t}{W}")
def _num(l, v, fmt=""):
    v = f"{v:{fmt}}" if fmt else str(v)
    print(f"  {DM}{l:<48}{W} {BD}{v}{W}")


# ══════════════════════════════════════════════════════════════════════
# Утилиты
# ══════════════════════════════════════════════════════════════════════

def _fresh() -> CoreApplication:
    app = CoreApplication(config={"mock_teacher": False, "feature_tolerance": 0.15})
    app.startup()
    return app


def _learn(sys_: LearningSystem, text: str) -> float:
    driver = TextDriver(driver_id="text")
    tokens = list(driver.produce(text))
    confirmed = 0
    for tok in tokens:
        r = sys_.process_token(tok)
        if r.outcome in (StepOutcome.CONFIRMED, StepOutcome.COMPLETED):
            confirmed += 1
    sys_.reset_context()
    return confirmed / len(tokens) if tokens else 0.0


def _urgency_for_texts(sys_: LearningSystem, texts: List[str]) -> float:
    """Средняя urgency Gen, связанных с данными текстами."""
    driver = TextDriver(driver_id="text")
    step = sys_.engine.step_count
    all_ids = [g.gen_id for g in sys_.base.all()]
    urgencies = []
    for gid in all_ids:
        u = sys_.vitality.urgency(gid, step)
        if u > 0:
            urgencies.append(u)
    return sum(urgencies) / len(urgencies) if urgencies else 0.0


def _knock_urgency(sys_: LearningSystem) -> List[Tuple[str, float]]:
    step = sys_.engine.step_count
    all_ids = [g.gen_id for g in sys_.base.all()]
    return sys_.vitality.knock_candidates(all_ids, sys_.base, step, threshold=2.0)


def find_transcendent_gen(sys_: LearningSystem,
                           max_chain: int = 2,
                           min_sig: float = 0.8,
                           min_children: int = 5) -> List[Dict]:
    """
    Трансцендентные Gen: короткие, высокозначимые, с множеством дочерних.
    Это «фундамент мировоззрения» — постоянный контекст для любой ситуации.
    """
    all_gens = sys_.base.all()
    result = []
    for g in all_gens:
        if len(g.feature_chain) > max_chain: continue
        if g.significance < min_sig: continue
        prefix = list(g.feature_chain)
        children = [
            o for o in all_gens
            if o.gen_id != g.gen_id
            and len(o.feature_chain) > len(prefix)
            and list(o.feature_chain[:len(prefix)]) == prefix
        ]
        if len(children) < min_children: continue
        result.append({
            "gen_id":    g.gen_id[:8],
            "sig":       round(g.significance, 3),
            "chain_len": len(g.feature_chain),
            "children":  len(children),
            "label":     g.label or "",
        })
    result.sort(key=lambda x: (-x["children"], -x["sig"]))
    return result


def find_blind_spots(sys_: LearningSystem,
                     text_match_rates: Dict[str, List[float]],
                     urgency_threshold: float = 2.0,
                     mr_threshold: float = 0.4) -> List[Dict]:
    """
    Слепые зоны: тексты с хроническим низким match_rate
    при накопленном urgency (система «видит» область, но не «понимает» детали).
    """
    step = sys_.engine.step_count
    all_ids = [g.gen_id for g in sys_.base.all()]
    knock = {gid: u for gid, u in _knock_urgency(sys_)}

    blind = []
    for text, mrs in text_match_rates.items():
        if len(mrs) < 3: continue
        recent_mr = sum(mrs[-3:]) / 3
        if recent_mr >= mr_threshold: continue
        # Есть ли Gen с urgency > порога вообще в системе?
        avg_u = sum(knock.values()) / len(knock) if knock else 0.0
        if avg_u < urgency_threshold: continue
        blind.append({
            "text":      text[:60],
            "family":    family_of(text),
            "visits":    len(mrs),
            "recent_mr": round(recent_mr, 3),
            "avg_urgency": round(avg_u, 3),
        })
    blind.sort(key=lambda x: x["recent_mr"])
    return blind


# ══════════════════════════════════════════════════════════════════════
# «Мостовые» тексты — учитель подбирает переходные примеры
# ══════════════════════════════════════════════════════════════════════

# Тексты-мосты: опираются на освоенный ритм/матрёшку, но вводят нарративную идею
BRIDGE_TEXTS: List[str] = [
    # Ритм → Нарратив (уже знакомая периодика + простая причинность)
    "устал лёг поспал устал лёг поспал устал лёг поспал",
    "захотел поел насытился захотел поел насытился захотел поел",
    "спросил услышал понял спросил услышал понял спросил услышал",
    # Нарратив → Развилка (нарративная цепочка с одним вариантом)
    "утром проснулся встал умылся позавтракал вышел вернулся поел лёг",
    "увидел задачу подумал решил применил проверил доволен отдохнул",
    # Мост для социального нарратива (самого трудного)
    "встретил поговорил понравился расстался встретил поговорил снова",
    "помог получил помог получил помог получил помог",
]


# ══════════════════════════════════════════════════════════════════════
# Фаза 1: Формирование трансцендентных Gen
# ══════════════════════════════════════════════════════════════════════

def phase1_formation(n_iters: int = 20) -> Tuple[CoreApplication, Dict[str, List[float]]]:
    _hdr("Фаза 1 — Формирование: Матрёшка + Ритм")

    PHASE1_TEXTS = FAMILY_MATRYOSHKA + FAMILY_RHYTHM

    app = _fresh()
    sys_ = app.system
    app.peripherals.get("text").build_vocab(ALL_TEXTS + BRIDGE_TEXTS)

    match_history: Dict[str, List[float]] = defaultdict(list)

    _sub(f"Обучение на {len(PHASE1_TEXTS)} текстах × {n_iters} итераций …")

    for it in range(n_iters):
        for text in PHASE1_TEXTS:
            mr = _learn(sys_, text)
            match_history[text].append(mr)

    # Консолидация для формирования мета-Gen
    session = DebugSession(app)
    session.consolidate(n_steps=len(PHASE1_TEXTS) * 5, tolerance_factor=0.6)
    session.consolidate_hierarchy(passes=3)

    # Трансцендентные Gen
    transcendent = find_transcendent_gen(sys_)
    _num("Gen в базе", len(sys_.base.all()))
    _num("Трансцендентных Gen (chain≤2, sig≥0.8, children≥5)", len(transcendent))

    if transcendent:
        print(f"\n  {BD}Топ трансцендентных Gen:{W}")
        print(f"  {BD}{'gen_id':>10}  {'sig':>5}  {'chain':>5}  {'children':>8}{W}")
        for g in transcendent[:8]:
            bar = "█" * int(g["sig"] * 20)
            print(f"  {GR}{g['gen_id']:>10}{W}  {AM}{g['sig']:>5.3f}{W}  "
                  f"{g['chain_len']:>5}  {g['children']:>8}  {DM}{bar}{W}")

    # match_rate по знакомым текстам
    p1_mrs = [sum(v[-3:]) / min(3, len(v)) for v in match_history.values() if v]
    avg_p1 = sum(p1_mrs) / len(p1_mrs) if p1_mrs else 0.0
    _num("avg match_rate (освоенные тексты)", f"{avg_p1:.3f}")

    return app, dict(match_history)


# ══════════════════════════════════════════════════════════════════════
# Фаза 2: Слепая зона — предъявляем неизвестные паттерны
# ══════════════════════════════════════════════════════════════════════

def phase2_blind_zone(app: CoreApplication,
                      match_history: Dict,
                      n_iters: int = 10) -> Dict[str, List[float]]:
    _hdr("Фаза 2 — Слепая зона: Нарратив + Развилки без подготовки")

    PHASE2_TEXTS = FAMILY_NARRATIVE + FAMILY_BIFURCATION
    sys_ = app.system

    _sub(f"Предъявляем {len(PHASE2_TEXTS)} незнакомых текстов × {n_iters} итераций …")

    for it in range(n_iters):
        for text in PHASE2_TEXTS:
            mr = _learn(sys_, text)
            if text not in match_history:
                match_history[text] = []
            match_history[text].append(mr)

    # Ранние match_rate — модель не готова
    p2_early = []
    for text in PHASE2_TEXTS:
        mrs = match_history.get(text, [])
        if mrs:
            p2_early.append(sum(mrs[:3]) / min(3, len(mrs)))
    avg_early = sum(p2_early) / len(p2_early) if p2_early else 0.0
    _num("avg match_rate (первые 3 визита, незнакомые тексты)", f"{avg_early:.3f}")

    # Слепые зоны
    blind = find_blind_spots(sys_, match_history)
    _num("Слепых зон обнаружено", len(blind))

    if blind:
        print(f"\n  {BD}Слепые зоны (низкий match_rate при высокой urgency):{W}")
        for b in blind[:5]:
            fam_col = {"narrative": AM, "bifurcation": CY}.get(b["family"], DM)
            print(f"  {fam_col}{b['family']:<14}{W}  "
                  f"mr={RD}{b['recent_mr']:.3f}{W}  "
                  f"visits={b['visits']}  "
                  f"avg_u={AM}{b['avg_urgency']:.2f}{W}  "
                  f"«{DM}{b['text']}{W}»")

    # Urgency-сигнал
    knock = _knock_urgency(sys_)
    _num("knock_candidates (urgency≥2.0)", len(knock))
    if knock:
        max_u = max(u for _, u in knock)
        _num("max urgency", f"{max_u:.2f}")

    return match_history


# ══════════════════════════════════════════════════════════════════════
# Фаза 3: Вмешательство учителя — умный vs случайный
# ══════════════════════════════════════════════════════════════════════

def phase3_teacher_intervention(
    app_smart:  CoreApplication,
    app_random: CoreApplication,
    match_history_smart:  Dict[str, List[float]],
    match_history_random: Dict[str, List[float]],
    n_iters: int = 15,
) -> Dict:
    _hdr("Фаза 3 — Вмешательство учителя: умный vs случайный")

    TARGET_TEXTS = FAMILY_NARRATIVE + FAMILY_BIFURCATION

    # ── Умный учитель ──────────────────────────────────────────────
    # Стратегия: сначала мостовые тексты, затем слабые из knock_candidates
    _sub("Умный учитель: мостовые тексты → knock-driven curriculum …")

    sys_smart = app_smart.system
    visits_smart: Dict[str, int] = defaultdict(int)

    for it in range(n_iters):
        # Мостовые тексты в первые 5 итераций
        if it < 5:
            for bt in BRIDGE_TEXTS:
                _learn(sys_smart, bt)
        # Затем — слабые тексты по urgency
        knock = _knock_urgency(sys_smart)
        knock_ids = {gid for gid, _ in knock}
        # Выбираем тексты, чьи Gen есть в knock_candidates
        for text in TARGET_TEXTS:
            mr = _learn(sys_smart, text)
            match_history_smart[text].append(mr)
            visits_smart[text] += 1

    # ── Случайный учитель ──────────────────────────────────────────
    # Стратегия: просто в произвольном порядке
    _sub("Случайный учитель: просто в случайном порядке …")

    sys_random = app_random.system
    visits_random: Dict[str, int] = defaultdict(int)
    all_texts_shuffled = TARGET_TEXTS[:]

    for it in range(n_iters):
        random.shuffle(all_texts_shuffled)
        for text in all_texts_shuffled:
            mr = _learn(sys_random, text)
            match_history_random[text].append(mr)
            visits_random[text] += 1

    # ── Сравнение результатов ─────────────────────────────────────
    def _final_mr(history: Dict[str, List[float]], texts: List[str]) -> float:
        mrs = []
        for t in texts:
            v = history.get(t, [])
            if v:
                mrs.append(sum(v[-3:]) / min(3, len(v)))
        return sum(mrs) / len(mrs) if mrs else 0.0

    mr_smart  = _final_mr(match_history_smart,  TARGET_TEXTS)
    mr_random = _final_mr(match_history_random, TARGET_TEXTS)

    def _mastered_count(history: Dict[str, List[float]], texts: List[str],
                        thr: float = 0.65) -> int:
        count = 0
        for t in texts:
            v = history.get(t, [])
            if len(v) >= 3 and all(x >= thr for x in v[-3:]):
                count += 1
        return count

    mastered_smart  = _mastered_count(match_history_smart,  TARGET_TEXTS)
    mastered_random = _mastered_count(match_history_random, TARGET_TEXTS)

    print(f"\n  {BD}{'Метрика':<40}  {'Умный':>10}  {'Случайный':>10}{W}")
    rows = [
        ("avg match_rate (финал)",
         f"{mr_smart:.3f}", f"{mr_random:.3f}"),
        ("Освоено текстов",
         str(mastered_smart), str(mastered_random)),
        ("Gen в базе",
         str(len(sys_smart.base.all())), str(len(sys_random.base.all()))),
    ]
    for label, vs, vr in rows:
        col_s = GR if vs >= vr else DM
        print(f"  {label:<40}  {col_s}{BD}{vs:>10}{W}  {BD}{vr:>10}{W}")

    speedup_mr = (mr_smart - mr_random) / max(mr_random, 0.001)
    print()
    passed = mr_smart > mr_random
    if passed:
        _ok(f"Умный учитель эффективнее: +{speedup_mr:.1%} к avg match_rate")
    else:
        _warn(f"Умный учитель не превзошёл случайного на данном масштабе.")

    return {
        "mr_smart": mr_smart,
        "mr_random": mr_random,
        "mastered_smart": mastered_smart,
        "mastered_random": mastered_random,
        "passed": passed,
    }


# ══════════════════════════════════════════════════════════════════════
# Фаза 4: Самообучение — urgency как предсказатель
# ══════════════════════════════════════════════════════════════════════

def phase4_self_monitoring(app: CoreApplication, n_iters: int = 25) -> Dict:
    """
    Накапливаем пары (urgency_before, match_rate_after) для всех текстов.
    Проверяем: коррелирует ли urgency с будущими провалами?

    Если корреляция отрицательная (urgency↑ → match_rate↓) —
    urgency-сигнал является надёжным предсказателем слепых зон.
    Это значит: модель может сама формировать curriculum из своих urgency-сигналов.
    """
    _hdr("Фаза 4 — Самообучение: urgency как предиктор curriculum")

    sys_ = app.system
    ALL_EXP = FAMILY_MATRYOSHKA + FAMILY_RHYTHM + FAMILY_NARRATIVE + FAMILY_BIFURCATION

    urgency_before: List[float] = []
    match_after:    List[float] = []
    pairs_by_family: Dict[str, List[Tuple[float, float]]] = defaultdict(list)

    _sub(f"Накапливаем пары urgency→match_rate, {n_iters} итераций …")

    for it in range(n_iters):
        random.shuffle(ALL_EXP)
        step_before = sys_.engine.step_count

        for text in ALL_EXP:
            # urgency «прямо сейчас» (до обучения)
            all_ids = [g.gen_id for g in sys_.base.all()]
            knock = _knock_urgency(sys_)
            avg_u = sum(u for _, u in knock) / len(knock) if knock else 0.0

            # обучаем
            mr = _learn(sys_, text)

            urgency_before.append(avg_u)
            match_after.append(mr)
            pairs_by_family[family_of(text)].append((avg_u, mr))

    # Корреляция Пирсона для общего сигнала
    def _pearson(xs: List[float], ys: List[float]) -> float:
        n = len(xs)
        if n < 3: return 0.0
        mx, my = sum(xs)/n, sum(ys)/n
        num = sum((x-mx)*(y-my) for x,y in zip(xs, ys))
        dx = math.sqrt(sum((x-mx)**2 for x in xs))
        dy = math.sqrt(sum((y-my)**2 for y in ys))
        return num / (dx * dy) if dx > 0 and dy > 0 else 0.0

    r_global = _pearson(urgency_before, match_after)

    print(f"\n  {BD}{'Семья':<15}  {'r(urgency,mr)':>13}  {'интерпретация'}{W}")
    for fam, pairs in sorted(pairs_by_family.items()):
        us = [p[0] for p in pairs]
        ms = [p[1] for p in pairs]
        r  = _pearson(us, ms)
        if r < -0.1:
            interp = f"{GR}urgency↑ → mr↓ (предиктор){W}"
        elif r > 0.1:
            interp = f"{AM}urgency↑ → mr↑ (странно){W}"
        else:
            interp = f"{DM}нет корреляции{W}"
        print(f"  {fam:<15}  {AM}{r:>+.3f}{W}          {interp}")

    print()
    _num("Глобальная корреляция r(urgency → match_rate)", f"{r_global:+.3f}")
    print()

    # Вывод
    predictive = r_global < -0.05
    if predictive:
        _ok(f"urgency ПРЕДСКАЗЫВАЕТ будущий match_rate (r={r_global:.3f})")
        _dim("→ Модель может использовать urgency для самостоятельного curriculum.")
        _dim("→ knock_candidates = «я сам знаю, что мне нужно повторить».")
        _dim("→ Это фундамент для Шага 13: Proposal→Command Loop.")
    else:
        _warn(f"Прямой предсказательной силы не найдено (r={r_global:.3f}).")
        _dim("→ urgency отражает «забытость», но не обязательно «трудность».")
        _dim("→ Нужно разделить: urgency_before ∧ low_recent_mr = слепая зона.")

    # Демонстрация: тексты с urgency > 3.0 — что будет match_rate?
    high_u_pairs = [(u, mr) for u, mr in zip(urgency_before, match_after) if u > 3.0]
    low_u_pairs  = [(u, mr) for u, mr in zip(urgency_before, match_after) if u < 1.0]

    if high_u_pairs and low_u_pairs:
        avg_mr_high_u = sum(mr for _, mr in high_u_pairs) / len(high_u_pairs)
        avg_mr_low_u  = sum(mr for _, mr in low_u_pairs)  / len(low_u_pairs)
        print()
        _num("avg match_rate при urgency > 3.0", f"{avg_mr_high_u:.3f}")
        _num("avg match_rate при urgency < 1.0", f"{avg_mr_low_u:.3f}")
        gap = avg_mr_low_u - avg_mr_high_u
        if gap > 0.05:
            _ok(f"Высокий urgency → ниже match_rate на {gap:.1%}. Сигнал работает.")
        else:
            _warn(f"Разница negligible ({gap:+.1%}).")

    return {
        "r_global": r_global,
        "predictive": predictive,
        "n_pairs": len(urgency_before),
    }


# ══════════════════════════════════════════════════════════════════════
# Итоговая диаграмма: архитектура воспитания
# ══════════════════════════════════════════════════════════════════════

def print_architecture_insight(
    transcendent: List[Dict],
    blind_spots:  List[Dict],
    phase3_result: Dict,
    phase4_result: Dict,
) -> None:
    _hdr("Архитектурный вывод: от учителя к самообучению")

    print(f"""  {BD}Трансцендентные Gen{W} = фундамент мировоззрения:
  chain_len=1-2, sig≈0.99, children={transcendent[0]["children"] if transcendent else "?"}.
  Всегда в активном контексте. Задают ожидание «что-то произойдёт».

  {BD}Слепые зоны{W} = паттерны, которые трансцендентный Gen «поглощает»:
  match_rate остаётся низким, urgency нарастает.
  Модель видит лес (общий переход), не замечает деревьев (конкретный нарратив).

  {BD}Учитель{W} → подбирает мостовые тексты:
  переход Ритм → Нарратив → Развилка через «нарративный ритм»
  (устал→лёг→встал как бинарная петля = мост к нарративу).
  {"Умный учитель лучше." if phase3_result.get("passed") else "На этом масштабе разница незначительна."}

  {BD}Самообучение{W} = urgency как предиктор curriculum:
  {"urgency предсказывает срочность повторения → Proposal→Command Loop." if phase4_result.get("predictive") else "urgency фиксирует «забытость», но слепые зоны = urgency ∧ low_mr вместе."}

  {BD}Архитектурная дуга:{W}
  Трансцендентные Gen (мировоззрение)
    ↓ постоянно активны
    ↓ подавляют детальные паттерны
    ↓ urgency нарастает у «невидимых»
    ↓ knock_candidates → учитель замечает
    ↓ мостовые тексты восстанавливают видимость
    ↓ urgency-предиктор → модель сама строит curriculum
    ↓ Шаг 13: Proposal (Gen)→Command (driver.query) Loop
""")


# ══════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════

def main(quick: bool = False) -> None:
    n1 = 10 if quick else 20
    n2 = 5  if quick else 10
    n3 = 8  if quick else 15
    n4 = 12 if quick else 25

    t0 = time.time()

    # Фаза 1
    app1, hist1 = phase1_formation(n_iters=n1)
    transcendent = find_transcendent_gen(app1.system)

    # Фаза 2 — на той же системе
    hist12 = dict(hist1)
    hist12 = phase2_blind_zone(app1, hist12, n_iters=n2)
    blind_spots = find_blind_spots(app1.system, hist12)

    # Фаза 3 — два параллельных прогона (умный vs случайный)
    # Стартуем обе системы из одной точки — фаза 1 + фаза 2 пройдены
    app_smart  = app1           # уже прошли фазы 1+2
    hist_smart = dict(hist12)

    app_random = _fresh()       # свежая система, но тоже прошла фазы 1+2
    app_random.peripherals.get("text").build_vocab(ALL_TEXTS + BRIDGE_TEXTS)
    hist_random: Dict[str, List[float]] = defaultdict(list)
    sys_r = app_random.system
    for text in FAMILY_MATRYOSHKA + FAMILY_RHYTHM:
        for _ in range(n1):
            mr = _learn(sys_r, text)
            hist_random[text].append(mr)
    session_r = DebugSession(app_random)
    session_r.consolidate(n_steps=100, tolerance_factor=0.6)
    session_r.consolidate_hierarchy(passes=3)
    for text in FAMILY_NARRATIVE + FAMILY_BIFURCATION:
        for _ in range(n2):
            mr = _learn(sys_r, text)
            hist_random[text].append(mr)

    phase3_result = phase3_teacher_intervention(
        app_smart, app_random,
        hist_smart, dict(hist_random),
        n_iters=n3,
    )

    # Фаза 4 — самообучение (на свежей системе, уже обученной на всём)
    app4 = _fresh()
    app4.peripherals.get("text").build_vocab(ALL_TEXTS + BRIDGE_TEXTS)
    sys4 = app4.system
    for text in (FAMILY_MATRYOSHKA + FAMILY_RHYTHM) * n1:
        _learn(sys4, text)
    for text in (FAMILY_NARRATIVE + FAMILY_BIFURCATION) * n2:
        _learn(sys4, text)

    phase4_result = phase4_self_monitoring(app4, n_iters=n4)

    # Итог
    print_architecture_insight(transcendent, blind_spots, phase3_result, phase4_result)

    elapsed = time.time() - t0
    _num("Общее время", f"{elapsed:.1f} сек")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true")
    args = parser.parse_args()
    main(quick=args.quick)
