"""
training/live_session.py — Живая сессия: модель учится в фоне, ты наблюдаешь.

Запуск:
  py -X utf8 training/live_session.py
  py -X utf8 training/live_session.py --port 8073 --cycle 8 --llm-interval 45
  py -X utf8 training/live_session.py --api-key sk-ant-...

Что делает скрипт
─────────────────
• Создаёт Gen-систему и корпус текстов
• Запускает FastAPI сервер на --port (default 8073) в фоновом потоке
  → http://localhost:8073/docs для REST API
  → http://localhost:8073/activity  для лога событий
• Запускает медленный обучающий цикл (пауза --cycle секунд между шагами)
• LLM-вызовы ограничены: не чаще чем 1 раз в --llm-interval секунд,
  и не более --daily-limit вызовов в сутки
• В основном потоке — интерактивный rich-терминал:
    > любой текст         — скормить модели как обучающий материал
    > /ask вопрос         — задать вопрос через гетерархию (LLM-учитель ответит)
    > /status             — подробный снапшот состояния
    > /top N              — топ-N Gen по значимости
    > /corpus             — список документов в корпусе
    > /add <doc> текст... — добавить документ в корпус на лету
    > /voices N           — вопросы модели в голосах персонажей (N = кол-во)
    > /reflect            — рефлексия: статистика качества формулировок
    > /pause              — приостановить фоновый цикл
    > /resume             — возобновить фоновый цикл
    > /quit               — выход

Ключевые параметры
──────────────────
  --port         порт сервера         (default: 8073)
  --cycle        пауза между циклами  (default: 8 сек)
  --llm-interval мин. интервал LLM    (default: 45 сек)
  --daily-limit  макс. LLM в сутки    (default: 20)
  --api-key      Anthropic API key    (или ANTHROPIC_API_KEY)
  --no-llm       отключить LLM-узел   (работает на mock)
  --verbose      подробные логи
"""
from __future__ import annotations

import argparse
import os
import sys
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Deque, Dict, List, Optional

# Rich
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box

console = Console(highlight=False)


# ══════════════════════════════════════════════════════════════════════════════
# Корпус
# ══════════════════════════════════════════════════════════════════════════════

CORPUS = {
    "children_1": {
        "domain": "children",
        "title":  "Маша и медведь",
        "text":   (
            "Маша пошла в лес за грибами.\n"
            "В лесу Маша встретила медведя.\n"
            "Медведь принёс Маше пирог с грибами.\n"
            "Маша обрадовалась и угостила медведя.\n"
            "Медведь и Маша стали друзьями."
        ),
    },
    "children_2": {
        "domain": "children",
        "title":  "Заяц и морковка",
        "text":   (
            "Заяц нашёл большую морковку в огороде.\n"
            "Заяц принёс морковку маме.\n"
            "Мама обрадовалась и сварила суп.\n"
            "Заяц и мама съели суп вместе.\n"
            "Это был вкусный суп из морковки."
        ),
    },
    "children_3": {
        "domain": "children",
        "title":  "Кот и мышка",
        "text":   (
            "Кот жил в большом доме.\n"
            "Кот мяукает когда хочет есть.\n"
            "Мышка принесла коту сыр.\n"
            "Кот обрадовался и не стал ловить мышку.\n"
            "Кот и мышка подружились."
        ),
    },
    "astronomy_1": {
        "domain": "astronomy",
        "title":  "Звёзды",
        "text":   (
            "Звёзды светят в ночном небе.\n"
            "Каждая звезда имеет свою орбиту.\n"
            "Телескоп позволяет увидеть далёкие звёзды.\n"
            "Астрономы изучают движение звёзд и планет.\n"
            "Планеты вращаются вокруг звезды."
        ),
    },
    "cooking_1": {
        "domain": "cooking",
        "title":  "Рецепт пирога",
        "text":   (
            "Пирог готовят из муки и яиц.\n"
            "Нужно добавить сахар и масло.\n"
            "Тесто раскатывают и кладут начинку.\n"
            "Пирог пекут в духовке час.\n"
            "Готовый пирог украшают кремом."
        ),
    },
}


# ══════════════════════════════════════════════════════════════════════════════
# Activity Log — кольцевой буфер событий для TUI и /activity API
# ══════════════════════════════════════════════════════════════════════════════

