"""
training/emotion_demo.py — Демо: эмоциональный драйвер + любопытство.

Показывает:
  1. Как EmotionDriver записывает контексты при обучении
  2. Как эмоциональная окраска влияет на генерацию вопросов
  3. Как relationships между персонажами формируются

Запуск:
    py -X utf8 training/emotion_demo.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.app import CoreApplication
from curriculum.debug_session import DebugSession
from drivers.text_driver import TextDriver
from drivers.emotion_driver import EmotionDriver
from core.curiosity import CharacterCuriosityEngine

W = "\033[0m"; BD = "\033[1m"; DM = "\033[90m"
GR = "\033[92m"; CY = "\033[96m"; AM = "\033[93m"; MG = "\033[95m"; RD = "\033[91m"

def hdr(t):
    print(f"\n{BD}{CY}{'═'*60}{W}")
    print(f"{BD}{CY}  {t}{W}")
    print(f"{BD}{CY}{'═'*60}{W}\n")


# ══════════════════════════════════════════════════════════════════════
# Корпус с эмоциональными развилками
# ══════════════════════════════════════════════════════════════════════

# Позитивные истории (хорошие отношения)
POSITIVE_STORIES = [
    "маша пошла в лес и встретила медведя медведь обрадовался поздоровались",
    "маша принесла медведю пирог медведь поел поблагодарил маша обрадовалась",
    "заяц и лиса играли в прятки в лесу смеялись весело было",
    "медведь нашёл мёд принёс зайцу заяц поел поблагодарил медведь доволен",
    "маша и ослик пошли гулять вместе нашли ягоды поели вместе обрадовались",
]

# Негативные истории (конфликты)
NEGATIVE_STORIES = [
    "маша обидела зайцу зайца расстроился убежал в лес",
    "лиса обманула зайца заяц потерял морковку грустный",
    "волк напугал всех зверей звери убежали испугались",
    "ослик упал в яму ему было больно плакал",
]

# Нейтральные истории
NEUTRAL_STORIES = [
    "утром встал умылся позавтракал пошёл на работу",
    "вечером кот сидит на окне смотрит на улицу",
    "два друга встретились поговорили разошлись",
]

ALL_STORIES = POSITIVE_STORIES + NEGATIVE_STORIES + NEUTRAL_STORIES


def main():
    hdr("Эмоциональный драйвер + любопытство")

    # ── 1. Инициализация ─────────────────────────────────────────────
    app = CoreApplication(config={"mock_teacher": True, "feature_tolerance": 0.15})
    app.startup()
    emotion = EmotionDriver()
    d = TextDriver("demo")

    print(f"  {BD}Корпус:{W} {len(ALL_STORIES)} историй "
          f"({len(POSITIVE_STORIES)} позитивных, "
          f"{len(NEGATIVE_STORIES)} негативных, "
          f"{len(NEUTRAL_STORIES)} нейтральных)")

    # ── 2. Обучение с записью эмоций ────────────────────────────────
    hdr("Фаза 1: Обучение с записью эмоций")

    for i, story in enumerate(ALL_STORIES):
        # Определяем тип истории
        if story in POSITIVE_STORIES:
            story_type = f"{GR}+{W}"
        elif story in NEGATIVE_STORIES:
            story_type = f"{RD}-{W}"
        else:
            story_type = f"{DM}~{W}"

        print(f"  {story_type} {story[:50]}...")

        for tok in d.produce(story):
            result = app.system.process_token(tok)
            outcome = result.outcome.name

            # Записать в эмоциональный драйвер
            active_ids = tuple(app.system.engine.context.active_gen_ids())
            token_label = getattr(tok, "label", "") or ""
            emotion.record(active_ids, outcome, token_label)

        app.system.reset_context()

    print(f"\n  {BD}Эмоциональный драйвер:{W} {emotion}")

    # ── 3. Анализ эмоционального контекста ───────────────────────────
    hdr("Фаза 2: Анализ эмоционального контекста")

    # Валентность слов
    print(f"  {BD}Эмоциональная окраска слов:{W}")
    words_to_check = ["маша", "медведь", "заяц", "лиса", "волк", "ослик",
                      "обрадовался", "испугался", "грустный", "весело",
                      "пирог", "мёд", "морковку"]
    for word in words_to_check:
        v = emotion.get_word_valence(word)
        if v != 0:
            color = GR if v > 0 else (RD if v < 0 else DM)
            bar = "+" * int(abs(v) * 10) if v > 0 else "-" * int(abs(v) * 10)
            print(f"    {word:<15} {color}{v:>6.3f}  {DM}{bar}{W}")

    # Relationships
    print(f"\n  {BD}Эмоциональные связи:{W}")
    rels = emotion.get_relationships(min_co=3)
    for r in rels[:10]:
        color = GR if r.avg_valence > 0 else (RD if r.avg_valence < 0 else DM)
        print(f"    {r.gen_a[:15]:<16} ↔ {r.gen_b[:15]:<16} "
              f"co={r.co_count:>3}  "
              f"{color}v={r.avg_valence:>6.3f}{W}  "
              f"[{r.emotional_charge}]")

    # Эмоциональные развилки
    print(f"\n  {BD}Эмоциональные развилки:{W}")
    pairs = emotion.unfamiliar_pairs()
    for p in pairs[:5]:
        print(f"    {p['gen_a'][:15]}({p['valence_a']:+.3f}) ↔ "
              f"{p['gen_b'][:15]}({p['valence_b']:+.3f})  "
              f"gap={p['gap']:.3f}  co={p['co_count']}")

    # ── 4. Вопросы на основе эмоций ─────────────────────────────────
    hdr("Фаза 3: Вопросы на основе эмоций")

    suggestions = emotion.suggest_stories(max_suggestions=8)
    for i, s in enumerate(suggestions, 1):
        print(f"  {BD}{i}.{W} [{s['type']}] {s['question']}")

    # ── 5. Интеграция с CharacterCuriosityEngine ─────────────────────
    hdr("Фаза 4: Loveopytство + эмоции")

    engine = CharacterCuriosityEngine(app.system.base)
    anchors = engine.find_anchors()
    unfamiliar = engine.find_unfamiliar(anchors)
    queries = engine.generate_queries(anchors, unfamiliar, max_queries=8)

    print(f"  {BD}Анкоры:{W} {[a.word for a in anchors[:8]]}")
    print(f"  {BD}Unfamiliar:{W} {[a.word for a in unfamiliar[:5]]}")
    print(f"\n  {BD}Запросы с учётом эмоций:{W}")
    for q in queries[:5]:
        target = q.get("target", "")
        v = emotion.get_word_valence(target.split()[0] if target else "")
        v_str = f"  v={v:+.3f}" if v != 0 else ""
        print(f"    {q['question']}{DM}{v_str}{W}")

    # ── Итог ────────────────────────────────────────────────────────
    hdr("Итог")
    stats = emotion.stats()
    print(f"  Записей:       {stats['entries']}")
    print(f"  Gen:           {stats['unique_gens']}")
    print(f"  Слов:          {stats['unique_words']}")
    print(f"  Связей:        {stats['relationships']}")
    print(f"  Позитивных:    {stats['positive']}")
    print(f"  Негативных:    {stats['negative']}")
    print(f"  Нейтральных:   {stats['neutral']}")
    print(f"\n{DM}{'─'*60}{W}")
    print(f"{DM}Эмоциональный драйвер работает. Контексты записаны.{W}\n")


if __name__ == "__main__":
    main()
