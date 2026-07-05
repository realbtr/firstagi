"""
tests/test_active_corpus.py — Тесты Active Corpus Server + компонентов.

Покрывает:
  ExplorationPolicy  — новизна + энтропийный бонус
  ProbeChain         — цепочки зондирования
  DomainDetector     — словарная классификация
  LLMTeachNode       — mock-узел с LLM бэкендом
  ActiveTextServer   — интеграция с ExplorationPolicy и ProbeChain
"""
from __future__ import annotations

import pytest
from collections import Counter

# ── Imports ────────────────────────────────────────────────────────────────

from core.exploration import (
    ExplorationPolicy, ProbeChain, ProbeStep, ProbeChainResult,
)
from core.domain_detector import DomainDetector, _tokenize
from core.llm_node import LLMTeachNode, _build_prompt, _parse_response
from core.heterarchy import HeterarchyRouter, ModelNode, TeachRequest
from core.query_builder import LeakyTemplate, TemplateSlot
from app.text_server import ActiveTextServer, ZoomLevel


# ══════════════════════════════════════════════════════════════════════════════
# ExplorationPolicy
# ══════════════════════════════════════════════════════════════════════════════

class TestExplorationPolicy:

    def test_initial_score_equal(self):
        pol = ExplorationPolicy()
        s1 = pol.score_match("doc1", 0, ["a", "b"])
        s2 = pol.score_match("doc2", 0, ["a", "b"])
        assert s1 == s2

    def test_revisit_reduces_score(self):
        pol = ExplorationPolicy()
        pol.record_visit("doc1", 0, ["маша", "медведь"])
        pol.record_visit("doc1", 0, ["маша", "медведь"])
        score_visited   = pol.score_match("doc1", 0, ["маша"])
        score_unvisited = pol.score_match("doc2", 0, ["маша"])
        assert score_visited < score_unvisited

    def test_rare_words_increase_entropy_bonus(self):
        pol = ExplorationPolicy()
        # Добавить несколько слов как «известные»
        pol.record_visit("d1", 0, ["маша"] * 10)
        # Фрагмент с редким словом vs фрагмент с известным
        score_rare = pol.score_match("d2", 0, ["квантум", "нейрон"])
        score_common = pol.score_match("d3", 0, ["маша", "маша"])
        assert score_rare >= score_common

    def test_select_returns_unvisited_first(self):
        from app.text_server import SearchMatch

        pol = ExplorationPolicy()
        pol.record_visit("d1", 0, ["tok"] * 5)
        pol.record_visit("d1", 0, ["tok"] * 5)  # дважды

        m1 = SearchMatch(doc_id="d1", para_idx=0, token_idx=0, fragment="a b", score=1.0)
        m2 = SearchMatch(doc_id="d2", para_idx=0, token_idx=0, fragment="c d", score=1.0)

        best = pol.select([m1, m2], corpus={}, top_k=1)
        assert best[0].doc_id == "d2"

    def test_stats(self):
        pol = ExplorationPolicy()
        pol.record_visit("d1", 0, ["a", "b"])
        pol.record_visit("d1", 1, ["c"])
        pol.record_visit("d1", 0, ["a"])  # revisit
        s = pol.stats
        assert s["total_visits"] == 3
        assert s["unique_paras"] == 2
        assert s["revisit_rate"] > 0

    def test_visit_map(self):
        pol = ExplorationPolicy()
        pol.record_visit("d1", 2, ["x"])
        pol.record_visit("d1", 2, ["y"])
        vmap = pol.visit_map()
        assert vmap[("d1", 2)] == 2


# ══════════════════════════════════════════════════════════════════════════════
# ProbeChain
# ══════════════════════════════════════════════════════════════════════════════

