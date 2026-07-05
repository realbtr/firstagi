"""
Шаг 10: DebugSession — единый интерфейс для отладки и управления обучением.

Объединяет Inspector, PredictiveSimulator, DriverController и CurriculumAgent
в один объект, который можно использовать как программно (из агента Claude),
так и через CLI или Jupyter notebook.

Принцип работы:
  • inspect()           — snapshot состояния без мутации
  • predict(text)       — dry-run: что произошло бы (без обучения)
  • learn(text)         — реальное обучение
  • weak() / top()      — просмотр обобщений
  • step_curriculum()   — один шаг автоматизированного обучения
  • set_stability(s)    — ручная установка уровня стабильности
  • inject(feature_id)  — синтетический токен напрямую в движок

Использование:
    from core.app import CoreApplication
    from curriculum.debug_session import DebugSession

    app = CoreApplication()
    app.startup()

    session = DebugSession(app, corpus=["кот сидит", "кот спит", ...])
    print(session.inspect())
    print(session.predict("кот бежит"))
    step = session.step_curriculum()
    print(step)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, TYPE_CHECKING

from core.inspector import GeneralizationInspector, PredictiveSimulator
from core.driver_control import DriverController
from core.attention_loop import AttentionLoop, AttentionStep
from core.learning import HierarchicalConsolidator, HierarchicalConsolidationReport
from core.vitality import WakeUpRestorer
from curriculum.agent import CurriculumAgent, CurriculumStep, StabilitySchedule
from drivers.memory_driver import MemoryDriver

if TYPE_CHECKING:
    from core.app import CoreApplication


class DebugSession:
    """
    Унифицированный отладочный интерфейс.

    Агент (Claude или другой LLM) может вызывать методы этого объекта
    для наблюдения и управления процессом обучения без знания
    внутренней архитектуры системы.
    """

    def __init__(
        self,
        app:      "CoreApplication",
        corpus:   Optional[List[str]] = None,
        schedule: Optional[StabilitySchedule] = None,
    ) -> None:
        self.app        = app
        self.inspector   = GeneralizationInspector(app.system)
        self.simulator   = PredictiveSimulator(
            app.system,
            text_driver=app.peripherals.get("text"),
        )
        self.controller  = DriverController(app)

        # Драйвер долговременной памяти: регистрируем при низком приоритете
        self.memory = MemoryDriver(
            driver_id        = "memory",
            max_entries      = 2000,
            replay_per_cycle = 100,
        )
        if "memory" not in app.peripherals._drivers:
            app.peripherals.register(self.memory, priority=1)

        self.attn_loop   = AttentionLoop(app.system, app.peripherals, memory=self.memory)
        self.curriculum  = CurriculumAgent(
            inspector  = self.inspector,
            controller = self.controller,
            app        = app,
            corpus     = corpus or [],
            schedule   = schedule,
        )
        self._log: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Наблюдение

    def inspect(self) -> Dict[str, Any]:
        """Полный snapshot состояния: stats, top/weak gens, proposals, attention."""
        snap = self.inspector.snapshot()
        snap["attention"] = self.controller.get_attention_map()
        return snap

    def predict(self, text: str) -> Dict[str, Any]:
        """Dry-run: что произошло бы при обучении text (без мутации)."""
        result = self.simulator.simulate(text)
        return {
            "text":         text,
            "outcomes":     result.outcomes,
            "match_rate":   result.match_rate,
            "confirmed":    result.confirmed_features,
            "refuted":      result.refuted_count,
            "would_create": result.would_create_gens,
        }

    def top(self, n: int = 10) -> List[Dict[str, Any]]:
        """Топ-N обобщений по значимости."""
        return self.inspector.top_gens(n)

    def weak(self, n: int = 20) -> List[Dict[str, Any]]:
        """Слабоподтверждённые обобщения — точки роста."""
        return self.inspector.weak_gens()[:n]

    def attention(self) -> Dict[str, Any]:
        """Карта внимания: куда «смотрит» система прямо сейчас."""
        return self.controller.get_attention_map()

    def readiness(self) -> float:
        """Готовность системы к усложнению [0..1]."""
        return self.inspector.readiness()

    # ------------------------------------------------------------------
    # Обучение

    def learn(self, text: str, driver_id: str = "text") -> Dict[str, Any]:
        """Обучить систему одной единицей текста."""
        result = self.app.learn(text, driver_id=driver_id)
        self._log.append({"action": "learn", "text": text, "result": result})
        return result

    # ------------------------------------------------------------------
    # Управление вниманием

    def set_driver_priority(self, driver_id: str, priority: int) -> None:
        """Изменить приоритет зарегистрированного драйвера."""
        self.controller.set_driver_priority(driver_id, priority)

    def get_driver_priorities(self) -> Dict[str, int]:
        """Текущие приоритеты всех драйверов."""
        return self.controller.get_driver_priorities()

    def set_tolerance(self, value: Optional[float]) -> None:
        """Переопределить tolerance (None = вернуть нейромодуляции)."""
        self.controller.set_tolerance_override(value)

    def inject(self, feature_id: str) -> Optional[Dict[str, Any]]:
        """Инжектировать синтетический признак напрямую в движок."""
        result = self.controller.inject_feature(feature_id)
        if result is None:
            return None
        return {
            "outcome": result.outcome.name,
            "feature": result.matched_feature_id,
        }

    def known_features(self) -> List[str]:
        """Список известных feature_id в реестре движка."""
        return self.controller.known_features()

    # ------------------------------------------------------------------
    # Curriculum

    def set_stability(self, value: float) -> None:
        """Вручную установить уровень стабильности [0..1]."""
        self.curriculum.stability = max(0.0, min(1.0, value))

    def step_curriculum(self) -> Dict[str, Any]:
        """Один шаг CurriculumAgent."""
        step = self.curriculum.step()
        self._log.append({"action": "curriculum_step", "step": step})
        return self._step_to_dict(step)

    def run_curriculum(self, n_steps: int) -> List[Dict[str, Any]]:
        """Запустить n_steps шагов CurriculumAgent подряд."""
        steps = self.curriculum.run(n_steps)
        for s in steps:
            self._log.append({"action": "curriculum_step", "step": s})
        return [self._step_to_dict(s) for s in steps]

    def curriculum_stats(self) -> Dict[str, Any]:
        """Сводная статистика CurriculumAgent."""
        return self.curriculum.stats()

    def add_to_corpus(self, texts: List[str]) -> None:
        """Добавить тексты в корпус агента."""
        self.curriculum.corpus.extend(texts)

    # ------------------------------------------------------------------
    # Шаг 11: активное внимание

    def load_buffer(self, text: str, driver_id: str = "text") -> int:
        """Загрузить текст в буфер драйвера для активного внимания."""
        return self.attn_loop.load_buffer(text, driver_id)

    def buffer_sizes(self) -> Dict[str, int]:
        """Текущие размеры буферов всех драйверов."""
        return self.attn_loop.buffer_sizes()

    def step_attention(self) -> Dict[str, Any]:
        """Один шаг активного внимания (модель запрашивает периферию)."""
        step = self.attn_loop.step()
        self._log.append({"action": "attention_step", "step": step})
        return self._attn_step_to_dict(step)

    def run_attention(self, n_steps: int) -> List[Dict[str, Any]]:
        """Запустить n шагов активного внимания подряд."""
        steps = self.attn_loop.run(n_steps)
        for s in steps:
            self._log.append({"action": "attention_step", "step": s})
        return [self._attn_step_to_dict(s) for s in steps]

    def run_attention_until_empty(self, max_steps: int = 1000) -> List[Dict[str, Any]]:
        """Запускать активное внимание, пока буферы не опустеют."""
        steps = self.attn_loop.run_until_empty(max_steps)
        for s in steps:
            self._log.append({"action": "attention_step", "step": s})
        return [self._attn_step_to_dict(s) for s in steps]

    def run_attention_sentences(
        self,
        texts: List[str],
        driver_id: str = "text",
    ) -> List[List[Dict[str, Any]]]:
        """
        Обработать каждый текст как самостоятельное предложение.

        Сбрасывает контекст перед каждым текстом — система «переводит взгляд».
        Возвращает список списков шагов (один подсписок на текст).
        """
        all_results = self.attn_loop.run_sentences(texts, driver_id)
        for sentence_steps in all_results:
            for s in sentence_steps:
                self._log.append({"action": "attention_step", "step": s})
        return [
            [self._attn_step_to_dict(s) for s in steps]
            for steps in all_results
        ]

    def reset_context(self) -> None:
        """Сбросить контекст системы (граница предложения / сессии)."""
        self.app.system.reset_context()

    # ------------------------------------------------------------------
    # Шаг 13б: консолидация через долговременную память

    def consolidate(
        self,
        n_steps:          int   = 100,
        tolerance_factor: float = 0.6,
    ) -> Dict[str, Any]:
        """
        Запустить цикл консолидации памяти.

        Система реплицирует прошлый опыт с повышенным разрешением
        (tolerance_factor < 1.0 — более тонкая сетка признаков).
        Слабые Gen получают приоритет воспроизведения.

        Возвращает статистику: сколько шагов, сколько CONFIRMED/REFUTED,
        состояние памяти до и после.
        """
        mem_before = self.memory.stats()

        # Сохранить текущую tolerance и ресурс перед консолидацией
        base_tol      = self.app.system.engine.feature_tolerance
        base_resource = self.app.system.resource.state.level

        # Повысить разрешение на время консолидации
        self.app.system.engine.feature_tolerance = base_tol * tolerance_factor
        self.controller._tolerance_override = base_tol * tolerance_factor
        try:
            steps = self.attn_loop.run_consolidation(n_steps)
        finally:
            # Восстановить точную tolerance (не через нейромодуляцию — она сбилась)
            # и уровень ресурса (консолидация = внутренний процесс, не обучение)
            self.app.system.engine.feature_tolerance = base_tol
            self.controller._tolerance_override = None
            self.app.system.resource.set_level(base_resource)

        for s in steps:
            self._log.append({"action": "consolidation_step", "step": s})

        outcomes = [s.outcome for s in steps if s.outcome != "IDLE"]
        confirmed = outcomes.count("CONFIRMED") + outcomes.count("COMPLETED")
        return {
            "steps":      len(steps),
            "confirmed":  confirmed,
            "refuted":    outcomes.count("REFUTED"),
            "match_rate": round(confirmed / max(len(outcomes), 1), 4),
            "memory_before": mem_before,
            "memory_after":  self.memory.stats(),
        }

    def memory_stats(self) -> Dict[str, Any]:
        """Статистика долговременной памяти."""
        return self.memory.stats()

    def consolidate_hierarchy(self, passes: int = 3) -> Dict[str, Any]:
        """
        Иерархическая консолидация: факторизовать развилки в мета-Gen.

        Находит все пары Gen с одинаковым префиксом (развилки) и создаёт
        или усиливает мета-Gen для этого общего префикса. Значимость
        течёт вверх по гетерархии: мета-Gen подтверждается при подтверждении
        любого из потомков, что позволяет строить абстрактный нарратив.

        Вызывается ПОСЛЕ consolidate() — после того как replay-цикл
        зафиксировал паттерны в памяти, hier-консолидация факторизует их.
        """
        hc = HierarchicalConsolidator(self.app.system.base)
        rep = hc.consolidate(passes=passes)
        self._log.append({"action": "hier_consolidation", "report": rep})
        return {
            "forks_found":      rep.forks_found,
            "meta_created":     rep.meta_created,
            "meta_strengthened": rep.meta_strengthened,
            "total_gen":        self.app.system.base.size(),
            "new_gen_ids":      rep.new_gen_ids[:10],  # топ-10 для отображения
        }

    def hierarchy_stats(self) -> Dict[str, Any]:
        """Статистика иерархической структуры гетерархии."""
        hc = HierarchicalConsolidator(self.app.system.base)
        return hc.stats()

    def focus_weak(self, n: int = 5) -> int:
        """
        Сосредоточить следующий цикл консолидации на n слабейших Gen.

        Устанавливает replay_count=0 для всех записей,
        связанных с Gen из топ-n по слабости.
        Возвращает количество «разбуженных» записей.
        """
        weak = self.inspector.weak_gens(max_significance=0.5)[:n]
        total = 0
        for g in weak:
            total += self.memory.focus_gen(g["full_id"])
        return total

    def attention_stats(self) -> Dict[str, Any]:
        """Статистика петли активного внимания."""
        return self.attn_loop.stats()

    # ------------------------------------------------------------------
    # Витальность

    def vitality_step(
        self,
        threshold: float = 2.0,
        auto_restore: bool = True,
    ) -> Dict[str, Any]:
        """
        Один цикл жизненности: проверить, «стучится» ли кто-то из активных Gen.

        1. Взять активные Gen из контекста.
        2. Найти knock_candidates (urgency >= threshold).
        3. При auto_restore — загрузить якорный Gen для самого тревожного.

        Возвращает:
            active_count  — Gen в контексте до шага
            knock_count   — Gen с urgency >= threshold
            knock_ids     — их gen_id (первые 8 символов)
            restored      — gen_id загруженного якоря или None
            step          — текущий step_count движка
        """
        sys = self.app.system
        active = sys.engine.context.active_gen_ids()
        step   = sys.engine.step_count
        knock  = sys.vitality.knock_candidates(active, sys.base, step, threshold)

        restored = None
        if auto_restore and knock:
            most_urgent_gid, _ = knock[0]
            gap = sys.vitality.gap_for(most_urgent_gid, step)
            restored = sys.restorer.restore(sys.base, sys.engine.context, gap)

        self._log.append({
            "action":       "vitality_step",
            "knock_count":  len(knock),
            "restored":     restored,
        })
        return {
            "active_count": len(active),
            "knock_count":  len(knock),
            "knock_ids":    [gid[:8] for gid, _ in knock],
            "restored":     restored[:8] if restored else None,
            "step":         step,
        }

    def wake_up(self, step_gap: int = 30) -> Optional[str]:
        """
        Принудительно восстановить якорный Gen для заданного step_gap.

        Обходит проверку urgency — полезно для явного «пробуждения»
        системы после внешней паузы.

        Возвращает gen_id (первые 8 символов) или None.
        """
        sys = self.app.system
        restored = sys.restorer.restore(sys.base, sys.engine.context, step_gap)
        self._log.append({
            "action":   "wake_up",
            "step_gap": step_gap,
            "restored": restored,
        })
        return restored[:8] if restored else None

    def vitality_report(
        self,
        n: int = 20,
        threshold: float = 2.0,
    ) -> Dict[str, Any]:
        """
        Полный отчёт о витальности топ-N Gen.

        Возвращает:
            step           — текущий step_count
            tracked        — сколько VitalityRecord существует
            at_risk        — Gen с urgency >= threshold
            records        — List[dict] из VitalityEngine.report()
            vitality_stats — агрегатная статистика
        """
        sys     = self.app.system
        step    = sys.engine.step_count
        top_ids = [g.gen_id for g in sys.base.rank()[:n]]
        records = sys.vitality.report(top_ids, sys.base, step)
        at_risk = sum(1 for r in records if r["urgency"] >= threshold)
        return {
            "step":           step,
            "tracked":        len(sys.vitality._records),
            "at_risk":        at_risk,
            "records":        records,
            "vitality_stats": sys.vitality.stats(),
        }

    # ------------------------------------------------------------------
    # История

    @property
    def log(self) -> List[Dict[str, Any]]:
        """Лог всех действий сессии."""
        return list(self._log)

    def log_summary(self) -> Dict[str, Any]:
        """Краткая статистика лога."""
        learns         = [e for e in self._log if e["action"] == "learn"]
        currsteps      = [e for e in self._log if e["action"] == "curriculum_step"]
        vitality_steps = [e for e in self._log if e["action"] == "vitality_step"]
        return {
            "total_actions":     len(self._log),
            "learn_calls":       len(learns),
            "curriculum_steps":  len(currsteps),
            "vitality_steps":    len(vitality_steps),
            "corpus_size":       len(self.curriculum.corpus),
            "current_stability": round(self.curriculum.stability, 4),
        }

    # ------------------------------------------------------------------

    @staticmethod
    def _attn_step_to_dict(step: AttentionStep) -> Dict[str, Any]:
        return {
            "step_n":              step.step_n,
            "outcome":             step.outcome,
            "driver_queried":      step.driver_queried,
            "proposal_feature_id": step.proposal_feature_id,
            "new_gens":            step.new_gens,
            "buffer_sizes":        step.buffer_sizes,
            "match_rate":          step.match_rate,
            "candidates":          step.candidates,
        }

    @staticmethod
    def _step_to_dict(step: CurriculumStep) -> Dict[str, Any]:
        return {
            "step_n":         step.step_n,
            "stability":      step.stability,
            "readiness":      step.readiness,
            "texts_fed":      step.texts_fed,
            "match_rates":    step.match_rates,
            "avg_match_rate": round(step.avg_match_rate, 4),
            "new_stability":  step.new_stability,
            "total_gens":     step.total_gens,
            "new_gens":       step.new_gens_this_step,
        }

    def __repr__(self) -> str:
        return (
            f"DebugSession("
            f"gens={self.app.system.base.size()}, "
            f"stability={self.curriculum.stability:.2f}, "
            f"corpus={len(self.curriculum.corpus)})"
        )
