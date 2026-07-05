"""Тесты трассы цикла внимания (И1-Т4, З-0028, имена по З-0029).

Инварианты SPEC §1.7 / v2 C.12:
  (1) EVALUATION узла прежде его RETENTION;
  (2) CONTEXT_FIXATION → CONTEXT_DECAY в пределах MAX_LIFETIME
      (нет вечных актуальных контекстов);
  (3) все события — из enum 12 стадий; выключенный трассер не пишет ничего;
  (4) контрольный слой соответствия ниданам тотален: 12 ↔ 12.
"""
from core.core_types import AttentionStage
from core.learning import LearningSystem
from core.attention_trace import AttentionTracer, NIDANA_CORRESPONDENCE
from drivers.text_driver import TextDriver

TEXT_A = "кот сидит на крыше . кот сидит на крыше . пёс спит в будке ."


def make_system():
    tracer = AttentionTracer()
    system = LearningSystem(feature_tolerance=0.3, min_gen_count=2,
                            attention_tracer=tracer)
    return system, tracer


def run_text(system, text, repeats=1):
    driver = TextDriver(driver_id="t", lowercase=True)
    for _ in range(repeats):
        for token in driver.produce(text):
            system.process_token(token)


class TestAttentionTrace:
    def test_trace_written_and_within_enum(self):
        system, tracer = make_system()
        run_text(system, TEXT_A)
        assert len(tracer.events) > 0, "трасса пуста"
        assert all(isinstance(e.stage, AttentionStage) for e in tracer.events), \
            "событие вне enum 12 стадий = красная сборка"

    def test_perception_stages_present(self):
        system, tracer = make_system()
        run_text(system, TEXT_A)
        seen = set(tracer.stages())
        for stage in (AttentionStage.SIGNAL_IN, AttentionStage.DISTINCTION,
                      AttentionStage.CONTEXT_READY, AttentionStage.CONTACT,
                      AttentionStage.EVALUATION, AttentionStage.UNCERTAINTY):
            assert stage in seen, f"стадия {stage.name} не эмитится"

    def test_evaluation_before_retention(self):
        system, tracer = make_system()
        run_text(system, TEXT_A, repeats=4)
        assert tracer.count(AttentionStage.RETENTION) > 0, \
            "RETENTION не наблюдалась — сценарий неинформативен"
        assert tracer.violations_evaluation_before_retention() == []

    def test_fixation_meets_decay(self):
        system, tracer = make_system()
        run_text(system, TEXT_A, repeats=4)
        system.reset_context()
        assert tracer.count(AttentionStage.CONTEXT_FIXATION) > 0, \
            "контекст ни разу не фиксировался"
        assert tracer.count(AttentionStage.CONTEXT_DECAY) > 0, \
            "контекст ни разу не распадался"
        assert tracer.violations_fixation_lifetime() == []

    def test_lifetime_violation_detected(self):
        tracer = AttentionTracer()
        tracer.emit(AttentionStage.CONTEXT_FIXATION, node="g1", tick=0)
        assert tracer.violations_fixation_lifetime(max_lifetime=10, now_tick=100), \
            "вечный контекст обязан ловиться"

    def test_retention_without_evaluation_detected(self):
        tracer = AttentionTracer()
        tracer.emit(AttentionStage.RETENTION, node="g1", tick=1)
        assert tracer.violations_evaluation_before_retention(), \
            "RETENTION без EVALUATION обязана ловиться"

    def test_disabled_by_default_hot_path_clean(self):
        system = LearningSystem()
        driver = TextDriver(driver_id="t", lowercase=True)
        for token in driver.produce(TEXT_A):
            system.process_token(token)
        assert system.attention_trace.enabled is False
        assert len(system.attention_trace.events) == 0, \
            "выключенный трассер не должен писать события"


class TestNidanaControlLayer:
    """Контрольный слой (З-0029): соответствие теории дхарм — проверочное."""

    def test_correspondence_total_and_bijective(self):
        assert set(NIDANA_CORRESPONDENCE) == set(AttentionStage), \
            "каждая стадия цикла обязана иметь ровно одно нидана-соответствие"
        assert len(set(NIDANA_CORRESPONDENCE.values())) == 12, \
            "ниданы не должны дублироваться"

    def test_canonical_chain_order(self):
        """Порядок стадий enum = канонический порядок звеньев цепи."""
        order = list(AttentionStage)
        assert order.index(AttentionStage.EVALUATION) \
            < order.index(AttentionStage.DRIVE) \
            < order.index(AttentionStage.RETENTION), \
            "оценка → влечение → удержание (ведана → танха → упадана)"
        assert order.index(AttentionStage.CONTEXT_FIXATION) \
            < order.index(AttentionStage.CONTEXT_DECAY)
