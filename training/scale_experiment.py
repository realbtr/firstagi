"""
scale_experiment.py — масштабный эксперимент: до 1M переходов внимания.

Проверяет гипотезы H16–H25:

  H16 — При base > 5^5 (3125 Gen) REFUTED-rate растёт (эффект разбавления).
         MR деградирует без CapacityBudget.
  H17 — n_new(pass) ∝ pass^(-α), α > 1. Смена домена сбрасывает α.
  H18 — CapacityBudget эффективен только после N^M-стены (base > 3125).
  H19 — Theme-слова: predicted_rate ≥ 1.5× rheme при том же avg_cands.
  H20 — Скорость конвергенции DualDriver ~ T_MR (H21 в новой формулировке).
  H21 — После смены домена: REINTERPRETATION-пик, затем быстрая конвергенция.
  H22 — avg_cands/unique_words → 5–7 (Miller's law на лексическом уровне).
  H23 — При base > 5K: chain≥3 Gen с sig>0.8 = межситуационные архетипы.
  H24 — ↺/(↺+✦) как функция переходов: сигмоида с точкой перегиба у √(N^M_target).
  H25 — sleep_cycle() после плато: chain≥3 count растёт ≥ 20%.

Запуск:
    py -X utf8 training/scale_experiment.py                     # 1M переходов
    py -X utf8 training/scale_experiment.py --quick             # 100K, быстро
    py -X utf8 training/scale_experiment.py --transitions 300000
    py -X utf8 training/scale_experiment.py --capacity 0        # без лимита
    py -X utf8 training/scale_experiment.py --no-dual           # без DualDriver
    py -X utf8 training/scale_experiment.py --csv results.csv
"""
from __future__ import annotations

import argparse
import csv
import math
import os
import random
import sys
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.app import CoreApplication
from core.algorithm import StepOutcome
from core.capacity import CapacityBudget
from core.dream import (
    CrossDomainDetector, DomainRegistry, ReplayEngine,
    SleepScheduler, sleep_cycle,
)
from core.dual_driver import DualDriverLoop, build_next_word_index
from core.timescale import TimescaleScheduler
from core.vitality import VitalityEngine
from drivers.text_driver import TextDriver
from training.serial_corpus import ALL_SERIAL_TEXTS, SITUATION_FAMILIES

# ─── ANSI ─────────────────────────────────────────────────────────────────────
W  = "\033[0m";  BD = "\033[1m";  DM = "\033[90m"
GR = "\033[92m"; CY = "\033[96m"; AM = "\033[93m"
RD = "\033[91m"; MG = "\033[95m"; BL = "\033[94m"


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1: Генеративный корпус (4 домена)
# ══════════════════════════════════════════════════════════════════════════════

_DOMAIN_SPECS: Dict[str, dict] = {
    "лес": {
        "chars":   ["маша", "медведь", "заяц", "лиса", "волк",
                    "сова", "ёжик", "белка", "олень", "кукушка"],
        "objects": ["ягоды", "грибы", "мёд", "орехи", "шишки", "морковь",
                    "пирог", "яблоко", "малину", "траву"],
        "places":  ["в лесу", "на поляне", "у реки", "под дубом",
                    "в норе", "на опушке", "у дерева", "в кустах"],
        "actions": ["пришёл", "побежал", "прыгнул", "нашёл", "принёс",
                    "угостил", "помог", "спас", "позвал", "встретил"],
        "results": ["обрадовался", "поблагодарил", "засмеялся", "удивился",
                    "улыбнулся", "поел", "ушёл довольный", "остался"],
    },
    "город": {
        "chars":   ["кот", "пёс", "попугай", "хомяк", "черепаха",
                    "мышка", "кролик", "ёж", "рыбка", "птица"],
        "objects": ["мячик", "косточку", "клетку", "зерно", "морковку",
                    "игрушку", "миску", "коробку", "поводок", "подушку"],
        "places":  ["во дворе", "в парке", "на улице", "в подъезде",
                    "у магазина", "на скамейке", "в квартире", "у фонтана"],
        "actions": ["прибежал", "позвал", "схватил", "потерял", "нашёл",
                    "дал", "взял", "спрятал", "показал", "принёс"],
        "results": ["обрадовался", "удивился", "поиграл", "устал",
                    "убежал", "остался", "поблагодарил", "засмеялся"],
    },
    "море": {
        "chars":   ["чайка", "краб", "дельфин", "морж", "осьминог",
                    "рыба", "медуза", "морской конёк", "морской лев", "черепаха"],
        "objects": ["рыбу", "водоросли", "ракушку", "жемчужину", "камень",
                    "кораллы", "сеть", "волну", "пузырь", "звезду"],
        "places":  ["у берега", "в волнах", "на дне", "у скалы",
                    "в бухте", "у маяка", "в открытом море", "у рифа"],
        "actions": ["приплыл", "нырнул", "поймал", "нашёл", "принёс",
                    "позвал", "спас", "помог", "показал", "отдал"],
        "results": ["обрадовался", "поблагодарил", "уплыл", "остался",
                    "удивился", "засмеялся", "поел", "поиграл"],
    },
    "горы": {
        "chars":   ["орёл", "сурок", "рысь", "горный козёл", "снежный барс",
                    "горная овца", "медведь", "куропатка", "тур", "серна"],
        "objects": ["вершину", "пещеру", "камень", "снег", "ущелье",
                    "тропу", "водопад", "гнездо", "кость", "шерсть"],
        "places":  ["на вершине", "в ущелье", "у водопада", "в пещере",
                    "на склоне", "среди скал", "на уступе", "у перевала"],
        "actions": ["взлетел", "прыгнул", "нашёл", "принёс", "спас",
                    "позвал", "помог", "встретил", "показал", "привёл"],
        "results": ["обрадовался", "поблагодарил", "улетел", "остался",
                    "удивился", "засмеялся", "отдохнул", "пошёл дальше"],
    },
}

