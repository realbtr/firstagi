"""
training/llm_cycle_demo.py — Полный LLM-цикл: вопросы → LLM → TEACH → обучение.

Запуск:
    py -X utf8 training/llm_cycle_demo.py
    py -X utf8 training/llm_cycle_demo.py --api-key sk-ant-...  (реальный LLM)
"""
import sys, os, json
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.app import CoreApplication
from core.curiosity import CharacterCuriosityEngine
from core.llm_broker import MockLLMClient, LLMTeacherWorker, LLMPromptBuilder
from app.runner import BackgroundRunner, RunnerConfig
from drivers.text_driver import TextDriver
from drivers.emotion_driver import EmotionDriver
from drivers.annotation_driver import AnnotationDriver

W = "\033[0m"; BD = "\033[1m"; DM = "\033[90m"
GR = "\033[92m"; CY = "\033[96m"; AM = "\033[93m"; MG = "\033[95m"; RD = "\033[91m"


def hdr(t):
    print(f"\n{BD}{CY}{'═'*60}{W}")
    print(f"{BD}{CY}  {t}{W}")
    print(f"{BD}{CY}{'═'*60}{W}")


# ── Mock LLM: возвращает релевантные тексты ─────────────────────────
MOCK_RESPONSES = [
    '{"action":"TEACH","text":"маша и ослик пошли в лес нашли грибы и ягоды","amount":0.0,"reason":"обучение новому паттерну"}',
    '{"action":"TEACH","text":"лиса поверила зайцу и они снова подружились","amount":0.0,"reason":"восстановление отношений"}',
    '{"action":"TEACH","text":"медведь угостил всех пирогом все обрадовались","amount":0.0,"reason":"позитивное взаимодействие"}',
    '{"action":"TEACH","text":"кот нашёл ключ откры дверь вошёл внутрь","amount":0.0,"reason":"новый персонаж"}',
    '{"action":"TEACH","text":"собака помогла коту забраться на дерево кот был благодарен","amount":0.0,"reason":"помощь между видами"}',
    '{"action":"REWARD","text":"","amount":5.0,"reason":"модель показывает прогресс"}',
    '{"action":"TEACH","text":"заяц и волк пошли гулять вместе все удивились","amount":0.0,"reason":"неожиданная дружба"}',
    '{"action":"TEACH","text":"попугай рассказал историю как он летал над морем","amount":0.0,"reason":"новый домен"}',
]


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-key", default="", help="Anthropic API key (пусто = mock)")
    parser.add_argument("--transitions", type=int, default=1000)
    args = parser.parse_args()

    hdr("LLM-цикл: вопросы → LLM → TEACH → обучение")

    # ── 1. Инициализация ─────────────────────────────────────────────
    app = CoreApplication(config={"mock_teacher": True, "feature_tolerance": 0.15})
    app.startup()

    ann = AnnotationDriver()
    ann.batch_annotate({
        "помогла": +1, "помог": +1, "обрадовался": +1, "поблагодарил": +1,
        "играли": +0.8, "смеялись": +0.8, "весело": +0.8,
        "обняла": +1, "обнял": +1, "тепло": +0.8,
        "обманула": -1, "напугал": -1, "расстроился": -0.8,
    })
    emotion = EmotionDriver(annotation_driver=ann)
    curiosity = CharacterCuriosityEngine(app.system.base)

    # LLM-клиент
    if args.api_key:
        from core.llm_broker import AnthropicClient
        llm_client = AnthropicClient(
            api_key=args.api_key,
            model="claude-haiku-4-5-20251001",
            max_tokens=128,
        )
        print(f"  {BD}LLM:{W} {GR}claude-haiku{W} (реальный)")
    else:
        llm_client = MockLLMClient(responses=MOCK_RESPONSES)
        print(f"  {BD}LLM:{W} {DM}mock (8 ответов){W}")

    llm_worker = LLMTeacherWorker(
        system=app.system,
        llm_client=llm_client,
        min_interval=0,
    )

    # ── 2. Callbacks ─────────────────────────────────────────────────
    llm_log = []

    def on_curiosity(data):
        text_prev = data["text_preview"]
        anchors = data["anchors"]
        unfamiliar = data["unfamiliar"]
        queries = data["queries"]
        print(f"\n  {AM}❓ Вопросы после «{text_prev[:30]}...»{W}")
        print(f"    Анкоры: {anchors[:5]}")
        if unfamiliar:
            print(f"    {MG}Unfamiliar:{W} {unfamiliar[:3]}")
        for q in queries[:2]:
            print(f"    → {q['question']}")

    def on_llm_teach(text):
        llm_log.append(text)
        print(f"\n  {CY}📚 LLM → TEACH:{W} «{text}»")
        emo = emotion.stats()
        print(f"    {DM}Эмоции: +{emo['positive']} -{emo['negative']}  "
              f"Gen={app.system.base.size()}{W}")

    def on_log(snap):
        t = snap["transitions"]
        bs = snap["base_size"]
        dom = snap.get("current_domain", "?")
        print(f"  {DM}{t:>5} tok  base={CY}{bs}{W}  dom={dom}{W}")

    # ── 3. Запуск BackgroundRunner ───────────────────────────────────
    hdr("Фаза 1: Обучение с LLM-циклом")

    forest_texts = [
        "маша пошла в лес и встретила медведя медведь обрадовался",
        "заяц и лиса играли в прятки в лесу смеялись весело",
        "лиса обманула зайца заяц расстроился убежал",
        "медведь нашёл мёд принёс зайцу заяц поблагодарил",
    ]

    runner = BackgroundRunner(
        system=app.system,
        domains=[("forest", forest_texts)],
        config=RunnerConfig(
            switch_domain_every=0,
            sleep_every=500,
            log_every=100,
        ),
        emotion_driver=emotion,
        annotation_driver=ann,
        curiosity_engine=curiosity,
        llm_worker=llm_worker,
        on_log=on_log,
        on_curiosity=on_curiosity,
        on_llm_teach=on_llm_teach,
    )

    print(f"\n  {BD}Запуск:{W} {args.transitions} переходов + LLM-цикл\n")
    stats = runner.run(max_transitions=args.transitions)

    # ── 4. Анализ ────────────────────────────────────────────────────
    hdr("Фаза 2: Анализ")

    emo_stats = emotion.stats()
    print(f"  {BD}EmotionDriver:{W} {emotion}")
    print(f"  {BD}LLM-вызовов:{W} {runner._llm_calls_total}")
    print(f"  {BD}Текстов от LLM:{W} {runner._llm_texts_fed}")

    if llm_log:
        print(f"\n  {BD}Тексты от LLM:{W}")
        for i, text in enumerate(llm_log, 1):
            print(f"    {i}. «{text}»")

    # Эмоциональные слова
    print(f"\n  {BD}Эмоциональные слова:{W}")
    word_vals = []
    for w, vals in emotion._word_emotion.items():
        if len(vals) >= 1:
            avg = sum(vals) / len(vals)
            word_vals.append((w, avg, len(vals)))
    word_vals.sort(key=lambda x: x[1], reverse=True)
    for w, v, c in word_vals[:8]:
        color = GR if v > 0.1 else (RD if v < -0.1 else DM)
        print(f"    {w:<15} {color}{v:>6.3f}{W}  (x{c})")

    # Вопросы модели
    engine = CharacterCuriosityEngine(app.system.base)
    anchors = engine.find_anchors()
    unfamiliar = engine.find_unfamiliar(anchors)
    queries = engine.generate_queries(anchors, unfamiliar, max_queries=5)

    print(f"\n  {BD}Текущие вопросы модели:{W}")
    for q in queries[:3]:
        print(f"    → {q['question']}")

    # ── 5. Итог ─────────────────────────────────────────────────────
    hdr("Итог")
    print(f"  {BD}BackgroundRunner:{W} {stats.transitions} переходов")
    print(f"  {BD}LLM-цикл:{W} {runner._llm_calls_total} вызовов, "
          f"{runner._llm_texts_fed} текстов загружено")
    print(f"  {BD}Эмоции:{W} +{emo_stats['positive']} -{emo_stats['negative']}")
    print(f"  {BD}Генерация:{W} {len(queries)} вопросов")

    print(f"\n  {BD}Полный цикл:{W}")
    print(f"    Text → process_token() → EmotionDriver.record()")
    print(f"    → CuriosityEngine.generate_queries()")
    print(f"    → LLMTeacherWorker → LLM → TEACH")
    print(f"    → текст загружен → process_token() → модель обучена")
    print(f"    → новые вопросы → повтор")

    print(f"\n{DM}{'─'*60}{W}")
    print(f"{DM}LLM-цикл замкнут.{W}\n")


if __name__ == "__main__":
    main()
