"""
training/emotion_cycle_demo.py — Полный цикл: 5 историй + эмоциональное состояние.

Запуск:
    py -X utf8 training/emotion_cycle_demo.py
    py -X utf8 training/emotion_cycle_demo.py --stories 10
"""
import sys, os, time
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.app import CoreApplication
from curriculum.debug_session import DebugSession
from drivers.text_driver import TextDriver
from drivers.emotion_driver import EmotionDriver
from drivers.narrator_driver import NarratorDriver, CreativityLevel
from core.curiosity import CharacterCuriosityEngine
from data.gen_base import GenBaseDB

W = "\033[0m"; BD = "\033[1m"; DM = "\033[90m"
GR = "\033[92m"; CY = "\033[96m"; AM = "\033[93m"; MG = "\033[95m"; RD = "\033[91m"


def hdr(t):
    print(f"\n{BD}{CY}{'═'*60}{W}")
    print(f"{BD}{CY}  {t}{W}")
    print(f"{BD}{CY}{'═'*60}{W}")


def show_emotion_state(emotion, label=""):
    """Показать текущее эмоциональное состояние."""
    stats = emotion.stats()
    print(f"\n  {BD}Эмоциональное состояние{(' — ' + label) if label else ''}:{W}")
    print(f"    Записей: {stats['entries']}  Gen: {stats['unique_gens']}  "
          f"Связей: {stats['relationships']}")
    print(f"    {GR}+{stats['positive']}{W}  "
          f"{RD}-{stats['negative']}{W}  "
          f"{DM}~{stats['neutral']}{W}")

    # Топ слов по валентности
    word_vals = []
    for word, vals in emotion._word_emotion.items():
        if len(vals) >= 1:
            avg = sum(vals) / len(vals)
            word_vals.append((word, avg, len(vals)))
    word_vals.sort(key=lambda x: x[1], reverse=True)

    if word_vals:
        print(f"\n    {BD}Слова:{W}")
        for word, v, count in word_vals[:8]:
            color = GR if v > 0.1 else (RD if v < -0.1 else DM)
            bar = "+" * int(abs(v) * 10) if v > 0 else "-" * int(abs(v) * 10)
            print(f"      {word:<15} {color}{v:>6.3f}{W}  (×{count})  {DM}{bar}{W}")

    # Топ связей
    rels = emotion.get_relationships(min_co=2)
    if rels:
        print(f"\n    {BD}Связи:{W}")
        for r in rels[:5]:
            color = GR if r.avg_valence > 0 else (RD if r.avg_valence < 0 else DM)
            print(f"      {r.gen_a[:12]:<13} ↔ {r.gen_b[:12]:<13} "
                  f"co={r.co_count:>2}  {color}v={r.avg_valence:>6.3f}{W}  "
                  f"[{r.emotional_charge}]")


