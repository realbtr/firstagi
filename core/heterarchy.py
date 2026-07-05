"""
core/heterarchy.py — Гетерархия моделей.

Архитектура
───────────
Каждая модель — это ModelNode с:
  - Собственным LearningSystem (своя Gen-база)
  - Набором доменов ({"astronomy", "cooking", ...})
  - Уровнем опыта (0=новичок → 3=мастер)
  - Связями: peers (того же уровня), mentors (старших)

Протокол обучения
─────────────────
Молодая модель генерирует вопрос (PatternQuestion):
  "Кто ещё принёс маше?"

HeterarchyRouter:
  1. Определяет домен по ключевым словам вопроса
  2. Роутит в подходящее сообщество (коллекцию ModelNode)
  3. Каждый узел возвращает ответ: последовательность токенов
  4. Молодая модель обрабатывает последовательность → новые Gen

Форматы ответов
───────────────
  TeachResponse.tokens   — прямая последовательность токенов для обработки
  TeachResponse.fragment — фрагмент текста (для ActiveTextServer)
  TeachResponse.redirect — "перейди в другое сообщество"

Гетерархия vs Иерархия
───────────────────────
В иерархии есть один начальник. В гетерархии узлы равны внутри уровня,
но связаны горизонтально (peers) и вертикально (mentors/students).
Наша модель может учиться у астрономов по астрономии и у кулинаров
по кулинарии — они не знают друг о друге.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Set


# ══════════════════════════════════════════════════════════════════════════════
# Структуры данных
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class TeachRequest:
    """Запрос на обучение от младшей модели к старшей."""
    question:     str            # "Кто ещё принёс маше?"
    domain_hint:  str = ""       # домен, если известен
    context_tokens: List[str] = field(default_factory=list)  # последние токены контекста
    origin_id:    str = ""       # node_id задающего вопрос


@dataclass
class TeachResponse:
    """Ответ от старшей модели."""
    tokens:    List[str]      # последовательность токенов для обработки
    domain:    str = ""
    source_id: str = ""       # node_id ответившего
    redirect:  str = ""       # если нужно перенаправить в другое сообщество
    confidence: float = 1.0


# ══════════════════════════════════════════════════════════════════════════════
# ModelNode
# ══════════════════════════════════════════════════════════════════════════════

class ModelNode:
    """
    Один узел в гетерархии моделей.

    Параметры
    ─────────
    node_id         — уникальный ID
    system          — LearningSystem этой модели
    domains         — набор тематических доменов
    experience      — уровень опыта (0=новичок, 1=junior, 2=senior, 3=master)
    teach_fn        — опциональный внешний обработчик запросов (для LLM-узлов)
    """

    def __init__(
        self,
        node_id: str,
        system,
        domains: Optional[Set[str]] = None,
        experience: int = 0,
        teach_fn: Optional[Callable[[TeachRequest], TeachResponse]] = None,
    ) -> None:
        self.node_id    = node_id
        self.system     = system
        self.domains    = domains or set()
        self.experience = experience
        self._teach_fn  = teach_fn

        self.peers:   List[ModelNode] = []   # того же уровня
        self.mentors: List[ModelNode] = []   # старших
        self.students: List[ModelNode] = []  # младших

        self._teach_log: List[Dict] = []
        self._learn_log: List[Dict] = []
        self._domain_detector = None   # опциональный DomainDetector

    # ── Связи ─────────────────────────────────────────────────────────────────

    def add_mentor(self, mentor: ModelNode) -> None:
        if mentor not in self.mentors:
            self.mentors.append(mentor)
            if self not in mentor.students:
                mentor.students.append(self)

    def add_peer(self, peer: ModelNode) -> None:
        if peer not in self.peers:
            self.peers.append(peer)
            if self not in peer.peers:
                peer.peers.append(self)

    # ── Запрос обучения ───────────────────────────────────────────────────────

    def ask(
        self,
        question: str,
        domain_hint: str = "",
        context_tokens: Optional[List[str]] = None,
    ) -> Optional[TeachResponse]:
        """
        Задать вопрос вышестоящим узлам.
        Сначала пробуем peers, потом mentors.
        """
        req = TeachRequest(
            question        = question,
            domain_hint     = domain_hint or self._detect_domain(question),
            context_tokens  = context_tokens or [],
            origin_id       = self.node_id,
        )

        # 1. Попробовать peers (горизонтальные связи — быстро)
        for peer in self.peers:
            if req.domain_hint in peer.domains or not req.domain_hint:
                resp = peer._handle_teach_request(req)
                if resp:
                    self._learn_log.append({
                        "from": peer.node_id, "q": question, "t": time.time()
                    })
                    return resp

        # 2. Попробовать mentors (вертикальные связи — богаче)
        for mentor in sorted(self.mentors, key=lambda m: -m.experience):
            if req.domain_hint in mentor.domains or not req.domain_hint:
                resp = mentor._handle_teach_request(req)
                if resp:
                    self._learn_log.append({
                        "from": mentor.node_id, "q": question, "t": time.time()
                    })
                    return resp

        return None

    def _handle_teach_request(self, req: TeachRequest) -> Optional[TeachResponse]:
        """Обработать входящий запрос на обучение."""
        if self._teach_fn:
            # Внешний обработчик (например LLM)
            try:
                return self._teach_fn(req)
            except Exception:
                return None

        # Внутренний: поискать в своей Gen-базе ответ на вопрос
        tokens = self._query_own_base(req.question)
        if not tokens:
            return None

        resp = TeachResponse(
            tokens    = tokens,
            domain    = list(self.domains)[0] if self.domains else "",
            source_id = self.node_id,
        )
        self._teach_log.append({
            "to": req.origin_id, "q": req.question, "tokens": tokens, "t": time.time()
        })
        return resp

    def _query_own_base(self, question: str) -> List[str]:
        """
        Найти в своей Gen-базе токены, релевантные вопросу.
        Простая эвристика: взять Gen с label, содержащим ключевые слова вопроса.
        """
        keywords = set(question.lower().replace("?", "").split()) - {
            "кто", "что", "где", "как", "ещё", "еще", "может", "ли"
        }
        if not keywords:
            return []

        # Топ-5 Gen с label совпадающим с ключевыми словами
        candidates = []
        for gid in list(self.system.base._gens.keys()):
            g = self.system.base.get(gid)
            if g and g.label:
                label_words = set(g.label.lower().replace("·", " ").split())
                overlap = label_words & keywords
                if overlap:
                    candidates.append((g, len(overlap) / len(keywords), g.significance))

        candidates.sort(key=lambda x: -(x[1] * x[2]))

        # Составить последовательность токенов из найденных Gen
        tokens: List[str] = []
        for gen, _, _ in candidates[:3]:
            label = gen.label or ""
            tokens.extend(label.replace("·", " ").split())

        return tokens[:15]  # ограничить ответ

    def _detect_domain(self, text: str) -> str:
        """
        Определить домен по тексту вопроса.
        Если к узлу привязан DomainDetector — использовать его,
        иначе — словарная эвристика.
        """
        if hasattr(self, "_domain_detector") and self._domain_detector is not None:
            return self._domain_detector.detect(text)

        # Словарная эвристика (fallback)
        domain_keywords = {
            "astronomy":  {"звезда", "планета", "галактика", "телескоп", "орбита"},
            "cooking":    {"рецепт", "блюдо", "готовить", "ингредиент", "вкус"},
            "children":   {"медведь", "маша", "пух", "мама", "папа", "кот"},
            "science":    {"закон", "теория", "опыт", "эксперимент", "физика"},
        }
        tokens = set(text.lower().split())
        best_domain, best_score = "", 0
        for domain, kw in domain_keywords.items():
            score = len(tokens & kw)
            if score > best_score:
                best_score, best_domain = score, domain
        return best_domain

    def set_domain_detector(self, detector) -> None:
        """Привязать DomainDetector для более точной классификации."""
        self._domain_detector = detector

    # ── Применить ответ ───────────────────────────────────────────────────────

    def learn_from_response(self, response: TeachResponse, driver) -> int:
        """
        Обработать ответ старшей модели через свой Gen-механизм.
        Возвращает число обработанных токенов.
        """
        if not response.tokens:
            return 0
        text = " ".join(response.tokens)
        count = 0
        for tok in driver.produce(text):
            self.system.process_token(tok)
            count += 1
        return count

    # ── Статистика ────────────────────────────────────────────────────────────

    @property
    def stats(self) -> Dict:
        return {
            "node_id":    self.node_id,
            "experience": self.experience,
            "domains":    list(self.domains),
            "gen_count":  self.system.base.size(),
            "taught":     len(self._teach_log),
            "learned":    len(self._learn_log),
            "peers":      [p.node_id for p in self.peers],
            "mentors":    [m.node_id for m in self.mentors],
            "students":   [s.node_id for s in self.students],
        }

    def __repr__(self) -> str:
        return (f"ModelNode({self.node_id!r}, exp={self.experience}, "
                f"domains={self.domains}, gen={self.system.base.size()})")


# ══════════════════════════════════════════════════════════════════════════════
# HeterarchyRouter — маршрутизация запросов
# ══════════════════════════════════════════════════════════════════════════════

class HeterarchyRouter:
    """
    Маршрутизирует запросы на обучение в гетерархии.

    Логика роутинга
    ───────────────
    1. Определить домен вопроса
    2. Найти ближайший узел с этим доменом и exp > origin.experience
    3. Если не найден — LLM-фоллбэк (если настроен)
    4. Если найден — TeachResponse → learn_from_response
    """

    def __init__(self) -> None:
        self._nodes: Dict[str, ModelNode] = {}
        self._llm_fallback: Optional[Callable[[TeachRequest], TeachResponse]] = None

    def register(self, node: ModelNode) -> None:
        self._nodes[node.node_id] = node

    def set_llm_fallback(self, fn: Callable[[TeachRequest], TeachResponse]) -> None:
        """Настроить LLM как fallback для вопросов, на которые никто не ответил."""
        self._llm_fallback = fn

    def set_domain_detector(self, detector) -> None:
        """
        Привязать DomainDetector ко всем зарегистрированным узлам.
        Вызывать после register() всех узлов.
        """
        for node in self._nodes.values():
            node.set_domain_detector(detector)

    def route(
        self,
        question: str,
        origin: ModelNode,
        domain: str = "",
    ) -> Optional[TeachResponse]:
        """
        Найти подходящий узел и запросить обучение.
        """
        detected_domain = domain or origin._detect_domain(question)

        # Кандидаты: узлы с нужным доменом И более высоким опытом
        candidates = [
            n for n in self._nodes.values()
            if n.node_id != origin.node_id
            and n.experience > origin.experience
            and (not detected_domain or detected_domain in n.domains)
        ]
        candidates.sort(key=lambda n: -n.experience)

        req = TeachRequest(
            question     = question,
            domain_hint  = detected_domain,
            origin_id    = origin.node_id,
        )

        for candidate in candidates:
            resp = candidate._handle_teach_request(req)
            if resp:
                return resp

        # Фоллбэк на LLM
        if self._llm_fallback:
            try:
                return self._llm_fallback(req)
            except Exception:
                pass

        return None

    def build_community(
        self,
        domain: str,
        experience_levels: int = 3,
        systems_factory: Optional[Callable[[int], any]] = None,
    ) -> List[ModelNode]:
        """
        Создать сообщество моделей для домена с заданным числом уровней опыта.
        systems_factory(level) → LearningSystem
        Удобный способ создать полную гетерархию для одного домена.
        """
        if systems_factory is None:
            from core.learning import LearningSystem
            systems_factory = lambda lvl: LearningSystem()

        nodes = []
        for lvl in range(experience_levels):
            node = ModelNode(
                node_id    = f"{domain}_l{lvl}",
                system     = systems_factory(lvl),
                domains    = {domain},
                experience = lvl,
            )
            self.register(node)
            nodes.append(node)

        # Связать уровни: каждый узел учится у всех более старших
        for i, node in enumerate(nodes):
            for mentor in nodes[i + 1:]:
                node.add_mentor(mentor)

        return nodes

    def summary(self) -> str:
        lines = [f"  Узлов в гетерархии: {len(self._nodes)}"]
        by_domain: Dict[str, List[str]] = {}
        for n in self._nodes.values():
            for d in n.domains:
                by_domain.setdefault(d, []).append(f"{n.node_id}(exp={n.experience})")
        for domain, nodes in sorted(by_domain.items()):
            lines.append(f"  {domain}: {', '.join(nodes)}")
        return "\n".join(lines)