class ActivityLog:
    """Потокобезопасный кольцевой буфер событий."""

    ICONS = {
        "search_hit":    "🔍",
        "search_miss":   "❌",
        "probe_abort":   "⛔",
        "cold_start":    "🌱",
        "loop_paused":   "⏸",
        "loop_resumed":  "▶",
        "llm_ask":       "🤖",
        "llm_answer":    "💬",
        "llm_skip":      "⏳",
        "user_feed":     "👤",
        "user_ask":      "❓",
        "gen_update":    "📈",
        "error":         "⚠",
    }

    COLORS = {
        "search_hit":    "green",
        "search_miss":   "red",
        "probe_abort":   "yellow",
        "cold_start":    "cyan",
        "loop_paused":   "dim",
        "loop_resumed":  "cyan",
        "llm_ask":       "magenta",
        "llm_answer":    "blue",
        "llm_skip":      "dim",
        "user_feed":     "bright_white",
        "user_ask":      "bright_yellow",
        "gen_update":    "green",
        "error":         "red",
    }

    def __init__(self, maxlen: int = 200) -> None:
        self._events: Deque[Dict] = deque(maxlen=maxlen)
        self._lock = threading.Lock()

    def add(self, kind: str, msg: str, data: Optional[Dict] = None) -> None:
        with self._lock:
            self._events.append({
                "ts":   datetime.now().strftime("%H:%M:%S"),
                "kind": kind,
                "msg":  msg,
                "data": data or {},
            })

    def recent(self, n: int = 20) -> List[Dict]:
        with self._lock:
            events = list(self._events)
        return events[-n:]

    def format_rich(self, n: int = 15) -> str:
        lines = []
        for ev in self.recent(n):
            icon  = self.ICONS.get(ev["kind"], "•")
            color = self.COLORS.get(ev["kind"], "white")
            lines.append(
                f"[dim]{ev['ts']}[/dim] {icon} [{color}]{ev['msg']}[/{color}]"
            )
        return "\n".join(lines) if lines else "[dim]Ожидание первых событий...[/dim]"

    def to_list(self) -> List[Dict]:
        return self.recent(50)


# ══════════════════════════════════════════════════════════════════════════════
# Rate Limiter для LLM вызовов
# ══════════════════════════════════════════════════════════════════════════════

class RateLimiter:
    """Гарантирует минимальный интервал между LLM-вызовами."""

    def __init__(self, min_interval: float = 45.0) -> None:
        self._min_interval = min_interval
        self._last_call    = 0.0
        self._lock         = threading.Lock()

    def can_call(self) -> bool:
        with self._lock:
            return (time.time() - self._last_call) >= self._min_interval

    def seconds_until_next(self) -> float:
        with self._lock:
            elapsed = time.time() - self._last_call
            return max(0.0, self._min_interval - elapsed)

    def consume(self) -> None:
        with self._lock:
            self._last_call = time.time()


# ══════════════════════════════════════════════════════════════════════════════
# Глобальное состояние сессии
# ══════════════════════════════════════════════════════════════════════════════