class TestProbeChain:

    def _make_server(self, text: str = "Медведь принёс Маше пирог"):
        server = ActiveTextServer(use_probe_chain=False)
        server.add_document("d1", text, domain="test")
        from app.text_server import SearchMatch
        server.navigate_to(SearchMatch(doc_id="d1", para_idx=0, token_idx=0, fragment=""))
        return server

    def test_empty_chain_passes(self):
        server = self._make_server()
        chain = ProbeChain()
        result = chain.run(server)
        assert result.passed is True
        assert result.steps_run == 0

    def test_anchor_hit(self):
        server = self._make_server()
        chain = ProbeChain([ProbeStep(expected="медведь", delta=0, critical=True)])
        result = chain.run(server)
        assert result.passed is True
        assert result.steps_passed == 1

    def test_critical_miss_aborts(self):
        server = self._make_server()
        chain = ProbeChain([ProbeStep(expected="заяц", delta=0, critical=True)])
        result = chain.run(server)
        assert result.passed is False
        assert result.abort_reason != ""

    def test_non_critical_miss_continues(self):
        server = self._make_server()
        chain = ProbeChain([
            ProbeStep(expected="медведь", delta=0, critical=True),
            ProbeStep(expected="неверно",  delta=1, critical=False),
            ProbeStep(expected="маше",     delta=2, critical=False),
        ])
        result = chain.run(server)
        assert result.passed is True
        assert result.steps_run == 3
        assert result.steps_passed == 2

    def test_from_template(self):
        t = LeakyTemplate(
            slots=[
                TemplateSlot(kind="anchor",   words=["принёс"]),
                TemplateSlot(kind="required", words=["маше"], max_gap=2),
            ],
            source="test",
        )
        chain = ProbeChain.from_template(t)
        assert len(chain) == 2
        assert chain._steps[0].expected == "принёс"
        assert chain._steps[0].critical is True

    def test_from_template_max_steps(self):
        slots = [TemplateSlot(kind="anchor", words=[f"w{i}"]) for i in range(10)]
        t = LeakyTemplate(slots=slots, source="test")
        chain = ProbeChain.from_template(t, max_steps=3)
        assert len(chain) == 3

    def test_confidence_all_hit(self):
        server = self._make_server()
        chain = ProbeChain([
            ProbeStep(expected="медведь", delta=0, critical=False),
            ProbeStep(expected="принёс",  delta=1, critical=False),
        ])
        result = chain.run(server)
        assert result.confidence == 1.0

    def test_repr(self):
        chain = ProbeChain([ProbeStep("abc", 0, True)])
        assert "abc@δ0" in repr(chain)


# ══════════════════════════════════════════════════════════════════════════════
# DomainDetector
# ══════════════════════════════════════════════════════════════════════════════

class TestDomainDetector:

    def _make_det(self) -> DomainDetector:
        det = DomainDetector()
        det.add_example(
            "Звёзды светят в ночном небе. Телескоп помогает изучать орбиты планет.",
            "astronomy",
        )
        det.add_example(
            "Маша пошла в лес. Медведь принёс пирог. Кот мяукает.",
            "children",
        )
        det.add_example(
            "Пирог готовят из муки и яиц. Рецепт требует масло и сахар.",
            "cooking",
        )
        return det

    def test_detect_astronomy(self):
        det = self._make_det()
        assert det.detect("телескоп орбита звезда") == "astronomy"

    def test_detect_children(self):
        det = self._make_det()
        assert det.detect("маша встретила медведя в лесу") == "children"

    def test_detect_cooking(self):
        det = self._make_det()
        assert det.detect("рецепт пирога из муки") == "cooking"

    def test_empty_text_returns_fallback(self):
        det = self._make_det()
        assert det.detect("", fallback="default") == "default"

    def test_unknown_text_may_return_empty(self):
        det = self._make_det()
        # Слова, которых нет в корпусе
        result = det.detect("абвгдеёжзийклмнопрст")
        assert isinstance(result, str)  # может быть "" или любой домен

    def test_detect_top_returns_ranked(self):
        det = self._make_det()
        ranked = det.detect_top("телескоп звезда планета", n=3)
        assert len(ranked) >= 1
        assert ranked[0][0] == "astronomy"
        assert ranked[0][1] > 0

    def test_no_domains_returns_empty(self):
        det = DomainDetector()
        assert det.detect("что-то") == ""
        assert det.detect_top("что-то") == []

    def test_top_words(self):
        det = self._make_det()
        top = det.top_words("children", n=5)
        assert len(top) > 0
        assert all(isinstance(w, str) and isinstance(c, int) for w, c in top)

    def test_domains_list(self):
        det = self._make_det()
        domains = det.domains()
        assert set(domains) == {"astronomy", "children", "cooking"}

    def test_serialization(self):
        det = self._make_det()
        data = det.to_dict()
        det2 = DomainDetector.from_dict(data)
        assert set(det2.domains()) == set(det.domains())
        assert det2.detect("телескоп звезда") == "astronomy"

    def test_build_from_corpus(self):
        corpus = {
            "a1": {"text": "звезда планета орбита", "domain": "astronomy"},
            "c1": {"text": "маша медведь лес",       "domain": "children"},
        }
        det = DomainDetector().build_from_corpus(corpus)
        assert "astronomy" in det.domains()
        assert "children"  in det.domains()

    def test_incremental_add(self):
        det = DomainDetector()
        det.add_example("звезда", "astronomy")
        det.add_example("планета орбита", "astronomy")
        # "звезда" = 1 tok, "планета орбита" = 2 tok → total = 3
        assert det._domain_total["astronomy"] == 3

    def test_cross_terms_excluded(self):
        det = DomainDetector()
        det.add_example("общее слово", "a")
        det.add_example("общее другое", "b")
        cross = det._get_cross_terms()
        assert "общее" in cross

    def test_tokenize_utility(self):
        tokens = _tokenize("Маша пошла в лес за грибами")
        assert "маша" in tokens
        assert "в" not in tokens   # стоп-слово
        assert "за" not in tokens  # стоп-слово