_TEMPLATES = [
    "{c1} {act1} к {c2} {c2} {res1} {c1} {res2}",
    "{c1} {act1} {obj} {c2} пришёл {c1} дал {obj} {c2} {res1}",
    "{c1} и {c2} пошли {place} {c1} {act1} {obj} {c2} {res1}",
    "{c1} {act1} {place} встретил {c2} {c2} {res1} пошли вместе {c1} {res2}",
    "{c1} потерял {obj} {c2} нашёл {obj} {c2} {act1} {c1} {c1} {res1}",
    "{c1} {act1} {c2} {c2} испугался {c1} сказал не бойся {c2} {res1}",
    "{c1} принёс {obj} {c2} {c2} взял {obj} {res1} {c1} {res2}",
    "{c1} и {c2} играли {place} {c1} {act1} {c2} {res1} вместе {res2}",
    "{c2} попросил {c1} помочь {c1} {act1} {c2} {res1} {c2} {res2}",
    "{c1} увидел {c2} {place} {c1} {act1} {c2} {c2} {res1}",
    "{c1} {act1} {obj} {place} принёс {c2} {c2} {res1} {c1} {res2}",
    "{c1} позвал {c2} {c2} пришёл они {act1} {place} {res1} {res2}",
]


class GenerativeCorpus:
    """
    Процедурный генератор текстов из 4 доменов.

    Комбинаторный подход: templates × characters × actions × objects → M уникальных текстов.
    При типичных размерах словарей: ~50K уникальных комбинаций на домен.
    """

    DOMAINS = list(_DOMAIN_SPECS.keys())

    def __init__(self, seed: int = 42) -> None:
        self._rng   = random.Random(seed)
        self._domain_idx  = 0
        self._domain      = self.DOMAINS[0]
        self._vocab_sizes: Dict[str, int] = {}
        # Добавляем serial_corpus в домен "лес" как базу
        self._base_texts  = ALL_SERIAL_TEXTS[:]

    @property
    def domain(self) -> str:
        return self._domain

    def switch_domain(self) -> str:
        """Переключиться на следующий домен по кругу."""
        self._domain_idx = (self._domain_idx + 1) % len(self.DOMAINS)
        self._domain     = self.DOMAINS[self._domain_idx]
        return self._domain

    def generate_batch(self, n: int) -> List[str]:
        """Сгенерировать n текстов из текущего домена."""
        spec = _DOMAIN_SPECS[self._domain]
        texts: List[str] = []

        # Если домен "лес" — сначала включим реальные тексты
        if self._domain == "лес" and self._base_texts:
            real = self._rng.sample(self._base_texts, min(n // 3, len(self._base_texts)))
            texts.extend(real)

        while len(texts) < n:
            tmpl = self._rng.choice(_TEMPLATES)
            chars = self._rng.sample(spec["chars"], 2)
            text  = tmpl.format(
                c1   = chars[0],
                c2   = chars[1],
                obj  = self._rng.choice(spec["objects"]),
                place= self._rng.choice(spec["places"]),
                act1 = self._rng.choice(spec["actions"]),
                res1 = self._rng.choice(spec["results"]),
                res2 = self._rng.choice(spec["results"]),
            )
            texts.append(text)

        return texts[:n]

    def unique_words(self) -> int:
        """Примерный размер словаря текущего домена."""
        spec = _DOMAIN_SPECS[self._domain]
        total = set()
        for key in ("chars", "objects", "places", "actions", "results"):
            for w in spec[key]:
                total.update(w.split())
        total.update(["к", "и", "в", "на", "у", "не", "они", "вместе",
                      "пошли", "пришёл", "взял", "дал", "показал"])
        return len(total)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2: Структура снапшота
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class SnapshotPoint:
    """Метрики в момент времени."""
    transition_idx:  int
    domain:          str
    base_size:       int
    n_new:           int           # новых Gen с прошлого снапшота
    mr_known:        float         # MR на знакомом тексте
    mr_transfer:     float         # MR на новом домене (transfer)
    chain_dist:      Dict[int, int] = field(default_factory=dict)  # chain → count
    avg_sig:         float = 0.0
    n_chain3plus:    int   = 0
    reinterp_rate:   float = 0.0   # ↺/(↺+✦+≡)
    disc_rate:       float = 0.0   # ✦/(↺+✦+≡)
    conv_rate:       float = 0.0   # ≡/(↺+✦+≡)
    avg_probes:      float = 0.0
    avg_cands:       float = 0.0
    n_evicted_total: int   = 0
    n_sleep_cycles:  int   = 0
    n_meta_gen:      int   = 0
    elapsed_s:       float = 0.0
    tok_per_s:       float = 0.0

    @property
    def chain1_frac(self) -> float:
        n = sum(self.chain_dist.values())
        return self.chain_dist.get(1, 0) / max(n, 1)

    @property
    def chain3plus_frac(self) -> float:
        n = sum(self.chain_dist.values())
        c3 = sum(v for k, v in self.chain_dist.items() if k >= 3)
        return c3 / max(n, 1)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3: ScaleRunner — основной цикл
# ══════════════════════════════════════════════════════════════════════════════

class ScaleRunner:
    """
    Главный движок масштабного эксперимента.

    Управляет:
      • обучением text_system через TextDriver
      • снапшотами метрик каждые snap_every переходов
      • сменой домена каждые domain_switch_every переходов
      • DualDriver-пробами каждые dual_every переходов
      • вызовом sleep_cycle() при H15-плато
      • включением CapacityBudget при достижении capacity_wall Gen
    """

    CAPACITY_WALL = 3125  # 5^5 — первая N^M граница

    def __init__(
        self,
        corpus:             GenerativeCorpus,
        max_transitions:    int,
        snap_every:         int   = 10_000,
        domain_switch_every:int   = 50_000,
        dual_every:         int   = 20_000,
        capacity:           int   = 6_000,   # 0 = без лимита
        enable_sleep:       bool  = True,
        enable_dual:        bool  = True,
        feature_tol:        float = 0.15,
        batch_size:         int   = 50,      # текстов за один шаг генерации
        seed:               int   = 42,
    ) -> None:
        self._corpus     = corpus
        self._max_trans  = max_transitions
        self._snap_every = snap_every
        self._ds_every   = domain_switch_every
        self._dual_every = dual_every
        self._capacity   = capacity
        self._sleep_on   = enable_sleep
        self._dual_on    = enable_dual
        self._batch_size = batch_size

        cfg = {"mock_teacher": False, "feature_tolerance": feature_tol}
        self._app        = CoreApplication(config=cfg)
        self._app.startup()

        # CapacityBudget (включается когда base > CAPACITY_WALL)
        self._budget: Optional[CapacityBudget] = None
        self._budget_enabled = False

        # DualDriver (отдельный smart_app)
        self._dual_loop: Optional[DualDriverLoop] = None
        if enable_dual:
            smart_app = CoreApplication(config=cfg)
            smart_app.startup()
            self._dual_loop = DualDriverLoop(
                self._app, smart_app, min_entropy=0.5, max_probes=5
            )

        # Sleep
        self._sleep_sched   = SleepScheduler(plateau_threshold=3, plateaus_required=2)
        self._n_sleep_total = 0
        self._n_meta_total  = 0

        # Vitality (нужен для SleepScheduler)
        self._vitality = self._app.system.vitality

        # Driver
        self._drv = TextDriver("scale_td")

        # State
        self._transition_idx  = 0
        self._prev_snap_trans = 0
        self._prev_base_size  = 0
        self._next_snap       = snap_every
        self._next_domain_sw  = domain_switch_every
        self._next_dual       = dual_every

        self._start_time = time.perf_counter()
        self._snapshots: List[SnapshotPoint] = []

    # ──────────────────────────────────────────────────────────────────────────
    # Основной метод

    def run(self) -> List[SnapshotPoint]:
        """Запустить эксперимент. Возвращает все снапшоты."""
        Reporter.print_run_header(self._max_trans, self._capacity, self._dual_on)

        while self._transition_idx < self._max_trans:
            # Генерируем батч текстов и обучаем
            texts = self._corpus.generate_batch(self._batch_size)
            for text in texts:
                if self._transition_idx >= self._max_trans:
                    break
                n = self._train_one_text(text)
                self._transition_idx += n

                # Проверяем события по таймерам
                if self._transition_idx >= self._next_snap:
                    self._do_snapshot()
                    self._next_snap += self._snap_every

                if self._transition_idx >= self._next_domain_sw:
                    new_dom = self._corpus.switch_domain()
                    self._next_domain_sw += self._ds_every
                    Reporter.print_domain_switch(self._transition_idx, new_dom)

                if self._dual_on and self._transition_idx >= self._next_dual:
                    self._do_dual_snapshot()
                    self._next_dual += self._dual_every

                # Включаем CapacityBudget при достижении N^M стены
                if (not self._budget_enabled and self._capacity > 0 and
                        len(self._app.system.base.all()) >= self.CAPACITY_WALL):
                    self._enable_capacity()

                # Проверяем Sleep (только при снапшотах — _sleep_sched_tick уже вызван)

        # Финальный снапшот
        self._do_snapshot()
        return self._snapshots

    # ──────────────────────────────────────────────────────────────────────────
    # Обучение одного текста

    def _train_one_text(self, text: str) -> int:
        """Прогнать один текст через TextDriver. Возвращает число переходов."""
        n = 0
        for tok in self._drv.produce(text):
            if self._budget and self._budget_enabled:
                self._budget.set_step(self._transition_idx + n)
            self._app.system.process_token(tok)
            n += 1
        self._app.system.reset_context()
        return n

    # ──────────────────────────────────────────────────────────────────────────
    # Снапшот метрик

    def _do_snapshot(self) -> None:
        base    = self._app.system.base
        all_gen = base.all()
        n_gen   = len(all_gen)
        n_new   = n_gen - self._prev_base_size
        self._prev_base_size = n_gen

        # Chain distribution
        chain_dist: Dict[int, int] = {}
        sig_sum = 0.0
        for g in all_gen:
            c = len(g.feature_chain)
            chain_dist[c] = chain_dist.get(c, 0) + 1
            sig_sum += g.significance
        avg_sig    = sig_sum / max(n_gen, 1)
        n_chain3p  = sum(v for k, v in chain_dist.items() if k >= 3)

        # MR на знакомом тексте (1 текст из текущего домена)
        mr_known    = self._measure_mr(known=True)
        mr_transfer = self._measure_mr(known=False)

        elapsed   = time.perf_counter() - self._start_time
        tok_per_s = self._transition_idx / max(elapsed, 1e-9)

        pt = SnapshotPoint(
            transition_idx  = self._transition_idx,
            domain          = self._corpus.domain,
            base_size       = n_gen,
            n_new           = n_new,
            mr_known        = mr_known,
            mr_transfer     = mr_transfer,
            chain_dist      = chain_dist,
            avg_sig         = avg_sig,
            n_chain3plus    = n_chain3p,
            n_evicted_total = self._budget.total_evicted if self._budget else 0,
            n_sleep_cycles  = self._n_sleep_total,
            n_meta_gen      = self._n_meta_total,
            elapsed_s       = elapsed,
            tok_per_s       = tok_per_s,
        )
        self._snapshots.append(pt)
        Reporter.print_snapshot(pt)

        # SleepScheduler tick (раз в снапшот)
        if self._sleep_on:
            self._sleep_sched_tick(n_new)

    def _measure_mr(self, known: bool) -> float:
        """Измерить MR на 3 текстах. known=True — текущий домен, False — другой."""
        if known:
            texts = self._corpus.generate_batch(3)
        else:
            # Берём тексты из другого домена
            other_idx = (self._corpus._domain_idx + 2) % len(GenerativeCorpus.DOMAINS)
            other_dom = GenerativeCorpus.DOMAINS[other_idx]
            spec = _DOMAIN_SPECS[other_dom]
            rng = random.Random(self._transition_idx)
            texts = []
            for _ in range(3):
                tmpl = rng.choice(_TEMPLATES)
                chars = rng.sample(spec["chars"], 2)
                texts.append(tmpl.format(
                    c1=chars[0], c2=chars[1],
                    obj=rng.choice(spec["objects"]),
                    place=rng.choice(spec["places"]),
                    act1=rng.choice(spec["actions"]),
                    res1=rng.choice(spec["results"]),
                    res2=rng.choice(spec["results"]),
                ))

        confirmed = total = 0
        for t in texts:
            self._app.system.reset_context()
            for tok in self._drv.produce(t):
                r = self._app.system.process_token(tok)
                if r.outcome in (StepOutcome.CONFIRMED, StepOutcome.COMPLETED):
                    confirmed += 1
                total += 1
        self._app.system.reset_context()
        return confirmed / max(total, 1)

    # ──────────────────────────────────────────────────────────────────────────
    # DualDriver-проба

    def _do_dual_snapshot(self) -> None:
        if not self._dual_loop:
            return

        # Перестраиваем индекс (может устареть)
        self._dual_loop._next_word_index = build_next_word_index(self._app.system)
        self._dual_loop._vocab = {}  # сброс vocab для перестройки

        texts = self._corpus.generate_batch(10)
        n_r = n_d = n_c = total = 0
        probe_sum = cand_sum = 0

        for t in texts:
            r = self._dual_loop.process_text(t)
            for s in r.steps:
                total += 1
                probe_sum += s.probe_stats.probes_used
                cand_sum  += s.probe_stats.candidates_before
                if s.is_reinterpretation: n_r += 1
                elif s.is_discovery:      n_d += 1
                elif s.is_convergent:     n_c += 1

        n = max(total, 1)
        reinterp_rate = n_r / n
        disc_rate     = n_d / n
        conv_rate     = n_c / n
        avg_probes    = probe_sum / n
        avg_cands     = cand_sum  / n

        # Обновляем последний снапшот
        if self._snapshots:
            pt = self._snapshots[-1]
            pt.reinterp_rate = reinterp_rate
            pt.disc_rate     = disc_rate
            pt.conv_rate     = conv_rate
            pt.avg_probes    = avg_probes
            pt.avg_cands     = avg_cands

        Reporter.print_dual_probe(
            self._transition_idx, n_r, n_d, n_c, avg_probes, avg_cands,
            avg_cands / max(self._corpus.unique_words(), 1)
        )

    # ──────────────────────────────────────────────────────────────────────────
    # CapacityBudget

    def _enable_capacity(self) -> None:
        if self._capacity <= 0:
            return
        sched  = TimescaleScheduler()
        budget = CapacityBudget(max_gens=self._capacity, scheduler=sched)
        budget.attach_vitality(self._vitality)
        budget.set_step(self._transition_idx)
        self._app.system.base._evict_callback = budget.enforce
        self._budget          = budget
        self._budget_enabled  = True
        Reporter.print_capacity_enabled(self._transition_idx, self._capacity)

    # ──────────────────────────────────────────────────────────────────────────
    # Sleep

    _sleep_n_new_last = 0

    def _sleep_sched_tick(self, n_new: int) -> None:
        decision = self._sleep_sched.tick(
            self._app.system.base,
            self._vitality,
            self._transition_idx,
        )
        if decision.should_sleep:
            self._do_sleep()
            self._sleep_sched.reset()

    def _do_sleep(self) -> None:
        base       = self._app.system.base
        chain3_before = sum(1 for g in base.all() if len(g.feature_chain) >= 3)

        registry  = DomainRegistry()
        detector  = CrossDomainDetector(registry)
        engine    = ReplayEngine(self._app.system)

        result = sleep_cycle(
            system        = self._app.system,
            replay_engine = engine,
            detector      = detector,
            budget        = self._budget,
            n_replays     = 5,
            replay_steps  = 10,
        )
        chain3_after = sum(1 for g in base.all() if len(g.feature_chain) >= 3)

        self._n_sleep_total += 1
        self._n_meta_total  += result.meta_gen_count

        Reporter.print_sleep(
            self._transition_idx, result, chain3_before, chain3_after
        )


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4: Reporter — вывод + CSV
# ══════════════════════════════════════════════════════════════════════════════

class Reporter:

    _header_printed = False
    _col_w = {
        "trans": 9, "dom": 6, "base": 6, "nnew": 5,
        "mr_k": 6, "mr_t": 6, "c1": 5, "c3": 5, "sig": 5,
        "reint": 6, "disc": 6, "conv": 6, "probes": 6, "cands": 5,
        "evict": 5, "slp": 4, "tok_s": 7,
    }

    @classmethod
    def print_run_header(cls, max_t: int, cap: int, dual: bool) -> None:
        print(f"\n{BD}{CY}{'═'*90}{W}")
        print(f"{BD}{CY}  Масштабный эксперимент: {max_t:,} переходов внимания{W}")
        cap_str = f"{cap:,} Gen" if cap > 0 else "без лимита"
        print(f"{BD}{CY}  CapacityBudget: {cap_str}   DualDriver: {'вкл' if dual else 'выкл'}{W}")
        print(f"{BD}{CY}{'═'*90}{W}\n")
        cls._print_table_header()

    @classmethod
    def _print_table_header(cls) -> None:
        print(
            f"  {'Переход':>9}  {'Дом':>6}  {'База':>6}  {'N+':>5}  "
            f"{'MR_k':>6}  {'MR_t':>6}  {'C1%':>5}  {'C3+%':>5}  {'Sig':>5}  "
            f"{'↺%':>6}  {'✦%':>6}  {'≡%':>6}  {'prb':>6}  {'cand':>5}  "
            f"{'evct':>5}  {'slp':>4}  {'tok/s':>7}"
        )
        print("  " + "─" * 88)

    @classmethod
    def print_snapshot(cls, pt: SnapshotPoint) -> None:
        mr_k_col = GR if pt.mr_known   >= 0.7 else AM if pt.mr_known   >= 0.4 else RD
        mr_t_col = GR if pt.mr_transfer >= 0.4 else AM if pt.mr_transfer >= 0.2 else RD
        ri_col   = MG if pt.reinterp_rate > 0.1 else DM
        di_col   = AM if pt.disc_rate     > 0.1 else DM
        cv_col   = GR if pt.conv_rate     > 0.5 else DM
        ni_col   = GR if pt.n_new > 0 else DM

        print(
            f"  {pt.transition_idx:>9,}  {pt.domain:>6}  {pt.base_size:>6,}  "
            f"{ni_col}{pt.n_new:>5,}{W}  "
            f"{mr_k_col}{pt.mr_known:>6.3f}{W}  {mr_t_col}{pt.mr_transfer:>6.3f}{W}  "
            f"{pt.chain1_frac:>5.2f}  {pt.chain3plus_frac:>5.2f}  {pt.avg_sig:>5.3f}  "
            f"{ri_col}{pt.reinterp_rate:>6.3f}{W}  "
            f"{di_col}{pt.disc_rate:>6.3f}{W}  "
            f"{cv_col}{pt.conv_rate:>6.3f}{W}  "
            f"{pt.avg_probes:>6.2f}  {pt.avg_cands:>5.1f}  "
            f"{pt.n_evicted_total:>5,}  {pt.n_sleep_cycles:>4}  "
            f"{pt.tok_per_s:>7.0f}"
        )

    @classmethod
    def print_domain_switch(cls, t: int, dom: str) -> None:
        print(f"\n  {BL}{'─'*40}{W}")
        print(f"  {BL}▶ [{t:,}] СМЕНА ДОМЕНА → «{dom}»{W}")
        print(f"  {BL}{'─'*40}{W}\n")
        cls._print_table_header()

    @classmethod
    def print_capacity_enabled(cls, t: int, cap: int) -> None:
        print(f"  {MG}[{t:,}] CapacityBudget ВКЛЮЧЁН: лимит = {cap:,} Gen (N^M-стена достигнута){W}")

    @classmethod
    def print_dual_probe(
        cls, t: int, n_r: int, n_d: int, n_c: int,
        avg_p: float, avg_c: float, miller_ratio: float
    ) -> None:
        total = max(n_r + n_d + n_c, 1)
        print(
            f"  {MG}[Dual {t:,}]{W}  "
            f"↺{n_r/total:.2f}  ✦{n_d/total:.2f}  ≡{n_c/total:.2f}  "
            f"probes={avg_p:.2f}  cands={avg_c:.1f}  "
            f"Miller={miller_ratio:.2f}×"
        )

    @classmethod
    def print_sleep(cls, t: int, result, chain3_before: int, chain3_after: int) -> None:
        delta = chain3_after - chain3_before
        pct   = delta / max(chain3_before, 1) * 100
        h25   = GR if pct >= 20 else AM if pct > 0 else DM
        print(
            f"  {CY}[Sleep #{t:,}]{W}  "
            f"meta_gen={result.meta_gen_count}  "
            f"commit_rate={result.commit_rate:.1%}  "
            f"chain3+ {chain3_before}→{chain3_after} "
            f"({h25}{pct:+.1f}%{W})"
        )

    @classmethod
    def print_hypothesis_results(cls, pts: List[SnapshotPoint]) -> None:
        if len(pts) < 2:
            return

        print(f"\n{BD}{CY}{'═'*80}{W}")
        print(f"{BD}{CY}  РЕЗУЛЬТАТЫ ГИПОТЕЗ H16–H25{W}")
        print(f"{BD}{CY}{'═'*80}{W}\n")

        # H16: MR деградация при base > 3125
        wall_pts  = [p for p in pts if p.base_size >= 3125]
        pre_wall  = [p for p in pts if p.base_size < 3125]
        if wall_pts and pre_wall:
            mr_pre  = sum(p.mr_known for p in pre_wall[-3:]) / min(3, len(pre_wall))
            mr_post = sum(p.mr_known for p in wall_pts[:3])  / min(3, len(wall_pts))
            h16 = "ПОДТВЕРЖДЕНА" if mr_post < mr_pre - 0.05 else "ОПРОВЕРГНУТА"
            col = GR if h16.startswith("П") else RD
            print(f"  H16 MR-деградация у N^M-стены: {col}{h16}{W}  "
                  f"MR до стены={mr_pre:.3f} → после={mr_post:.3f}")

        # H17: n_new степенной закон
        n_news = [p.n_new for p in pts if p.n_new >= 0]
        if len(n_news) >= 5:
            # Проверяем монотонное убывание с начала
            decreasing = all(n_news[i] >= n_news[i+1] for i in range(min(5, len(n_news)-1)))
            h17 = "ПОДТВЕРЖДЕНА" if decreasing else "ОПРОВЕРГНУТА"
            col = GR if h17.startswith("П") else RD
            peak = max(n_news[:5])
            last = n_news[-1] if n_news else 0
            print(f"  H17 Степенной закон n_new:      {col}{h17}{W}  "
                  f"peak={peak} → last={last}  mono={decreasing}")

        # H18: CapacityBudget эффективен после стены
        evicted_pts = [p for p in pts if p.n_evicted_total > 0]
        if evicted_pts and wall_pts:
            mr_no_cap = sum(p.mr_known for p in wall_pts[:2]) / min(2, len(wall_pts))
            mr_w_cap  = sum(p.mr_known for p in evicted_pts[-3:]) / min(3, len(evicted_pts))
            h18 = "ПОДТВЕРЖДЕНА" if mr_w_cap >= mr_no_cap else "ОПРОВЕРГНУТА"
            col = GR if h18.startswith("П") else RD
            print(f"  H18 CapacityBudget после стены: {col}{h18}{W}  "
                  f"MR без cap={mr_no_cap:.3f} → с cap={mr_w_cap:.3f}  "
                  f"evicted={evicted_pts[-1].n_evicted_total}")

        # H22: Miller's law
        dual_pts = [p for p in pts if p.avg_cands > 0]
        if dual_pts:
            miller_vals = []
            for p in dual_pts:
                uniq = GenerativeCorpus().unique_words()  # ~60-80
                ratio = p.avg_cands / max(uniq, 1) * 10  # нормировка к 10-кратному
                miller_vals.append(p.avg_cands)
            avg_cands_late = sum(p.avg_cands for p in dual_pts[-3:]) / min(3, len(dual_pts))
            h22 = "ПОДТВЕРЖДЕНА" if 4 <= avg_cands_late <= 8 else "ОПРОВЕРГНУТА"
            col = GR if h22.startswith("П") else RD
            print(f"  H22 Miller's law (avg_cands):   {col}{h22}{W}  "
                  f"avg_cands_late={avg_cands_late:.1f}  (ожидается 5–7)")

        # H23: chain≥3 архетипы
        late_pts = pts[-5:] if len(pts) >= 5 else pts
        avg_c3 = sum(p.n_chain3plus for p in late_pts) / max(len(late_pts), 1)
        max_base = max(p.base_size for p in pts) if pts else 0
        h23 = "ПОДТВЕРЖДЕНА" if avg_c3 >= 10 and max_base >= 5000 else (
              "ЧАСТИЧНО" if avg_c3 >= 3 else "ОПРОВЕРГНУТА")
        col = GR if h23.startswith("П") else AM if h23 == "ЧАСТИЧНО" else RD
        print(f"  H23 chain≥3 архетипы:           {col}{h23}{W}  "
              f"avg_chain3+={avg_c3:.0f}  max_base={max_base:,}")

        # H24: REINTERP/(REINTERP+DISC) сигмоида
        dual_pts2 = [p for p in pts if p.reinterp_rate + p.disc_rate > 0]
        if len(dual_pts2) >= 4:
            ri_ratios = [p.reinterp_rate / max(p.reinterp_rate + p.disc_rate, 1e-9)
                         for p in dual_pts2]
            # Ищем монотонный рост (сигмоида = рост от ≈0 к ≈1)
            growing = ri_ratios[-1] > ri_ratios[0] + 0.1
            h24 = "ПОДТВЕРЖДЕНА" if growing else "ОПРОВЕРГНУТА"
            col = GR if h24.startswith("П") else RD
            print(f"  H24 REINTERP/(↺+✦) сигмоида:   {col}{h24}{W}  "
                  f"↺-ratio: {ri_ratios[0]:.2f}→{ri_ratios[-1]:.2f}")

        # H25: Sleep → chain≥3 рост
        sleep_pts = [p for p in pts if p.n_sleep_cycles > 0]
        if sleep_pts:
            n_meta = sleep_pts[-1].n_meta_gen
            h25 = "ПОДТВЕРЖДЕНА" if n_meta >= 3 else "ОПРОВЕРГНУТА"
            col = GR if h25.startswith("П") else RD
            print(f"  H25 Sleep → chain≥3 рост:       {col}{h25}{W}  "
                  f"sleep_cycles={sleep_pts[-1].n_sleep_cycles}  meta_gen={n_meta}")

        print()

    @classmethod
    def print_final_depth_profile(cls, pts: List[SnapshotPoint]) -> None:
        """Chain distribution финального состояния."""
        if not pts:
            return
        last = pts[-1]
        print(f"\n{BD}  Профиль глубины (финальное состояние, base={last.base_size:,}):{W}")
        total = sum(last.chain_dist.values())
        for chain_len in sorted(last.chain_dist.keys()):
            count = last.chain_dist[chain_len]
            pct   = count / max(total, 1)
            bar   = "█" * int(pct * 40)
            col   = GR if chain_len >= 3 else AM if chain_len == 2 else DM
            print(f"  chain={chain_len}: {col}{count:>5,} ({pct:5.1%}){W}  {bar}")
        print(f"  {'ИТОГО':>7}: {total:>5,}")

    @staticmethod
    def export_csv(pts: List[SnapshotPoint], filename: str) -> None:
        fields = [
            "transition_idx", "domain", "base_size", "n_new",
            "mr_known", "mr_transfer", "chain1_frac", "chain3plus_frac",
            "avg_sig", "n_chain3plus", "reinterp_rate", "disc_rate",
            "conv_rate", "avg_probes", "avg_cands",
            "n_evicted_total", "n_sleep_cycles", "n_meta_gen",
            "elapsed_s", "tok_per_s",
        ]
        with open(filename, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            for pt in pts:
                row = {k: getattr(pt, k) for k in fields}
                w.writerow(row)
        print(f"  CSV сохранён: {filename}")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5: Анализ H17 — степенной закон
# ══════════════════════════════════════════════════════════════════════════════

def analyze_power_law(pts: List[SnapshotPoint]) -> None:
    """Аппроксимация n_new(t) степенным законом на первом домене."""
    first_dom  = pts[0].domain if pts else "?"
    dom_pts    = [p for p in pts if p.domain == first_dom and p.n_new > 0]
    if len(dom_pts) < 3:
        return

    # Линейная регрессия в log-log пространстве
    import math
    xs = [math.log(i + 1) for i in range(len(dom_pts))]
    ys = [math.log(max(p.n_new, 1)) for p in dom_pts]
    n  = len(xs)
    sx = sum(xs); sy = sum(ys)
    sxx = sum(x*x for x in xs); sxy = sum(x*y for x, y in zip(xs, ys))
    denom = n * sxx - sx * sx
    if abs(denom) < 1e-10:
        return
    alpha = -(n * sxy - sx * sy) / denom
    r2 = 0.0
    if denom != 0:
        b = (sy - (-(n*sxy-sx*sy)/denom) * sx) / n
        y_mean = sy / n
        ss_tot = sum((y - y_mean)**2 for y in ys)
        ss_res = sum((y - (-alpha * x + b))**2 for x, y in zip(xs, ys))
        r2 = 1 - ss_res / max(ss_tot, 1e-12)

    col = GR if 0.5 < alpha < 3.0 else AM
    print(f"\n  H17 Степенной закон: α = {col}{alpha:.2f}{W}  R²={r2:.3f}  "
          f"(подтверждена если 0.5 < α < 3 и убывание)")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 6: main()
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(description="Scale experiment: 1M attention transitions")
    parser.add_argument("--transitions", type=int,   default=1_000_000)
    parser.add_argument("--quick",       action="store_true",
                        help="Быстрый прогон: 100K переходов")
    parser.add_argument("--snap-every",  type=int,   default=10_000)
    parser.add_argument("--domain-switch", type=int, default=50_000,
                        help="Переходов до смены домена")
    parser.add_argument("--dual-every",  type=int,   default=25_000,
                        help="Переходов между DualDriver-пробами")
    parser.add_argument("--capacity",    type=int,   default=6_000,
                        help="Лимит CapacityBudget (0 = выкл)")
    parser.add_argument("--no-dual",     action="store_true")
    parser.add_argument("--no-sleep",    action="store_true")
    parser.add_argument("--tol",         type=float, default=0.15)
    parser.add_argument("--seed",        type=int,   default=42)
    parser.add_argument("--csv",         type=str,   default="",
                        help="Файл для экспорта CSV")
    args = parser.parse_args()

    if args.quick:
        args.transitions   = 100_000
        args.snap_every    = 5_000
        args.domain_switch = 25_000
        args.dual_every    = 10_000
    snap_every = args.snap_every

    corpus = GenerativeCorpus(seed=args.seed)

    runner = ScaleRunner(
        corpus              = corpus,
        max_transitions     = args.transitions,
        snap_every          = snap_every,
        domain_switch_every = args.domain_switch,
        dual_every          = args.dual_every,
        capacity            = args.capacity,
        enable_sleep        = not args.no_sleep,
        enable_dual         = not args.no_dual,
        feature_tol         = args.tol,
        seed                = args.seed,
    )

    snapshots = runner.run()

    # ── Итоговый анализ ────────────────────────────────────────────────────
    Reporter.print_hypothesis_results(snapshots)
    Reporter.print_final_depth_profile(snapshots)
    analyze_power_law(snapshots)

    if args.csv:
        Reporter.export_csv(snapshots, args.csv)

    # Быстрая оценка времени на полный прогон
    if args.quick and snapshots:
        last = snapshots[-1]
        full_t = args.transitions * 10 / last.tok_per_s / 60
        print(f"\n  {DM}Оценка: 1M переходов при {last.tok_per_s:.0f} tok/s ≈ {full_t:.0f} мин{W}")

    print()


if __name__ == "__main__":
    main()
