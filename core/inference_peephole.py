"""
core/inference_peephole.py — «Глазок» инференса.

Тонкая обёртка над LearningSystem.process_token():
захватывает состояние контекста после каждого токена и позволяет наблюдать:

  * Чем «интересуется» система — топ активных Gen по уровню цепочки
  * Что значат Gen максимального уровня в текущем контексте
  * Насколько система уверена в актуальности каждого Gen
  * Как часто инициируются каскады проверки «не сменился ли контекст»

Использование
─────────────
    from core.inference_peephole import InferencePeephole
    from drivers.text_driver import TextDriver

    peep = InferencePeephole(system, top_k=6, cascade_threshold=2)
    drv  = TextDriver(system)
    for tok in drv.produce(text):
        snap = peep.step(tok)
        print(peep.render(snap))

    print(peep.summary())
"""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, List, Optional, Tuple

from .algorithm import StepOutcome


# ══════════════════════════════════════════════════════════════════════════════
# Данные
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class DeepContext:
    """Цепочки в базе, которые 'знают' о данном Gen (он входит в их начало)."""
    chain_len: int        # длина верхней цепочки
    label:     str        # её метка
    significance: float   # sig верхней цепочки


@dataclass
class ActiveGenInfo:
    """Снимок одного активного/конкурирующего Gen в контексте."""
    gen_id:    str
    label:     Optional[str]
    chain_len: int          # длина feature_chain (уровень Gen, обычно 1)
    progress:  int          # current_feature_index (сколько признаков уже прошли)
    significance: float     # success / (success + stop)
    success_count: int
    stop_count: int
    is_competing: bool      # True = конкурирует, False = основной (active)
    deep_chains: List[DeepContext] = field(default_factory=list)
    # deep_chains — L2+ Gen в базе, у которых этот Gen — первое звено:
    # показывает что «система знает» о продолжении текущего паттерна

    @property
    def progress_pct(self) -> float:
        return self.progress / self.chain_len if self.chain_len > 0 else 0.0

    @property
    def confidence_bar(self) -> str:
        """▓░-полоска уверенности [0..1] шириной 8 символов."""
        n = round(self.significance * 8)
        return "▓" * n + "░" * (8 - n)


@dataclass
class CycleSnapshot:
    """Полный снимок одного шага инференса."""
    step:         int
    token_label:  str          # человекочитаемая метка токена
    outcome:      StepOutcome

    # ── Контекст ──────────────────────────────────────────────────────────────
    active:     List[ActiveGenInfo]   # топ-K по chain_len↓, sig↓
    max_chain:  int                   # максимальная длина цепочки в контексте
    n_active:   int                   # всего активных Gen
    n_competing: int                  # всего конкурирующих Gen

    # ── Каскадность ───────────────────────────────────────────────────────────
    is_cascade:       bool   # REFUTED на уровне ≥ cascade_threshold
    is_context_shift: bool   # топ-K на max_chain сменился по сравнению с пред. шагом
    cascade_count:    int    # накопленных каскадов за всё время
    cascade_rate:     float  # каскадов на 100 шагов (скользящее окно)
    refuted_streak:   int    # текущая серия последовательных REFUTED

    # ── Что создано / удалено ─────────────────────────────────────────────────
    new_gen_id:      Optional[str]  # создан при REFUTED
    removed_gen_ids: List[str]      # убраны из контекста

    # ── Метрика ───────────────────────────────────────────────────────────────
    elapsed_ms: float


# ══════════════════════════════════════════════════════════════════════════════
# Основной класс
# ══════════════════════════════════════════════════════════════════════════════