# ══════════════════════════════════════════════════════════════════════════════
# LLMTeachNode
# ══════════════════════════════════════════════════════════════════════════════

class TestLLMTeachNode:

    def _make_node(self, responses=None):
        return LLMTeachNode.mock(
            responses=responses or ["маша пошла в лес за грибами"],
            node_id="test_llm",
            domains={"children"},
            experience=3,
        )

    def test_mock_creation(self):
        node = self._make_node()
        assert node.node_id == "test_llm"
        assert node.experience == 3
        assert "children" in node.domains

    def test_stats_gen_count_zero(self):
        node = self._make_node()
        assert node.stats["gen_count"] == 0

    def test_handle_request_returns_tokens(self):
        node = self._make_node(["маша медведь пирог"])
        req = TeachRequest(question="Кто принёс маше?", domain_hint="children")
        resp = node._handle_teach_request(req)
        assert resp is not None
        assert len(resp.tokens) > 0
        assert resp.source_id == "test_llm"

    def test_call_count_increments(self):
        node = self._make_node(["ответ один", "ответ два"])
        req = TeachRequest(question="Вопрос?")
        node._handle_teach_request(req)
        node._handle_teach_request(req)
        assert node._call_count == 2

    def test_token_count_increments(self):
        node = self._make_node(["слово1 слово2 слово3"])
        req = TeachRequest(question="?")
        node._handle_teach_request(req)
        assert node._token_count == 3

    def test_stats_includes_llm_fields(self):
        node = self._make_node()
        s = node.stats
        assert "llm_calls"  in s
        assert "llm_tokens" in s

    def test_build_prompt_includes_question(self):
        req = TeachRequest(
            question       = "Кто принёс маше?",
            domain_hint    = "children",
            context_tokens = ["маша", "медведь"],
        )
        prompt = _build_prompt(req)
        assert "Кто принёс маше?" in prompt
        assert "children" in prompt
        assert "маша" in prompt or "медведь" in prompt

    def test_parse_response_filters_punctuation(self):
        tokens = _parse_response("Маша, пошла! в лес.")
        assert all(tok.isalpha() for tok in tokens)

    def test_parse_response_max_tokens(self):
        text = "а б в г д е ё ж з и й к л м н о п р с т"
        tokens = _parse_response(text, max_tokens=5)
        assert len(tokens) == 5

    def test_empty_response_returns_none(self):
        node = LLMTeachNode.mock(responses=["   "], node_id="empty_llm")
        req = TeachRequest(question="?")
        resp = node._handle_teach_request(req)
        assert resp is None

    def test_register_in_router(self):
        from core.learning import LearningSystem
        from core.capacity import CapacityBudget

        sys1 = LearningSystem(capacity_budget=CapacityBudget(max_gens=500))
        novice = ModelNode("nov", sys1, domains={"children"}, experience=0)
        llm    = self._make_node()

        router = HeterarchyRouter()
        router.register(novice)
        router.register(llm)
        novice.add_mentor(llm)

        resp = router.route("Кто принёс маше?", novice, domain="children")
        assert resp is not None
        assert resp.source_id == "test_llm"

    def test_domain_detector_integration(self):
        from core.learning import LearningSystem
        from core.capacity import CapacityBudget

        sys1 = LearningSystem(capacity_budget=CapacityBudget(max_gens=500))
        novice = ModelNode("nov2", sys1, domains={"children"}, experience=0)
        det = DomainDetector()
        det.add_example("маша медведь лес", "children")
        det.add_example("звезда орбита телескоп", "astronomy")

        novice.set_domain_detector(det)
        assert novice._detect_domain("маша встретила медведя") == "children"
        assert novice._detect_domain("телескоп видит звезду") == "astronomy"