class SessionState:
    """Всё живёт здесь — один объект, передаётся в API и в TUI."""

    def __init__(self, args: argparse.Namespace) -> None:
        from core.learning import LearningSystem
        from core.capacity import CapacityBudget
        from core.budget import QuestionBudget
        from drivers.text_driver import TextDriver
        from app.text_server import ActiveTextServer
        from core.exploration import ExplorationPolicy
        from core.domain_detector import DomainDetector
        from core.heterarchy import HeterarchyRouter, ModelNode
        from core.llm_node import LLMTeachNode

        self.args = args

        # Gen-система
        self.system = LearningSystem(
            capacity_budget=CapacityBudget(max_gens=20_000),
        )
        # Ограничить жадный обобщитель: не строить Gen длиннее предложения
        self.system.generalizer.max_chain = 6
        self.driver = TextDriver(self.system)
        # Мьютекс для /talk — приостанавливает фоновый цикл на время разговора
        self._talk_lock = threading.Lock()

        # Корпус-сервер
        self.server = ActiveTextServer(
            exploration_policy=ExplorationPolicy(revisit_penalty=0.4),
            use_probe_chain=True,
        )
        for doc_id, info in CORPUS.items():
            self.server.add_document(
                doc_id, info["text"],
                domain=info["domain"], title=info["title"],
            )

        # Детектор доменов
        self.domain_detector = DomainDetector()
        self.domain_detector.build_from_corpus(CORPUS)

        # Гетерархия
        self.router   = HeterarchyRouter()
        self.rate_lim = RateLimiter(min_interval=args.llm_interval)
        self.budget   = QuestionBudget(daily_limit=args.daily_limit)

        # Gen-узел новичка (сама модель)
        self.novice_node = ModelNode(
            "session_model", self.system,
            domains={"children", "astronomy", "cooking"},
            experience=0,
        )
        self.novice_node.set_domain_detector(self.domain_detector)

        # LLM-учитель
        api_key = args.api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        if api_key and not args.no_llm:
            try:
                self.llm_node = LLMTeachNode.from_api_key(
                    api_key   = api_key,
                    node_id   = "claude_teacher",
                    domains   = {"children", "astronomy", "cooking"},
                    experience = 5,
                    verbose   = args.verbose,
                )
                self._llm_real = True
            except Exception as e:
                console.print(f"[yellow]⚠ Не удалось подключить Claude API: {e}[/yellow]")
                self.llm_node  = LLMTeachNode.mock(node_id="mock_teacher",
                                                   domains={"children","astronomy","cooking"})
                self._llm_real = False
        else:
            self.llm_node  = LLMTeachNode.mock(node_id="mock_teacher",
                                               domains={"children","astronomy","cooking"})
            self._llm_real = False

        self.router.register(self.novice_node)
        self.router.register(self.llm_node)
        self.novice_node.add_mentor(self.llm_node)
        self.router.set_domain_detector(self.domain_detector)

        # Лог событий
        self.log = ActivityLog()

        # Память формулировок (двойная запись вопросов + рефлексия)
        from core.question_trace import VoiceMemory
        self.voice_memory = VoiceMemory(max_traces=200)

        # Состояние цикла
        self._paused    = False
        self._stop      = False
        self._cycle_n   = 0
        self._lock      = threading.Lock()

    # ── Прогрев ───────────────────────────────────────────────────────────────

    def warmup(self) -> int:
        """Один проход по всему корпусу для начальной засева Gen."""
        count = 0
        for info in CORPUS.values():
            for tok in self.driver.produce(info["text"]):
                self.system.process_token(tok)
                count += 1
        return count

    # ── Скормить текст ────────────────────────────────────────────────────────

    def feed_text(self, text: str) -> int:
        """Скормить произвольный текст через driver → system."""
        count = 0
        for tok in self.driver.produce(text):
            self.system.process_token(tok)
            count += 1
        return count

    # ── Задать вопрос через гетерархию ────────────────────────────────────────

    def ask_heterarchy(
        self,
        question: str,
        logical_form: Optional[str] = None,
        char_name: str = "",
        role: str = "",
    ) -> Optional[str]:
        """
        Задать вопрос → LLM-учитель отвечает → результат скармливается модели.

        Parameters
        ----------
        question      : финальный (нарративный) вопрос для отправки
        logical_form  : исходный сухой вопрос (если None = совпадает с question)
        char_name     : имя персонажа, чьим голосом озвучен вопрос
        role          : архетип роли (_VoiceRole.name)
        """
        from core.question_trace import QuestionTrace

        # Проверить бюджет + rate limit
        if not self.budget.can_ask():
            remaining = self.budget.remaining()
            self.log.add("llm_skip",
                         f"Дневной лимит исчерпан (осталось {remaining})")
            return None
        wait = self.rate_lim.seconds_until_next()
        if wait > 0:
            self.log.add("llm_skip",
                         f"Rate limit: следующий вызов через {wait:.0f}с")
            return f"[wait:{wait:.0f}s]"

        self.budget.consume()
        self.rate_lim.consume()
        domain = self.novice_node._detect_domain(question)
        self.log.add("llm_ask", f"Вопрос: «{question[:60]}» (домен: {domain or '?'})")

        # Создать trace перед ответом
        trace = QuestionTrace.begin(
            logical_form     = logical_form or question,
            narrative_form   = question,
            char_name        = char_name,
            role             = role,
            gen_count_before = self.gen_count,
        )

        resp = self.router.route(question, self.novice_node, domain=domain)
        if resp:
            n = self.novice_node.learn_from_response(resp, self.driver)
            tokens_str = " ".join(resp.tokens[:8])
            self.log.add("llm_answer",
                         f"← {resp.source_id}: «{tokens_str}» (+{n} tok)")
            # Финализировать trace
            trace.finish(
                gen_count_after = self.gen_count,
                answer_tokens   = list(resp.tokens[:20]),
            )
            self.voice_memory.record(trace)
            if trace.gen_delta > 0:
                self.log.add("reflect",
                             f"Δgen={trace.gen_delta:+d} q={trace.quality_score:.2f} "
                             f"({char_name or 'sys'}/{role or '?'})")
            return tokens_str
        else:
            # Пустой ответ — записать нулевой trace
            trace.finish(gen_count_after=self.gen_count)
            self.voice_memory.record(trace)
            self.log.add("error", "Нет ответа от гетерархии")
            return None

    # ── CharacterVoice ────────────────────────────────────────────────────────

    def _voice_question(self, question: str) -> str:
        """Переформулировать вопрос в голосе персонажа (только текст)."""
        voiced, _, _ = self._voice_question_with_meta(question)
        return voiced

    def _voice_question_with_meta(
        self, question: str
    ) -> tuple:
        """
        Переформулировать вопрос в голосе персонажа.

        Returns
        -------
        (voiced_question, char_name, role_name)
        voiced_question = оригинал если персонажей нет.
        """
        try:
            from drivers.narrator_driver import NarratorDriver, CharacterVoice
            narrator = NarratorDriver(self.system.base, seed=None)
            profiles = narrator.character_profiles(max_profiles=3)
            if not profiles:
                return question, "", ""
            voice = CharacterVoice(profiles)
            voiced = voice.voice_questions([question], max_chars=3)
            if not voiced:
                return question, "", ""
            # Персонаж для первого вопроса (индекс 0 → profiles[0])
            p    = profiles[0]
            role = voice.role_of(p.name)
            return voiced[0], p.name, role.name if role else ""
        except Exception:
            return question, "", ""

    def voiced_gap_questions(self, max_questions: int = 5, max_chars: int = 3) -> List[str]:
        """
        Вернуть список вопросов о пробелах знания, озвученных персонажами.

        Используется из /ask и из терминала для отображения любопытства модели.
        """
        try:
            from drivers.narrator_driver import NarratorDriver
            narrator = NarratorDriver(self.system.base, seed=None)
            return narrator.voiced_questions(
                max_questions=max_questions, max_chars=max_chars
            )
        except Exception:
            return []

    # ── Один шаг автономного цикла ────────────────────────────────────────────

    def _loop_step(self) -> str:
        """Один цикл активного чтения. Возвращает статус."""
        from core.query_builder import QueryBuilder, LeakyTemplate
        from app.text_server import ZoomLevel
        from core.exploration import ProbeChain
        from drivers.narrator_driver import NarratorDriver

        qbuilder = QueryBuilder()

        # Строим шаблон из текущего состояния Gen
        templates = qbuilder.build_from_active_gen(self.system)
        if not templates:
            # Холодный старт: читаем случайный документ
            docs = self.server.list_documents()
            if not docs:
                return "empty_corpus"
            import random
            doc_id = random.choice(docs)
            from app.text_server import SearchMatch
            self.server.navigate_to(
                SearchMatch(doc_id=doc_id, para_idx=0, token_idx=0, fragment="")
            )
            frag = self.server.read(20)
            text = " ".join(frag.tokens)
            n = self.feed_text(text)
            self.server._policy.record_visit(frag.doc_id, frag.para_idx, frag.tokens)
            return f"cold_start:{doc_id}(+{n}tok)"

        t = templates[0]
        hits = self.server.search(t, zoom=ZoomLevel.CORPUS, max_hits=10)

        if hits:
            # Выбрать лучший фрагмент (ExplorationPolicy внутри select)
            best = self.server._policy.select(hits, self.server._corpus, top_k=1)
            chosen = best[0] if best else hits[0]

            # ProbeChain: быстрая проверка гипотезы
            if len(t.slots) >= 2:
                self.server.navigate_to(chosen)
                chain = ProbeChain.from_template(t, max_steps=3)
                chain_res = chain.run(self.server)
                if not chain_res.passed:
                    return f"probe_abort:{chosen.doc_id}[{chosen.para_idx}]"

            self.server.navigate_to(chosen)
            frag = self.server.read(15)
            n = self.feed_text(" ".join(frag.tokens))
            self.server._policy.record_visit(frag.doc_id, frag.para_idx, frag.tokens)
            return f"search_hit:{frag.doc_id}[{frag.para_idx}](+{n}tok)"

        else:
            # Промах поиска → спросить LLM если можно
            status = f"search_miss:«{t}»"
            if self.rate_lim.can_call() and self.budget.can_ask():
                # Сухой логический вопрос
                logical_q = f"Что идёт после «{t.anchor or '?'}»?"
                # Нарративный голос персонажа + имя/роль для trace
                voiced_q, char_name, role = self._voice_question_with_meta(logical_q)
                self.ask_heterarchy(
                    voiced_q,
                    logical_form=logical_q,
                    char_name=char_name,
                    role=role,
                )
            return status

    # ── Управление циклом ─────────────────────────────────────────────────────

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    def stop(self) -> None:
        self._stop = True

    @property
    def gen_count(self) -> int:
        return self.system.base.size()

    @property
    def cycle_count(self) -> int:
        return self._cycle_n

    def snapshot(self) -> Dict:
        stats = self.server.stats
        bstats = self.budget.stats()
        return {
            "gen_count":      self.gen_count,
            "cycle_count":    self._cycle_n,
            "paused":         self._paused,
            "llm_real":       self._llm_real,
            "budget_used":    bstats.get("used_today", 0),
            "budget_limit":   bstats.get("daily_limit", 0),
            "rate_wait":      round(self.rate_lim.seconds_until_next(), 1),
            "server_stats":   stats,
            "exploration":    self.server._policy.stats,
        }

    def top_gens(self, n: int = 8) -> List[Dict]:
        base = self.system.base
        result = []
        for gid in list(base._gens.keys()):
            g = base.get(gid)
            if g and g.label:
                result.append({
                    "label": g.label,
                    "sig":   round(g.significance, 3),
                    "chain": len(g.feature_chain),
                    "success": g.success_count,
                    "stop":    g.stop_count,
                })
        result.sort(key=lambda x: -x["sig"])
        return result[:n]


