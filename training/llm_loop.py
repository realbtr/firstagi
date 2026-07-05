"""
Шаг 8: BrokerLoop — цикл непрерывного обучения через LLM-брокер.

Поток управления одного шага (step()):
  1. pop_content() из TeachingLog → если есть → app.learn(text)
     (контент был подготовлен LLM на предыдущем tick)
  2. scheduler.tick() → вызывает LLMTeacherWorker.observe() + suggest_content()
     → LLM решает TEACH/REWARD/WAIT, результаты пушатся в TeachingLog

Таким образом LLM-контент текущего тика обрабатывается на следующем шаге —
нет гонок, нет рекурсии.
"""

from __future__ import annotations

import sys
import os

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from core.app import CoreApplication
    from core.llm_broker import LLMTeacherWorker


class BrokerLoop:
    """
    Цикл обучения через LLM-брокер.

    Использование:
        app = CoreApplication()
        app.startup()
        worker = LLMTeacherWorker(app.system, MockLLMClient(...))
        app.scheduler.add_worker(worker, name="llm")

        loop = BrokerLoop(app, worker)
        reports = loop.run(n_steps=100, verbose=True)
    """

    def __init__(
        self,
        app: "CoreApplication",
        worker: "LLMTeacherWorker",
    ) -> None:
        self.app = app
        self.worker = worker
        self._step_count: int = 0
        self._content_fed_count: int = 0
        self._orders_fired_total: int = 0
        self._reports: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------

    def step(self) -> Dict[str, Any]:
        """
        Один шаг брокер-цикла.

        Возвращает словарь:
            step          — номер шага
            content_fed   — текст, поданный в систему (или None)
            learn_result  — результат app.learn() (или None)
            orders_fired  — число ордеров/контента от tick()
            resource      — текущий уровень ресурса
            llm_calls     — общее число LLM-вызовов воркера
        """
        # 1. Взять контент из очереди (если LLM что-то предложил на прошлом тике)
        content = self.app.system.teaching_log.pop_content()
        learn_result = None
        if content:
            learn_result = self.app.learn(str(content), reset_after=True)
            self._content_fed_count += 1

        # 2. Тик планировщика — вызывает LLM (если готов) и пушит результаты
        orders_fired = self.app.scheduler.tick()
        self._orders_fired_total += orders_fired

        self._step_count += 1
        report: Dict[str, Any] = {
            "step":         self._step_count,
            "content_fed":  content,
            "learn_result": learn_result,
            "orders_fired": orders_fired,
            "resource":     self.app.system.resource.level,
            "llm_calls":    self.worker.call_count,
        }
        self._reports.append(report)
        return report

    def run(
        self,
        n_steps: int = 100,
        verbose: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Запустить n_steps шагов цикла.

        Возвращает список отчётов (по одному на шаг).
        """
        reports = []
        for _ in range(n_steps):
            report = self.step()
            reports.append(report)
            if verbose:
                self._print_step(report)
        return reports

    def run_interactive(self, verbose: bool = True) -> None:
        """
        Непрерывный цикл до Ctrl+C.
        """
        print("[BrokerLoop] Запуск интерактивного режима. Ctrl+C для остановки.")
        try:
            while True:
                report = self.step()
                if verbose:
                    self._print_step(report)
        except KeyboardInterrupt:
            print("\n[BrokerLoop] Остановлен пользователем.")
            self._print_summary()

    # ------------------------------------------------------------------

    def _print_step(self, report: Dict[str, Any]) -> None:
        content_str = ""
        if report["content_fed"]:
            snippet = str(report["content_fed"])[:40]
            content_str = f'  → "{snippet}"'
            if report["learn_result"]:
                lr = report["learn_result"]
                outcomes = lr.get("outcomes", [])
                comp = outcomes.count("COMPLETED")
                conf = outcomes.count("CONFIRMED")
                ref  = outcomes.count("REFUTED")
                content_str += f" [C:{comp} V:{conf} R:{ref}]"
        orders_str = (
            f"  ✓{report['orders_fired']}" if report["orders_fired"] > 0 else ""
        )
        print(
            f"step={report['step']:4d}  "
            f"res={report['resource']:.3f}  "
            f"llm={report['llm_calls']}{orders_str}{content_str}"
        )

    def _print_summary(self) -> None:
        stats = self.stats()
        print(
            f"\n[Итог] steps={stats['total_steps']}  "
            f"content={stats['content_fed_count']}  "
            f"orders={stats['orders_fired_total']}  "
            f"llm_calls={stats['llm_calls']}"
        )

    def stats(self) -> Dict[str, Any]:
        """Агрегированная статистика цикла."""
        return {
            "total_steps":       self._step_count,
            "content_fed_count": self._content_fed_count,
            "orders_fired_total": self._orders_fired_total,
            "llm_calls":         self.worker.call_count,
            "final_resource":    self.app.system.resource.level,
            "worker_stats":      self.worker.stats(),
            "system_stats":      self.app.system.stats(),
        }