# ══════════════════════════════════════════════════════════════════════════════
# ActiveTextServer с новыми компонентами
# ══════════════════════════════════════════════════════════════════════════════

class TestActiveTextServerIntegration:

    CORPUS = {
        "c1": "Маша пошла в лес.\nМедведь принёс маше пирог с грибами.",
        "c2": "Заяц нашёл морковку.\nЗаяц принёс морковку маме.",
    }

    def _make_server(self, use_probe_chain: bool = False) -> ActiveTextServer:
        server = ActiveTextServer(use_probe_chain=use_probe_chain)
        for doc_id, text in self.CORPUS.items():
            server.add_document(doc_id, text, domain="children")
        return server

    def test_exploration_policy_applied_on_search(self):
        server = self._make_server()
        # Посетить c1, para 1 несколько раз
        server._policy.record_visit("c1", 1, ["медведь", "принёс"])
        server._policy.record_visit("c1", 1, ["медведь", "принёс"])

        t = LeakyTemplate(
            slots=[TemplateSlot(kind="anchor", words=["принёс"])],
            source="test",
        )
        hits = server.search(t, max_hits=10)
        best = server._policy.select(hits, server._corpus, top_k=1)
        # c2 должен быть предпочтительнее (не посещался)
        if best:
            assert best[0].doc_id == "c2"

    def test_stats_has_probe_fields(self):
        server = self._make_server()
        s = server.stats
        assert "probe_chains" in s
        assert "probe_aborts" in s

    def test_run_loop_with_probe_chain(self):
        from core.learning import LearningSystem
        from core.capacity import CapacityBudget
        from drivers.text_driver import TextDriver

        server = ActiveTextServer(use_probe_chain=True)
        for doc_id, text in self.CORPUS.items():
            server.add_document(doc_id, text, domain="children")

        system = LearningSystem(capacity_budget=CapacityBudget(max_gens=500))
        driver = TextDriver(system)

        # Прогрев
        for tok in driver.produce("Маша пошла в лес за грибами"):
            system.process_token(tok)

        cycles_done = []
        def on_cycle(c, status):
            cycles_done.append(status)

        server.run_active_loop(system, driver, max_cycles=3, on_cycle=on_cycle)
        assert len(cycles_done) == 3

    def test_run_loop_records_visits(self):
        from core.learning import LearningSystem
        from core.capacity import CapacityBudget
        from drivers.text_driver import TextDriver

        server = ActiveTextServer(use_probe_chain=False)
        for doc_id, text in self.CORPUS.items():
            server.add_document(doc_id, text, domain="children")

        system = LearningSystem(capacity_budget=CapacityBudget(max_gens=500))
        driver = TextDriver(system)

        for tok in driver.produce("Маша пошла в лес"):
            system.process_token(tok)

        server.run_active_loop(system, driver, max_cycles=4)
        exp_stats = server._policy.stats
        assert exp_stats["total_visits"] > 0