# ══════════════════════════════════════════════════════════════════════════════
# Background learning loop
# ══════════════════════════════════════════════════════════════════════════════

def run_loop(state: SessionState, cycle_sleep: float) -> None:
    """Фоновый поток: медленный автономный цикл."""
    while not state._stop:
        if state._paused:
            time.sleep(1.0)
            continue

        try:
            status = state._loop_step()
            state._cycle_n += 1

            # Логировать событие
            if status.startswith("search_hit"):
                state.log.add("search_hit", status)
            elif status.startswith("search_miss"):
                state.log.add("search_miss", status)
            elif status.startswith("probe_abort"):
                state.log.add("probe_abort", status)
            elif status.startswith("cold_start"):
                state.log.add("cold_start", status)

            # Периодически логируем прогресс Gen
            if state._cycle_n % 5 == 0:
                state.log.add(
                    "gen_update",
                    f"Gen: {state.gen_count}  "
                    f"loops: {state._cycle_n}  "
                    f"visits: {state.server._policy.stats['total_visits']}"
                )

        except Exception as e:
            state.log.add("error", f"Ошибка цикла: {e}")

        time.sleep(cycle_sleep)


# ══════════════════════════════════════════════════════════════════════════════
# FastAPI приложение (использует SessionState)
# ══════════════════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════════════════
# Pydantic-модели для API (module-level — FastAPI их видит как body params)
# ══════════════════════════════════════════════════════════════════════════════

