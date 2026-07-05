"""Тесты нидана-трассы C.12 (И1-Т4, З-0028): маркировка стадий + CI-ассерты.

Инварианты SPEC §1.7 / v2 C.12:
  (1) Ведана узла прежде его Упаданы;
  (2) Джати→Джара-марана в пределах MAX_LIFETIME (нет вечных контекстов);
  (3) все события — из enum 12 нидан; выключенный трассер не пишет ничего.
"""
from core.core_types import Nidana
from core.learning import LearningSystem
from core.nidana import NidanaTracer
from drivers.text_driver import TextDriver

TEXT_A = "кот сидит на крыше . кот сидит на крыше . пёс спит в будке ."


def make_system():
    tracer = NidanaTracer()
    system = LearningSystem(feature_tolerance=0.3, min_gen_count=2,
                            nidana_tracer=tracer)
    return system, tracer


def run_text(system, text, repeats=1):
    driver = TextDriver(driver_id="t", lowercase=True)
    for _ in range(repeats):
        for token in driver.produce(text):
            system.process_token(token)


class TestNidanaTrace:
    def test_trace_written_and_within_enum(self):
        system, tracer = make_system()
        run_text(system, TEXT_A)
        assert len(tracer.events) > 0, "трасса пуста"
        assert all(isinstance(e.stage, Nidana) for e in tracer.events), \
            "событие вне enum 12 нидан = красная сборка"

    def test_perception_stages_present(self):
        system, tracer = make_system()
        run_text(system, TEXT_A)
        seen = set(tracer.stages())
        for stage in (Nidana.VIJNANA, Nidana.NAMARUPA, Nidana.AYATANA,
                      Nidana.SPARSHA, Nidana.VEDANA, Nidana.AVIDYA):
            assert stage in seen, f"стадия {stage.name} не эмитится"

    def test_vedana_before_upadana(self):
        system, tracer = make_system()
        run_text(system, TEXT_A, repeats=4)
        assert tracer.count(Nidana.UPADANA) > 0, \
            "Упадана не наблюдалась — сценарий неинформативен"
        assert tracer.violations_vedana_before_upadana() == []

    def test_jati_meets_jara_marana(self):
        system, tracer = make_system()
        run_text(system, TEXT_A, repeats=4)
        system.reset_context()
        assert tracer.count(Nidana.JATI) > 0, "контекст ни разу не фиксировался"
        assert tracer.count(Nidana.JARA_MARANA) > 0, "контекст ни разу не распадался"
        assert tracer.violations_jati_lifetime() == []

    def test_lifetime_violation_detected(self):
        tracer = NidanaTracer()
        tracer.emit(Nidana.JATI, node="g1", tick=0)
        assert tracer.violations_jati_lifetime(max_lifetime=10, now_tick=100), \
            "вечный контекст обязан ловиться"

    def test_upadana_without_vedana_detected(self):
        tracer = NidanaTracer()
        tracer.emit(Nidana.UPADANA, node="g1", tick=1)
        assert tracer.violations_vedana_before_upadana(), \
            "Упадана без Веданы обязана ловиться"

    def test_disabled_by_default_hot_path_clean(self):
        system = LearningSystem()
        driver = TextDriver(driver_id="t", lowercase=True)
        for token in driver.produce(TEXT_A):
            system.process_token(token)
        assert system.nidana.enabled is False
        assert len(system.nidana.events) == 0, \
            "выключенный трассер не должен писать события"
