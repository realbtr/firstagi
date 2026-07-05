"""Демо: учительская разметка → зеркальные нейроны → интуиция."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.app import CoreApplication
from drivers.text_driver import TextDriver
from drivers.emotion_driver import EmotionDriver
from drivers.annotation_driver import AnnotationDriver

W = "\033[0m"; BD = "\033[1m"; DM = "\033[90m"
GR = "\033[92m"; RD = "\033[91m"; AM = "\033[93m"; MG = "\033[95m"

app = CoreApplication(config={"mock_teacher": True, "feature_tolerance": 0.15})
app.startup()

# ── 1. Учитель даёт разметку ────────────────────────────────────────
ann = AnnotationDriver()
emotion = EmotionDriver(annotation_driver=ann)

print(f"{BD}Фаза 1: Учитель даёт разметку{W}\n")

teacher_annotations = {
    # Позитивные
    "помогла": +1.0, "помог": +1.0, "подружились": +1.0,
    "обрадовался": +1.0, "поблагодарил": +1.0, "угостил": +1.0,
    "играли": +0.8, "смеялись": +0.8, "весело": +0.8,
    "простил": +0.7, "помирились": +0.7,

    # Негативные
    "обидела": -1.0, "обманула": -1.0, "напугал": -1.0,
    "расстроился": -0.8, "убежал": -0.7, "გрустный": -0.8,
    "потерял": -0.5, "упал": -0.5,

    # Нейтральные (автоматически)
    "пошла": 0.0, "встретила": 0.0, "сказала": 0.0,
}

ann.batch_annotate(teacher_annotations)
print(f"  {ann}")

# Показать аннотации
print(f"\n  {BD}Позитивные:{W} {ann.positive_words()}")
print(f"  {BD}Негативные:{W} {ann.negative_words()}")

# ── 2. Обучение с учётом разметки ──────────────────────────────────
print(f"\n{BD}Фаза 2: Обучение (разметка влияет на валентность){W}\n")

stories = [
    "маша помогла зайцу заяц обрадовался поблагодарил",
    "лиса обманула зайца заяц расстроился убежал",
    "маша и ослик играли вместе весело смеялись",
    "лиса обманула кота кот расстроился ушёл",
    "маша помогла ослику ослик обрадовался",
    "заяц и лиса помирились все обрадовались",
]

d = TextDriver("demo")
for story in stories:
    for tok in d.produce(story):
        result = app.system.process_token(tok)
        active = tuple(app.system.engine.context.active_gen_ids())
        emotion.record(active, result.outcome.name, getattr(tok, "label", "") or "")
    app.system.reset_context()

# ── 3. Сравнение: с разметкой vs без ───────────────────────────────
print(f"{BD}Фаза 3: Сравнение{W}\n")

print(f"  {BD}Валентность С разметкой учителя:{W}")
test_words = ["помогла", "обидела", "расстроился", "обрадовался",
              "пошла", "играли", "обманула", "простил"]
for word in test_words:
    v = emotion.get_word_valence(word)
    color = GR if v > 0.1 else (RD if v < -0.1 else DM)
    bar = "+" * int(abs(v) * 10) if v > 0 else "-" * int(abs(v) * 10)
    print(f"    {word:<15} {color}{v:>6.3f}{W}  {DM}{bar}{W}")

# ── 4. Интуиция с учётом разметки ──────────────────────────────────
print(f"\n{BD}Фаза 4: Интуиция (прогноз с учётом разметки){W}\n")

for action in ["обманула", "помогла", "напугал", "простил"]:
    r = emotion.predict_outcome(action)
    v = emotion.get_word_valence(action)
    color = GR if v > 0.1 else (RD if v < -0.1 else DM)
    print(f"  {BD}«{action}»{W}  v={color}{v:+.3f}{W}")
    for c in r["likely_consequences"][:2]:
        cv = emotion.get_word_valence(c["word"])
        ccolor = GR if cv > 0.1 else (RD if cv < -0.1 else DM)
        print(f"    → {c['word']:<15} p={c['probability']:.2f}  "
              f"{ccolor}v={cv:+.3f}{W}")
    print()

# ── 5. Внутренний голос ────────────────────────────────────────────
print(f"{BD}Фаза 5: Внутренний голос (рекомендации модели){W}\n")

for word in ["лиса", "маша", "заяц", "волк", "ослик"]:
    r = emotion.intuition_report(word)
    color = GR if r["valence"] > 0.1 else (RD if r["valence"] < -0.1 else DM)
    print(f"  {BD}«{word}»{W}  v={color}{r['valence']:+.3f}{W}")
    print(f"    {r['recommendation']}")
    if r["sequence"]:
        top = r["sequence"][0]
        print(f"    после «{word}» → «{top['next']}» (p={top['probability']:.2f})")
    print()

# ── Итог ────────────────────────────────────────────────────────────
print(f"{BD}{'='*60}{W}")
print(f"{BD}  ИТОГ{W}")
print(f"{BD}{'='*60}{W}")
print(f"  {BD}Учитель:{W} {ann}")
print(f"  {BD}Эмоции:{W} {emotion}")
print(f"\n  {BD}Принцип:{W}")
print(f"    Level 0: Учитель размечает «помогла=+1, обидела=-1»")
print(f"    Level 1: Модель видит: «обидела→расстроился→убежал»")
print(f"    Level 2: Модель предсказывает: «обидела→расстроится»")
print(f"    Level 3: Модель сама говорит: «обидела — плохо»")
print(f"\n{DM}{'─'*60}{W}")
print(f"{DM}Зеркальная нейронная сеть через костыль работает.{W}\n")