try:
    from pydantic import BaseModel as _BM

    class _AddDocReq(_BM):
        doc_id: str; content: str
        domain: str = ""; title: str = ""

    class _FeedReq(_BM):
        text: str

    class _AskReq(_BM):
        question: str

    class _TalkReq(_BM):
        text: str
        learn: bool = True

    class _SlotM(_BM):
        kind: str; words: List[str] = []; max_gap: int = 0; min_gap: int = 0

    class _SearchReq(_BM):
        slots: List[_SlotM]; source: str = "api"
        confidence: float = 0.5; zoom: str = "CORPUS"; max_hits: int = 10

except ImportError:
    pass   # FastAPI optional — TUI работает без него


def build_api(state: SessionState):
    """Создать FastAPI приложение, шарящее state с TUI."""
    from fastapi import FastAPI, HTTPException
    from fastapi.middleware.cors import CORSMiddleware
    from core.query_builder import LeakyTemplate, TemplateSlot
    from app.text_server import ZoomLevel

    api = FastAPI(title="FirstAGI Live Session API", version="1.0.0")
    api.add_middleware(CORSMiddleware, allow_origins=["*"],
                       allow_methods=["*"], allow_headers=["*"])

    # ── Документы ─────────────────────────────────────────────────────────────

    @api.post("/documents")
    def add_doc(req: _AddDocReq):
        state.server.add_document(req.doc_id, req.content,
                                  domain=req.domain, title=req.title)
        state.domain_detector.add_example(req.content, req.domain or "unknown")
        state.log.add("user_feed", f"Документ добавлен: {req.doc_id}")
        return {"ok": True, "corpus_size": state.server.document_count()}

    @api.get("/documents")
    def list_docs(domain: str = ""):
        return {"docs": state.server.list_documents(domain=domain)}

    # ── Чат ───────────────────────────────────────────────────────────────────

    @api.post("/feed")
    def feed(req: _FeedReq):
        n = state.feed_text(req.text)
        state.log.add("user_feed", f"Пользователь скормил {n} токенов")
        return {"ok": True, "tokens_fed": n, "gen_count": state.gen_count}

    @api.post("/ask")
    def ask(req: _AskReq):
        answer = state.ask_heterarchy(req.question)
        return {
            "question": req.question,
            "answer":   answer,
            "gen_count": state.gen_count,
        }

    # ── Состояние ─────────────────────────────────────────────────────────────

    @api.get("/stats")
    def stats():
        return state.snapshot()

    @api.get("/activity")
    def activity(n: int = 30):
        return {"events": state.log.to_list()[-n:]}

    @api.get("/top_gens")
    def top_gens(n: int = 10):
        return {"gens": state.top_gens(n)}

    @api.get("/voices")
    def voices(n: int = 5, chars: int = 3):
        """Вопросы модели, озвученные персонажами из её историй."""
        return {"voiced_questions": state.voiced_gap_questions(max_questions=n, max_chars=chars)}

    @api.get("/reflect")
    def reflect():
        """Рефлексия: статистика качества голосовых формулировок вопросов."""
        mem   = state.voice_memory
        stats = mem.stats()
        recent = [
            {
                "logical":   t.logical_form,
                "narrative": t.narrative_form,
                "char":      t.char_name,
                "role":      t.role,
                "gen_delta": t.gen_delta,
                "quality":   round(t.quality_score, 3),
                "overlap":   round(t.narrative_overlap, 3),
            }
            for t in mem.all_scored()[:10]
        ]
        return {"stats": stats, "best_traces": recent}

    # ── Навигация ─────────────────────────────────────────────────────────────

    @api.post("/search")
    def search(req: _SearchReq):
        slots = [TemplateSlot(kind=s.kind, words=s.words,
                              max_gap=s.max_gap, min_gap=s.min_gap)
                 for s in req.slots]
        template = LeakyTemplate(slots=slots, source=req.source,
                                 confidence=req.confidence)
        try:
            zoom = ZoomLevel[req.zoom.upper()]
        except KeyError:
            raise HTTPException(400, f"Unknown zoom: {req.zoom}")
        hits = state.server.search(template, zoom=zoom, max_hits=req.max_hits)
        return {
            "hits":  [{"doc_id": h.doc_id, "para_idx": h.para_idx,
                       "fragment": h.fragment} for h in hits],
            "total": len(hits),
            "regex": template.to_regex().pattern,
        }

    # ── Разговор с моделью ────────────────────────────────────────────────────

    @api.post("/talk")
    def talk(req: _TalkReq):
        """
        Обработать текст пошагово через InferencePeephole.
        Возвращает список шагов: что модель ожидала, что пришло, что поймала.
        Пока идёт /talk — фоновый цикл приостанавливается автоматически.
        """
        from core.inference_peephole import InferencePeephole
        from drivers.text_driver import TextDriver as _TD

        was_paused = state._paused
        steps = []

        with state._talk_lock:
            state._paused = True   # стоп-пауза для цикла во время разговора
            try:
                peep = InferencePeephole(state.system, top_k=5, cascade_threshold=2)
                drv  = _TD(state.system)

                for tok in drv.produce(req.text):
                    snap = peep.step(tok)

                    active = []
                    for g in snap.active:
                        deep_labels = [d.label for d in g.deep_chains[:2]]
                        active.append({
                            "label":     g.label or "?",
                            "sig":       round(g.significance, 3),
                            "chain":     g.chain_len,
                            "progress":  g.progress,
                            "competing": g.is_competing,
                            "deep":      deep_labels,
                        })

                    steps.append({
                        "token":       snap.token_label or tok.label or "?",
                        "outcome":     snap.outcome.name if snap.outcome else "?",
                        "active":      active,
                        "n_active":    snap.n_active,
                        "n_competing": snap.n_competing,
                        "max_chain":   snap.max_chain,
                        "is_cascade":  snap.is_cascade,
                        "is_shift":    snap.is_context_shift,
                        "new_gen":     snap.new_gen_id,
                        "elapsed_ms":  round(snap.elapsed_ms, 2),
                    })

                    if req.learn:
                        state.log.add("user_feed",
                                      f"talk/{snap.token_label}→{snap.outcome.name if snap.outcome else '?'}")

            finally:
                state._paused = was_paused

        return {
            "text":       req.text,
            "steps":      steps,
            "gen_before": state.gen_count,
        }

    # ── Управление циклом ─────────────────────────────────────────────────────

    @api.post("/loop/pause")
    def pause(): state.pause(); return {"paused": True}

    @api.post("/loop/resume")
    def resume(): state.resume(); return {"paused": False}

    @api.get("/loop/status")
    def loop_status():
        return {"paused": state._paused, "cycles": state._cycle_n,
                "gen_count": state.gen_count}

    return api