def show_curiosity(engine, emotion):
    """Показать вопросы модели."""
    anchors = engine.find_anchors()
    unfamiliar = engine.find_unfamiliar(anchors)
    queries = engine.generate_queries(anchors, unfamiliar, max_queries=5)

    print(f"\n    {BD}Анкоры:{W} ", end="")
    for a in anchors[:6]:
        v = emotion.get_word_valence(a.word)
        v_str = f"({v:+.2f})" if v != 0 else ""
        print(f"{a.word}{v_str} ", end="")
    print()

    if unfamiliar:
        print(f"    {AM}Unfamiliar:{W} {[a.word for a in unfamiliar[:5]]}")

    if queries:
        print(f"\n    {BD}Запросы:{W}")
        for q in queries[:3]:
            print(f"      • {q['question']}")


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--stories", type=int, default=5)
    parser.add_argument("--db", type=str, default="data/gen_base.db")
    args = parser.parse_args()

    hdr("Полный цикл: истории → эмоции → вопросы")

    # ── Загрузка БД ─────────────────────────────────────────────────
    db_path = Path(args.db)
    if db_path.exists():
        db = GenBaseDB(db_path)
        base_size = 0
        try:
            from core.generalization import GeneralizationBase
            base = GeneralizationBase()
            base_size = db.load(base)
            print(f"\n  {BD}Загружено из БД:{W} {base_size} Gen")
        except:
            print(f"\n  {DM}БД существует, но не удалось загрузить{W}")
    else:
        print(f"\n  {DM}БД не найдена, начинаем с нуля{W}")

    # ── Инициализация ───────────────────────────────────────────────
    app = CoreApplication(config={"mock_teacher": True, "feature_tolerance": 0.15})
    app.startup()
    emotion = EmotionDriver()
    d = TextDriver("demo")

    # Загрузим базу если есть
    if db_path.exists():
        try:
            db.load(app.system.base)
        except:
            pass

    print(f"  {BD}Gen в базе:{W} {app.system.base.size()}")

    # ── 5 историй ───────────────────────────────────────────────────
    stories = [
        # История 1: знакомство (позитив)
        ("маша пошла в лес и встретила нового друга ослика "
         "ослик был весёлый и добрый они подружились",
         "Знакомство"),

        # История 2: помощь (сильный позитив)
        ("ослик упал в яму и не мог выбратся маша помогла ему "
         "вытащить ослик поблагодарил машу и они пошли дальше вместе",
         "Помощь"),

        # История 3: конфликт (негатив)
        ("лиса обманула ослика и забрала у него морковку "
         "ослик расстроился и убежал грустный в лес",
         "Конфликт"),

        # История 4: восстановление (позитив)
        ("маша нашла грустного ослика и угостила его пирогом "
         "ослик обрадовался и снова стал весёлым",
         "Восстановление"),

        # История 5: развилка (смешанные эмоции)
        ("лиса пришла к ослику и сказала что жалеет о своём поступке "
         "ослик подумал и решил простить лису они помирились",
         "Примирение"),
    ]

    for i, (story, title) in enumerate(stories[:args.stories], 1):
        hdr(f"История {i}: {title}")
        print(f"  {DM}«{story[:60]}...»{W}")

        # Обучение
        n_confirmed = 0
        n_refuted = 0
        n_completed = 0
        for tok in d.produce(story):
            result = app.system.process_token(tok)
            outcome = result.outcome.name
            if outcome == "CONFIRMED":
                n_confirmed += 1
            elif outcome == "REFUTED":
                n_refuted += 1
            elif outcome == "COMPLETED":
                n_completed += 1

            # Записать в эмоциональный драйвер
            active_ids = tuple(app.system.engine.context.active_gen_ids())
            token_label = getattr(tok, "label", "") or ""
            emotion.record(active_ids, outcome, token_label)

        app.system.reset_context()

        print(f"  {GR}✓{n_confirmed}{W}  {RD}✗{n_refuted}{W}  "
              f"{AM}★{n_completed}{W}  Gen={app.system.base.size()}")

        # Показать состояние после истории
        show_emotion_state(emotion, f"после «{title}»")

    # ── Финальный анализ ────────────────────────────────────────────
    hdr("Финальный анализ")

    engine = CharacterCuriosityEngine(app.system.base)
    show_curiosity(engine, emotion)

    # NarratorDriver: что модель «расскажет»
    narrator = NarratorDriver(app.system.base, seed=42)
    print(f"\n  {BD}Модель расскажет:{W}")
    for level in [CreativityLevel.RECALL, CreativityLevel.COMPOSE]:
        r = narrator.generate(level, max_words=12)
        if r.text:
            print(f"    [{level.name}] «{r.text}»")

    # Предсказания
    print(f"\n  {BD}Предсказания:{W}")
    test_phrases = [
        "маша и ослик пошли",
        "лиса пришла к",
        "ослик обрадовался",
    ]
    for phrase in test_phrases:
        pred = app.system.engine.context
        print(f"    «{phrase}» → context active: {len(pred.active_gen_ids())} Gen")

    print(f"\n{DM}{'─'*60}{W}")
    print(f"{DM}Цикл завершён. {args.stories} историй обработано.{W}\n")


if __name__ == "__main__":
    main()
