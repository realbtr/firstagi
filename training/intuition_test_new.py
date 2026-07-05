"""Демо: проверка интуиции на НОВОЙ истории."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.app import CoreApplication
from drivers.text_driver import TextDriver
from drivers.emotion_driver import EmotionDriver
from drivers.annotation_driver import AnnotationDriver
from drivers.narrator_driver import NarratorDriver, CreativityLevel

W = "\033[0m"; BD = "\033[1m"; DM = "\033[90m"
GR = "\033[92m"; RD = "\033[91m"; AM = "\033[93m"; MG = "\033[95m"

app = CoreApplication(config={"mock_teacher": True, "feature_tolerance": 0.15})
app.startup()

ann = AnnotationDriver()
emotion = EmotionDriver(annotation_driver=ann)
d = TextDriver("demo")

# ── 1. Обучение на знакомых историях ────────────────────────────────
print(f"{BD}Фаза 1: Обучение на 8 знакомых историях{W}\n")

train_stories = [
    ("маша помогла зайцу заяц обрадовался поблагодарил", "+"),
    ("лиса обманула зайца заяц расстроился убежал", "-"),
    ("маша и ослик играли вместе весело смеялись", "+"),
    ("лиса обманула кота кот расстроился ушёл", "-"),
    ("медведь помог лисе лиса обрадовалась поблагодарила", "+"),
    ("волк напугал зайца заяц испугался спрятался", "-"),
    ("маша угостила ослика ослик обрадовался", "+"),
    ("лиса обманула медведя медведь расстроился", "-"),
]

# Разметка учителя
teacher_map = {
    "помогла": +1, "помог": +1, "угостила": +1, "угостил": +1,
    "обрадовался": +1, "поблагодарил": +1, "поблагодарила": +1,
    "играли": +0.8, "смеялись": +0.8, "весело": +0.8,
    "обманула": -1, "напугал": -1,
    "расстроился": -0.8, "испугался": -0.8,
    "убежал": -0.7, "спрятался": -0.7, "ушёл": -0.5,
}
ann.batch_annotate(teacher_map)

for story, tag in train_stories:
    color = GR if tag == "+" else RD
    print(f"  {color}{tag}{W} {story[:55]}...")
    for tok in d.produce(story):
        result = app.system.process_token(tok)
        active = tuple(app.system.engine.context.active_gen_ids())
        emotion.record(active, result.outcome.name, getattr(tok, "label", "") or "")
    app.system.reset_context()

print(f"\n  {BD}Обучено:{W} {emotion}")

# ── 2. Предсказания ДО новой истории ───────────────────────────────
print(f"\n{BD}Фаза 2: Предсказания ДО новой истории{W}\n")

for action in ["обманула", "помогла", "напугал", "обняла", "украл"]:
    r = emotion.predict_outcome(action)
    v = emotion.get_word_valence(action)
    color = GR if v > 0.1 else (RD if v < -0.1 else DM)
    print(f"  {BD}«{action}»{W}  v={color}{v:+.3f}{W}", end="")
    if r["likely_consequences"]:
        top = r["likely_consequences"][0]
        cv = emotion.get_word_valence(top["word"])
        ccolor = GR if cv > 0.1 else (RD if cv < -0.1 else DM)
        print(f"  → «{top['word']}» {ccolor}v={cv:+.3f}{W}", end="")
    print()

# ── 3. НОВАЯ история (модель не видела) ─────────────────────────────
new_story = "маша обняла зайца зайц стало тепло и радостно он улыбнулся"

print(f"\n{BD}Фаза 3: НОВАЯ история (модель не видела){W}")
print(f"  {MG}«{new_story}»{W}\n")

# Что модель ОЖИДАЕТ ДО обработки
print(f"  {BD}ДО обработки (ожидания):{W}")
for word in ["обняла", "зайца", "тепло", "радостно", "улыбнулся"]:
    v = emotion.get_word_valence(word)
    color = GR if v > 0.1 else (RD if v < -0.1 else DM)
    pred = emotion.predict_outcome(word)
    consequence = pred["likely_consequences"][0]["word"] if pred["likely_consequences"] else "?"
    print(f"    «{word}»  v={color}{v:+.3f}{W}  → ожидание: «{consequence}»")

# Обработка новой истории
n_c = n_r = n_co = 0
for tok in d.produce(new_story):
    result = app.system.process_token(tok)
    o = result.outcome.name
    if o == "CONFIRMED": n_c += 1
    elif o == "REFUTED": n_r += 1
    elif o == "COMPLETED": n_co += 1
    active = tuple(app.system.engine.context.active_gen_ids())
    emotion.record(active, o, getattr(tok, "label", "") or "")
app.system.reset_context()

print(f"\n  {BD}Результат:{W} {GR}✓{n_c}{W}  {RD}✗{n_r}{W}  {AM}★{n_co}{W}")

# Что модель ЗНАЕТ ПОСЛЕ обработки
print(f"\n  {BD}ПОСЛЕ обработки (знание):{W}")
for word in ["обняла", "зайца", "тепло", "радостно", "улыбнулся"]:
    v = emotion.get_word_valence(word)
    color = GR if v > 0.1 else (RD if v < -0.1 else DM)
    pred = emotion.predict_outcome(word)
    consequence = pred["likely_consequences"][0]["word"] if pred["likely_consequences"] else "?"
    print(f"    «{word}»  v={color}{v:+.3f}{W}  → прогноз: «{consequence}»")

# ── 4. Проверка: интуиция на ещё одной новой истории ────────────────
print(f"\n{BD}Фаза 4: Проверка — ещё одна новая история{W}")

test_story = "волк обнял зайца зайц стало тепло он перестал бояться"
print(f"  {MG}«{test_story}»{W}\n")

print(f"  {BD}Предсказание ДО обработки:{W}")
for word in ["обнял", "зайца", "тепло", "перестал", "бояться"]:
    v = emotion.get_word_valence(word)
    color = GR if v > 0.1 else (RD if v < -0.1 else DM)
    print(f"    «{word}»  v={color}{v:+.3f}{W}")

# Обработка
n_c2 = n_r2 = n_co2 = 0
for tok in d.produce(test_story):
    result = app.system.process_token(tok)
    o = result.outcome.name
    if o == "CONFIRMED": n_c2 += 1
    elif o == "REFUTED": n_r2 += 1
    elif o == "COMPLETED": n_co2 += 1
    active = tuple(app.system.engine.context.active_gen_ids())
    emotion.record(active, o, getattr(tok, "label", "") or "")
app.system.reset_context()

print(f"\n  {BD}Результат:{W} {GR}✓{n_c2}{W}  {RD}✗{n_r2}{W}  {AM}★{n_co2}{W}")

# ── 5. Итоговая интуиция ───────────────────────────────────────────
print(f"\n{BD}Фаза 5: Итоговая интуиция{W}\n")

for word in ["обняла", "обнял", "обманула", "помогла", "напугал"]:
    report = emotion.intuition_report(word)
    color = GR if report["valence"] > 0.1 else (RD if report["valence"] < -0.1 else DM)
    print(f"  {BD}«{word}»{W}  v={color}{report['valence']:+.3f}{W}")
    print(f"    {report['recommendation']}")
    if report["sequence"]:
        top = report["sequence"][0]
        print(f"    после → «{top['next']}» (p={top['probability']:.2f})")
    print()

print(f"{DM}{'─'*60}{W}")
print(f"{DM}Интуиция проверена на новых историях.{W}\n")