def run_server(state: SessionState, port: int) -> None:
    """Фоновый поток: uvicorn сервер."""
    import uvicorn
    api = build_api(state)
    config = uvicorn.Config(
        api, host="127.0.0.1", port=port,
        log_level="warning",    # не засорять вывод
        access_log=False,
    )
    server = uvicorn.Server(config)
    server.run()


# ══════════════════════════════════════════════════════════════════════════════
# TUI — Rich-терминал
# ══════════════════════════════════════════════════════════════════════════════

def print_header(state: SessionState, port: int) -> None:
    llm_tag = (
        "[green]Claude API[/green]" if state._llm_real
        else "[yellow]mock LLM[/yellow]"
    )
    console.print(Panel(
        f"[bold cyan]🧠 FirstAGI Live Session[/bold cyan]\n"
        f"Сервер: [link]http://localhost:{port}[/link]  |  "
        f"Docs: [link]http://localhost:{port}/docs[/link]\n"
        f"LLM: {llm_tag}  |  "
        f"Цикл: {state.args.cycle}с  |  "
        f"Rate limit: {state.args.llm_interval}с  |  "
        f"Бюджет: {state.args.daily_limit}/день\n\n"
        f"[dim]Команды: > текст  /ask вопрос  /status  /top N  "
        f"/corpus  /add id текст  /voices N  /reflect  /pause  /resume  /quit[/dim]",
        box=box.ROUNDED,
        border_style="cyan",
    ))


def print_status(state: SessionState) -> None:
    snap = state.snapshot()
    exp  = snap["exploration"]

    t = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
    t.add_column("key",   style="dim", no_wrap=True)
    t.add_column("value", style="bright_white")
    t.add_row("Gen-база",     f"{snap['gen_count']} обобщений")
    t.add_row("Циклов",       str(snap["cycle_count"]))
    t.add_row("LLM вызовов",  f"{snap['budget_used']}/{snap['budget_limit']} (ждать {snap['rate_wait']}с)")
    t.add_row("Визитов",      f"{exp['total_visits']} ({exp['unique_paras']} уникальных)")
    t.add_row("Revisit rate", f"{exp['revisit_rate']:.0%}")
    ss = snap["server_stats"]
    t.add_row("Поисков",      f"{ss['searches']} (hit: {ss['hits']}, miss: {ss['misses']})")
    t.add_row("Probe chains", f"{ss['probe_chains']} (aborts: {ss['probe_aborts']})")
    t.add_row("Корпус",       f"{ss['corpus_size']} документов")

    console.print(Panel(t, title="[bold]Состояние модели[/bold]", border_style="blue"))


def print_top_gens(state: SessionState, n: int = 10) -> None:
    gens = state.top_gens(n)
    if not gens:
        console.print("[dim]Gen-база пуста[/dim]")
        return
    t = Table(box=box.SIMPLE, show_header=True, header_style="bold dim")
    t.add_column("Метка",    style="cyan")
    t.add_column("Sig",      justify="right")
    t.add_column("Chain",    justify="right")
    t.add_column("✓/✗",      justify="right")
    for g in gens:
        bar = "█" * min(10, int(g["sig"] * 10))
        t.add_row(
            g["label"], f"{g['sig']:.3f} [dim]{bar}[/dim]",
            str(g["chain"]),
            f"[green]{g['success']}[/green]/[red]{g['stop']}[/red]",
        )
    console.print(Panel(t, title="[bold]Топ Gen[/bold]", border_style="green"))