class InferencePeephole:
    """
    Параметры
    ─────────
    system             — LearningSystem
    top_k              — сколько Gen показывать в снимке
    cascade_threshold  — минимальная длина цепочки для регистрации каскада
    window             — окно (шагов) для rolling cascade_rate
    """

    def __init__(
        self,
        system,
        top_k: int = 6,
        cascade_threshold: int = 2,
        window: int = 100,
    ) -> None:
        self._sys = system
        self._top_k = top_k
        self._cascade_threshold = cascade_threshold
        self._window = window

        self._step_count = 0
        self._cascade_count = 0
        self._cascade_window: Deque[bool] = deque(maxlen=window)
        self._prev_top_ids: frozenset = frozenset()  # top-K IDs на max_chain
        self._refuted_streak: int = 0

    # ── Основной метод ────────────────────────────────────────────────────────

    def step(self, token) -> CycleSnapshot:
        """Выполнить один токен и вернуть снимок."""
        t0 = time.perf_counter()
        result = self._sys.process_token(token)
        elapsed = (time.perf_counter() - t0) * 1000

        self._step_count += 1
        return self._build_snapshot(token, result, elapsed)

    # ── Запуск на тексте ──────────────────────────────────────────────────────

    def run(
        self,
        driver,
        text: str,
        every_n: int = 1,
        render: bool = True,
        verbose: bool = True,
    ) -> List[CycleSnapshot]:
        """
        Прогнать текст через driver.produce(text), захватить N снимков.

        every_n=1  — каждый токен
        every_n=5  — каждый 5-й токен
        render=True — печатать по мере обработки
        """
        snaps: List[CycleSnapshot] = []
        for tok in driver.produce(text):
            snap = self.step(tok)
            snaps.append(snap)
            if render and (snap.step % every_n == 0):
                print(self.render(snap, verbose=verbose))
        return snaps

    # ── Итоговая статистика ───────────────────────────────────────────────────

    def summary(self) -> str:
        lines = [
            f"  Шагов обработано:  {self._step_count:,}",
            f"  Каскадов всего:    {self._cascade_count}",
            f"  Каскадов / 100ш:   {self._rolling_rate():.1f}",
            f"  Gen в базе:        {self._sys.base.size():,}",
        ]
        return "\n".join(lines)

    # ── Рендер одного снимка ──────────────────────────────────────────────────

    def render(self, snap: CycleSnapshot, verbose: bool = True) -> str:
        W  = "\033[0m";  BD = "\033[1m";  DM = "\033[90m";  IT = "\033[3m"
        GR = "\033[92m"; CY = "\033[96m"; AM = "\033[93m"
        RD = "\033[91m"; MG = "\033[95m"; YL = "\033[33m"

        # ── Заголовок шага ────────────────────────────────────────────────────
        oc = snap.outcome
        oc_color = (GR if oc == StepOutcome.CONFIRMED  else
                    AM if oc == StepOutcome.COMPLETED   else
                    RD if oc == StepOutcome.REFUTED     else
                    CY if oc == StepOutcome.EXPLORING   else DM)
        oc_name = oc.name

        streak_mark = f"  {RD}×{snap.refuted_streak}{W}" if snap.refuted_streak >= 2 else ""
        casc_mark   = f"  {RD}⚡CASCADE{W}" if snap.is_cascade else ""
        shift_mark  = f"  {MG}↺SHIFT{W}"  if snap.is_context_shift else ""

        header = (
            f"{DM}┌─ #{snap.step:>4} ─ «{snap.token_label}»{W}"
            f"  {oc_color}{BD}{oc_name}{W}"
            f"  act={CY}{snap.n_active}{W}"
            f"  cmp={DM}{snap.n_competing}{W}"
            f"  casc={snap.cascade_count}({snap.cascade_rate:.0f}/100)"
            f"{streak_mark}{casc_mark}{shift_mark}"
        )

        if not verbose or not snap.active:
            return header

        lines = [header]

        # ── Топ Gen ───────────────────────────────────────────────────────────
        for gi in snap.active:
            role_col = CY if not gi.is_competing else DM
            label    = gi.label or "(unlabelled)"
            sig_col  = GR if gi.significance >= 0.7 else (AM if gi.significance >= 0.4 else RD)

            # прогресс-бар цепочки: ◉ = пройден, ◎ = текущий, ○ = впереди
            chain_bar = ""
            for i in range(gi.chain_len):
                if i < gi.progress:
                    chain_bar += "◉"
                elif i == gi.progress:
                    chain_bar += "◎"
                else:
                    chain_bar += "○"

            role_sym = "●" if not gi.is_competing else "◌"
            lines.append(
                f"  {role_col}{role_sym}{W} "
                f"{role_col}{label:<20}{W}"
                f"  L{gi.chain_len}"
                f"  [{chain_bar}]"
                f"  sig={sig_col}{gi.significance:.3f}{W} {gi.confidence_bar}"
                f"  s={gi.success_count} f={gi.stop_count}"
            )
            # Показать контекст из более глубоких цепочек (L2+ в памяти)
            if gi.deep_chains and not gi.is_competing:
                dc_parts = []
                for dc in gi.deep_chains:
                    dc_sig = GR if dc.significance >= 0.7 else AM
                    short_lbl = dc.label[:16] if len(dc.label) > 16 else dc.label
                    dc_parts.append(
                        f"L{dc.chain_len}:{short_lbl}({dc_sig}{dc.significance:.2f}{W})"
                    )
                lines.append(f"    {DM}└ знает: {', '.join(dc_parts)}{W}")

        # ── Что произошло с Gen ───────────────────────────────────────────────
        if snap.new_gen_id:
            ng = self._sys.base.get(snap.new_gen_id)
            nl = ng.label if ng else "?"
            lines.append(f"  {YL}+ NEW Gen '{nl}'  id={snap.new_gen_id[:8]}…{W}")

        if snap.removed_gen_ids and verbose:
            for rid in snap.removed_gen_ids[:3]:
                rg = self._sys.base.get(rid)
                rl = rg.label if rg else "?"
                lines.append(f"  {RD}✗ removed '{rl}'  id={rid[:8]}…{W}")

        lines.append(f"  {DM}└─ {snap.elapsed_ms:.1f}ms{W}")
        return "\n".join(lines)

    # ══════════════════════════════════════════════════════════════════════════
    # Внутренние методы
    # ══════════════════════════════════════════════════════════════════════════

    def _build_snapshot(self, token, result, elapsed_ms: float) -> CycleSnapshot:
        ctx  = self._sys.engine.context
        base = self._sys.base

        # ── Собрать ActiveGenInfo для всех active + competing ─────────────────
        infos: List[ActiveGenInfo] = []

        for gen_id, ag in list(ctx._active.items()):
            g = base.get(gen_id)
            if g is None:
                continue
            infos.append(ActiveGenInfo(
                gen_id       = gen_id,
                label        = g.label,
                chain_len    = len(g.feature_chain),
                progress     = ag.current_feature_index,
                significance = g.significance,
                success_count= g.success_count,
                stop_count   = g.stop_count,
                is_competing = False,
                deep_chains  = self._get_deep_chains(g, base),
            ))

        for gen_id, ag in list(ctx._competing.items()):
            g = base.get(gen_id)
            if g is None:
                continue
            infos.append(ActiveGenInfo(
                gen_id       = gen_id,
                label        = g.label,
                chain_len    = len(g.feature_chain),
                progress     = ag.current_feature_index,
                significance = g.significance,
                success_count= g.success_count,
                stop_count   = g.stop_count,
                is_competing = True,
                deep_chains  = [],
            ))

        # Сортировка: сначала основные, потом конкурирующие;
        # внутри — по chain_len↓, significance↓
        infos.sort(key=lambda x: (x.is_competing, -x.chain_len, -x.significance))
        top = infos[: self._top_k]

        # ── Метрики контекста ─────────────────────────────────────────────────
        max_chain = max((x.chain_len for x in infos), default=0)
        n_active  = len(ctx._active)
        n_comp    = len(ctx._competing)

        # ── Серия REFUTED и каскад ────────────────────────────────────────────
        if result.outcome == StepOutcome.REFUTED:
            self._refuted_streak += 1
        else:
            self._refuted_streak = 0

        prev_max = max((x.chain_len for x in infos
                        if x.gen_id in (result.removed_gen_ids or [])),
                       default=0)
        # Каскад = REFUTED при chain≥threshold ИЛИ серия ≥ 2 последовательных REFUTED
        is_cascade = (
            result.outcome == StepOutcome.REFUTED
            and (prev_max >= self._cascade_threshold or self._refuted_streak >= 2)
        )
        if is_cascade:
            self._cascade_count += 1
        self._cascade_window.append(is_cascade)

        # ── Смена контекста на верхнем уровне? ───────────────────────────────
        cur_top_ids = frozenset(
            x.gen_id for x in infos
            if not x.is_competing and x.chain_len == max_chain
        )
        is_shift = bool(self._prev_top_ids and cur_top_ids != self._prev_top_ids)
        if cur_top_ids:
            self._prev_top_ids = cur_top_ids

        # ── Метка токена ──────────────────────────────────────────────────────
        token_label = getattr(token, "label", None) or str(getattr(token, "data", token))

        return CycleSnapshot(
            step          = self._step_count,
            token_label   = token_label,
            outcome       = result.outcome,
            active        = top,
            max_chain     = max_chain,
            n_active      = n_active,
            n_competing   = n_comp,
            is_cascade    = is_cascade,
            is_context_shift = is_shift,
            cascade_count = self._cascade_count,
            cascade_rate  = self._rolling_rate(),
            refuted_streak = self._refuted_streak,
            new_gen_id    = result.new_gen_id,
            removed_gen_ids = list(result.removed_gen_ids or []),
            elapsed_ms    = elapsed_ms,
        )

    def _get_deep_chains(self, gen, base, top_n: int = 3) -> List[DeepContext]:
        """
        Найти в базе L2+ Gen, чьи метки НАЧИНАЮТСЯ с метки данного Gen.
        Показывает что «система знает» о продолжении текущего паттерна.
        """
        if not gen.label:
            return []
        prefix = gen.label.lower()
        result_list: List[DeepContext] = []
        try:
            # search_by_label_prefix если есть, иначе ручной перебор
            # ищем Gen с label начинающимся на нашу метку (bigram pattern)
            for gid in list(base._gens.keys()):
                cand = base.get(gid)
                if cand is None:
                    continue
                clen = len(cand.feature_chain)
                if clen < 2:
                    continue
                clabel = (cand.label or "").lower()
                # label L2+ выглядит как "word1·word2·..." — ищем начало
                first_word = clabel.split("·")[0] if "·" in clabel else clabel
                if first_word == prefix:
                    result_list.append(DeepContext(
                        chain_len    = clen,
                        label        = cand.label or gid[:8],
                        significance = cand.significance,
                    ))
        except Exception:
            return []
        result_list.sort(key=lambda x: (-x.chain_len, -x.significance))
        return result_list[:top_n]

    def _rolling_rate(self) -> float:
        """Каскадов на 100 шагов (по скользящему окну)."""
        if not self._cascade_window:
            return 0.0
        return sum(self._cascade_window) / len(self._cascade_window) * 100
