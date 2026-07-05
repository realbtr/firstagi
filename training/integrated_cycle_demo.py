"""
training/integrated_cycle_demo.py — Полный цикл: истории → эмоции → вопросы → разметка.

Запуск:
    py -X utf8 training/integrated_cycle_demo.py
    py -X utf8 training/integrated_cycle_demo.py --stories 3
"""
import sys, os, time
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.app import CoreApplication
from core.curiosity import CharacterCuriosityEngine
from app.runner import BackgroundRunner, RunnerConfig
from drivers.text_driver import TextDriver
from drivers.emotion_driver import EmotionDriver
from drivers.annotation_driver import AnnotationDriver
from drivers.context_broker import ContextBroker, SourceTextRegistry
from data.gen_base import GenBaseDB

W = "\033[0m"; BD = "\033[1m"; DM = "\033[90m"
GR = "\033[92m"; CY = "\033[96m"; AM = "\033[93m"; MG = "\033[95m"; RD = "\033[91m"


def hdr(t):
    print(f"\n{BD}{CY}{'═'*60}{W}")
    print(f"{BD}{CY}  {t}{W}")
    print(f"{BD}{CY}{'═'*60}{W}")


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--stories", type=int, default=3)
    parser.add_argument("--transitions", type=int, default=2000)
    args = parser.parse_args()

    hdr("Интегрированный цикл: истории → эмоции → вопросы → разметка")

    # ── 1. Инициализация ─────────────────────────────────────────────
    app = CoreApplication(config={"mock_teacher": True, "feature_tolerance": 0.15})
    app.startup()

    # Создаём компоненты
    ann = AnnotationDriver()
    emotion = EmotionDriver(annotation_driver=ann)
    curiosity = CharacterCuriosityEngine(app.system.base)

    # Разметка учителя (начальная)
    ann.batch_annotate({
        "помогла": +1, "помог": +1, "обрадовался": +1, "поблагодарил": +1,
        "играли": +0.8, "смеялись": +0.8, "весело": +0.8,
        "обняла": +1, "обнял": +1, "тепло": +0.8, "радостно": +0.8,
        "обманула": -1, "напугал": -1, "расстроился": -0.8,
        "убежал": -0.7, "спрятался": -0.7,
    })

    print(f"  {BD}Разметка учителя:{W} {ann}")

    # Домены с историями
    forest_texts = [
        "маша пошла в лес и встретила медведя медведь обрадовался",
        "маша принесла медведю пирог медведь поел поблагодарил",
        "заяц и лиса играли в прятки в лесу смеялись весело",
        "лиса обманула зайца заяц расстроился убежал",
        "медведь нашёл мёд принёс зайцу заяц поблагодарил",
    ]

    city_texts = [
        "кот сидит на окне кот мяукает кот хочет есть",
        "собака бежит по улице собака громко лает",
        "попугай летает и говорит привет привет",
        "хомяк ест семечки хомяк доволен",
        "черепаха медленно идёт по парку черепаха спокойна",
    ]

    # ── 2. Запуск BackgroundRunner ───────────────────────────────────
    hdr("Фаза 1: Обучение с эмоциями и вопросами")

    curiosity_log = []

    def on_curiosity(data):
        curiosity_log.append(data)
        text_prev = data["text_preview"]
        anchors = data["anchors"]
        unfamiliar = data["unfamiliar"]
        queries = data["queries"]
        print(f"\n  {AM}❓ После «{text_prev}...»{W}")
        print(f"    Анкоры: {anchors[:5]}")
        if unfamiliar:
            print(f"    {MG}Unfamiliar:{W} {unfamiliar[:3]}")
        for q in queries[:2]:
            print(f"    → {q['question']}")

    def on_log(snap):
        t = snap["transitions"]
        bs = snap["base_size"]
        dom = snap.get("current_domain", "?")
        emo_stats = emotion.stats()
        print(f"  {DM}{t:>5} tok  base={CY}{bs}{W}  "
              f"dom={dom}  "
              f"emo={emo_stats['entries']} "
              f"({GR}+{emo_stats['positive']}{W} "
              f"{RD}-{emo_stats['negative']}{W})")

    runner = BackgroundRunner(
        system=app.system,
        domains=[
            ("forest", forest_texts),
            ("city", city_texts),
        ],
        config=RunnerConfig(
            switch_domain_every=500,
            sleep_every=300,
            log_every=200,
        ),
        emotion_driver=emotion,
        annotation_driver=ann,
        curiosity_engine=curiosity,
        on_log=on_log,
        on_curiosity=on_curiosity,
    )

    print(f"\n  {BD}Запуск:{W} {args.transitions} переходов, 2 домена\n")
    stats = runner.run(max_transitions=args.transitions)

    # ── 3. Анализ после обучения ─────────────────────────────────────
    hdr("Фаза 2: Анализ")

    emo_stats = emotion.stats()
    print(f"  {BD}Эмоциональный драйвер:{W}")
    print(f"    Записей: {emo_stats['entries']}")
    print(f"    Gen: {emo_stats['unique_gens']}")
    print(f"    Связей: {emo_stats['relationships']}")
    print(f"    {GR}+{emo_stats['positive']}{W}  "
          f"{RD}-{emo_stats['negative']}{W}  "
          f"{DM}~{emo_stats['neutral']}{W}")

    # Топ эмоциональных слов
    print(f"\n  {BD}Эмоциональные слова:{W}")
    word_vals = []
    for w, vals in emotion._word_emotion.items():
        if len(vals) >= 2:
            avg = sum(vals) / len(vals)
            word_vals.append((w, avg, len(vals)))
    word_vals.sort(key=lambda x: x[1], reverse=True)
    for w, v, c in word_vals[:10]:
        color = GR if v > 0.1 else (RD if v < -0.1 else DM)
        has_ann = ann.has_annotation(w)
        src = f"{AM}[ann]{W}" if has_ann else ""
        print(f"    {w:<15} {color}{v:>6.3f}{W}  (x{c})  {src}")

    # Вопросы модели
    print(f"\n  {BD}Вопросы модели (последние):{W}")
    for entry in curiosity_log[-3:]:
        print(f"    После «{entry['text_preview'][:30]}...»:")
        for q in entry["queries"][:2]:
            print(f"      → {q['question']}")

    # ── 4. Итог ─────────────────────────────────────────────────────
    hdr("Итог")
    print(f"  {BD}BackgroundRunner:{W} {stats.transitions} переходов, "
          f"{stats.texts_processed} текстов")
    print(f"  {BD}EmotionDriver:{W} {emotion}")
    print(f"  {BD}AnnotationDriver:{W} {ann}")
    print(f"  {BD}CuriosityEngine:{W} {curiosity}")
    print(f"  {BD}Вопросов сгенерировано:{W} {len(curiosity_log)}")

    print(f"\n  {BD}Поток данных:{W}")
    print(f"    Text → process_token() → EmotionDriver.record()")
    print(f"    → после текста → CuriosityEngine.generate_queries()")
    print(f"    → on_curiosity → вопросы к LLM → TEACH → новые тексты")

    print(f"\n{DM}{'─'*60}{W}")
    print(f"{DM}Интеграция завершена.{W}\n")


if __name__ == "__main__":
    main()