def print_corpus(state: SessionState) -> None:
    docs = state.server.list_documents()
    t = Table(box=box.SIMPLE)
    t.add_column("ID",    style="cyan")
    t.add_column("Домен", style="dim")
    t.add_column("Визитов", justify="right")
    vmap = state.server._policy.visit_map()
    for doc_id in docs:
        entry = state.server._corpus.get(doc_id)
        domain = entry.domain if entry else "?"
        visits = sum(cnt for (d, _), cnt in vmap.items() if d == doc_id)
        t.add_row(doc_id, domain, str(visits))
    console.print(Panel(t, title="[bold]Корпус[/bold]", border_style="yellow"))


def print_activity(state: SessionState, n: int = 20) -> None:
    console.print(Panel(
        state.log.format_rich(n),
        title="[bold]Последние события[/bold]",
        border_style="magenta",
    ))


def _print_reflect(state: SessionState) -> None:
    """Вывести рефлексию: статистика качества формулировок вопросов."""
    from rich.table import Table
    mem   = state.voice_memory
    stats = mem.stats()

    if stats["scored"] == 0:
        console.print("[dim]Рефлексия: вопросов к LLM ещё не было[/dim]")
        return

    # Сводка
    console.print(Panel(
        f"  Всего вопросов:     [bold]{stats['total']}[/bold]\n"
        f"  Оценено:            [bold]{stats['scored']}[/bold]\n"
        f"  Ср. качество:       [bold green]{stats['avg_quality']:.3f}[/bold green]\n"
        f"  Ср. Δgen:           [bold]{stats['avg_gen_delta']:.1f}[/bold]\n"
        f"  Ср. overlap:        [bold]{stats['avg_overlap']:.3f}[/bold]\n"
        f"  Лучшая роль:        [bold magenta]{stats['best_role'] or '—'}[/bold magenta]",
        title="🔍 Рефлексия формулировок", border_style="cyan",
    ))

    # По ролям
    ranking = mem.role_ranking()
    if ranking:
        tbl = Table(title="Роли по качеству", box=None, header_style="bold dim")
        tbl.add_column("Роль",    style="magenta")
        tbl.add_column("Ср. q",   justify="right")
        for role, q in ranking:
            tbl.add_row(role, f"{q:.3f}")
        console.print(tbl)

    # Лучшие формулировки
    best = mem.all_scored()[:3]
    if best:
        lines = []
        for t in best:
            lines.append(
                f"  [green]Δ{t.gen_delta:+d}[/green] [{t.role}/{t.char_name}]  "
                f"[dim]{t.narrative_form[:60]}[/dim]"
            )
        console.print(Panel("\n".join(lines), title="Топ формулировок", border_style="green"))


# ══════════════════════════════════════════════════════════════════════════════
# Периодические обновления в TUI
# ══════════════════════════════════════════════════════════════════════════════

_last_status_print = [0.0]
_STATUS_INTERVAL   = 15.0   # показывать статус каждые N секунд


def maybe_print_status(state: SessionState) -> None:
    now = time.time()
    if now - _last_status_print[0] >= _STATUS_INTERVAL:
        _last_status_print[0] = now
        console.rule("[dim]── обновление ──[/dim]")
        print_activity(state, n=10)
        snap = state.snapshot()
        console.print(
            f"  [dim]Gen: [bright_white]{snap['gen_count']}[/bright_white]  "
            f"loops: [bright_white]{snap['cycle_count']}[/bright_white]  "
            f"LLM: [bright_white]{snap['budget_used']}/{snap['budget_limit']}[/bright_white]  "
            f"rate_wait: [bright_white]{snap['rate_wait']}с[/bright_white][/dim]"
        )


# ══════════════════════════════════════════════════════════════════════════════
# Интерактивный REPL
# ══════════════════════════════════════════════════════════════════════════════

def handle_command(line: str, state: SessionState) -> bool:
    """
    Обработать команду пользователя.
    Возвращает False → выход.
    """
    line = line.strip()
    if not line:
        return True

    # Системные команды
    if line.lower() in ("/quit", "/exit", "/q"):
        return False

    if line.lower() == "/status":
        print_status(state)
        return True

    if line.lower().startswith("/top"):
        parts = line.split()
        n = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 10
        print_top_gens(state, n)
        return True

    if line.lower() == "/corpus":
        print_corpus(state)
        return True

    if line.lower() == "/activity":
        print_activity(state, n=20)
        return True

    if line.lower() == "/pause":
        state.pause()
        console.print("[yellow]⏸ Цикл приостановлен[/yellow]")
        state.log.add("loop_paused", "Приостановлено пользователем")
        return True

    if line.lower() == "/resume":
        state.resume()
        console.print("[green]▶ Цикл возобновлён[/green]")
        state.log.add("loop_resumed", "Возобновлено пользователем")
        return True

    if line.lower().startswith("/add "):
        # /add doc_id текст текст текст
        rest = line[5:].strip()
        parts = rest.split(None, 1)
        if len(parts) < 2:
            console.print("[red]Использование: /add doc_id текст документа[/red]")
            return True
        doc_id, text = parts[0], parts[1]
        state.server.add_document(doc_id, text, domain="user", title=doc_id)
        state.domain_detector.add_example(text, "user")
        state.log.add("user_feed", f"Добавлен документ «{doc_id}»")
        console.print(f"[green]✓ Документ «{doc_id}» добавлен в корпус[/green]")
        return True

    if line.lower().startswith("/ask "):
        question = line[5:].strip()
        if not question:
            console.print("[red]Введите вопрос после /ask[/red]")
            return True
        console.print(f"[magenta]❓ Задаём вопрос гетерархии: «{question}»[/magenta]")
        state.log.add("user_ask", f"«{question}»")
        answer = state.ask_heterarchy(question)
        if answer and not answer.startswith("[wait"):
            console.print(f"[blue]💬 Ответ: «{answer}»[/blue]")
        elif answer and answer.startswith("[wait"):
            wait = answer[6:-2]
            console.print(f"[yellow]⏳ Rate limit: подожди {wait} секунд[/yellow]")
        else:
            console.print("[dim]Ответа нет[/dim]")
        return True

    if line.lower().startswith("/voices"):
        parts = line.split()
        n = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 5
        voiced = state.voiced_gap_questions(max_questions=n, max_chars=3)
        if not voiced:
            console.print("[dim]Персонажей пока нет — модель ещё не обучилась[/dim]")
        else:
            from rich.panel import Panel
            lines = "\n".join(f"  {q}" for q in voiced)
            console.print(Panel(lines, title="🎭 Голоса персонажей", border_style="magenta"))
        return True

    if line.lower() == "/reflect":
        _print_reflect(state)
        return True

    # Просто текст — скормить модели
    n = state.feed_text(line)
    state.log.add("user_feed", f"Пользователь: «{line[:50]}» (+{n} tok)")
    console.print(f"[green]✓ Скормлено {n} токенов. Gen: {state.gen_count}[/green]")
    return True


# ══════════════════════════════════════════════════════════════════════════════
# Главная функция
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(
        description="FirstAGI Live Session — модель учится в фоне"
    )
    parser.add_argument("--port",         type=int,   default=8073,
                        help="Порт HTTP-сервера (default: 8073)")
    parser.add_argument("--cycle",        type=float, default=8.0,
                        help="Пауза между циклами, сек (default: 8)")
    parser.add_argument("--llm-interval", type=float, default=45.0,
                        dest="llm_interval",
                        help="Мин. интервал между LLM-вызовами, сек (default: 45)")
    parser.add_argument("--daily-limit",  type=int,   default=20,
                        dest="daily_limit",
                        help="Макс. LLM-вызовов в сутки (default: 20)")
    parser.add_argument("--api-key",      type=str,   default="",
                        dest="api_key",
                        help="Anthropic API key (или ANTHROPIC_API_KEY)")
    parser.add_argument("--no-llm",       action="store_true",
                        dest="no_llm",
                        help="Отключить LLM (использовать mock)")
    parser.add_argument("--warmup",       action="store_true",
                        help="Прогреть модель на корпусе перед стартом")
    parser.add_argument("--verbose",      action="store_true")
    args = parser.parse_args()

    # Инициализация
    console.print("[dim]Инициализация...[/dim]")
    state = SessionState(args)

    if args.warmup:
        console.print("[dim]Прогрев на корпусе...[/dim]")
        n = state.warmup()
        console.print(f"[green]✓ Прогрев: {n} токенов, {state.gen_count} Gen[/green]")
    else:
        # Минимальный прогрев одним текстом
        for tok in state.driver.produce(CORPUS["children_1"]["text"]):
            state.system.process_token(tok)
        state.log.add("cold_start",
                      f"Начальный прогрев: {state.gen_count} Gen")

    # Запустить фоновый сервер
    srv_thread = threading.Thread(
        target=run_server, args=(state, args.port), daemon=True
    )
    srv_thread.start()
    time.sleep(0.8)   # дать uvicorn запуститься

    # Запустить фоновый обучающий цикл
    loop_thread = threading.Thread(
        target=run_loop, args=(state, args.cycle), daemon=True
    )
    loop_thread.start()

    # TUI
    print_header(state, args.port)
    console.print()
    print_status(state)

    console.print(
        "\n[dim]Модель работает в фоне. Введите команду или текст для обучения.[/dim]\n"
    )

    # REPL или headless-режим
    def _headless_loop() -> None:
        console.print("[dim]Headless режим — статус каждые 15с (Ctrl-C для остановки)[/dim]")
        while not state._stop:
            time.sleep(_STATUS_INTERVAL)
            console.rule("[dim]── обновление ──[/dim]")
            print_activity(state, n=8)
            snap = state.snapshot()
            console.print(
                f"  [dim]Gen: [bright_white]{snap['gen_count']}[/bright_white]  "
                f"loops: [bright_white]{snap['cycle_count']}[/bright_white]  "
                f"LLM: [bright_white]{snap['budget_used']}/{snap['budget_limit']}[/bright_white][/dim]"
            )

    try:
        while True:
            maybe_print_status(state)
            try:
                line = input("  > ")
            except EOFError:
                # stdin закрыт (фоновый процесс) → headless
                _headless_loop()
                break
            if not handle_command(line, state):
                break
    except KeyboardInterrupt:
        pass
    finally:
        state.stop()
        console.print("\n[dim]Сессия завершена. Итог:[/dim]")
        print_status(state)


if __name__ == "__main__":
    main()
