"""Демо: интуиция — прогноз последствий действий."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.app import CoreApplication
from drivers.text_driver import TextDriver
from drivers.emotion_driver import EmotionDriver

W = "\033[0m"; BD = "\033[1m"; DM = "\033[90m"
GR = "\033[92m"; RD = "\033[91m"; AM = "\033[93m"; MG = "\033[95m"

app = CoreApplication(config={"mock_teacher": True, "feature_tolerance": 0.15})
app.startup()
emotion = EmotionDriver()
d = TextDriver("demo")

# Корпус с повторяющимися паттернами «действие → последствие»
corpus = [
    # Паттерн: обидела → расстроился
    "лиса обманула зайца заяц расстроился и убежал",
    "лиса обманула кота кот расстроился и ушёл",
    "волк напугал зайца заяц расстроился и спрятался",
    "лиса обманула ослика ослик расстроился",
    # Паттерн: помогла → обрадовался
    "маша помогла зайцу заяц обрадовался и поблагодарил",
    "маша помогла коту кот обрадовался",
    "медведь помогла лисе лиса обрадовалась",
    "маша помогла ослику ослик обрадовалась",
    # Паттерн: угостил → обрадовался
    "заяц угостил лису лиса обрадовалась и поблагодарила",
    "медведь угостил зайцу заяц обрадовался",
    # Паттерн: играл вместе → весело
    "маша и ослик играли вместе весело смеялись",
    "кот и собака играли вместе весело",
    # Паттерн: потерял → грустный
    "заяц потерял морковку заяц был грустный",
    "кот потерял ключ кот был грустный",
]

print(f"{BD}Обучение: {len(corpus)} паттернов «действие → последствие»{W}\n")

for story in corpus:
    for tok in d.produce(story):
        result = app.system.process_token(tok)
        active = tuple(app.system.engine.context.active_gen_ids())
        emotion.record(active, result.outcome.name, getattr(tok, "label", "") or "")
    app.system.reset_context()

print(f"{BD}Эмоциональный драйвер:{W} {emotion}\n")

# ── Интуиция ────────────────────────────────────────────────────────
print(f"{BD}{'='*60}{W}")
print(f"{BD}  ИНТУИЦИЯ: прогноз последствий{W}")
print(f"{BD}{'='*60}{W}")

# Тест 1: что будет если кто-то обманет?
print(f"\n{BD}1. Что будет если «обманула»?{W}")
r = emotion.predict_outcome("обманула")
print(f"  Валентность: {AM}{r['overall_valence']:+.3f}{W}  "
      f"Уверенность: {r['confidence']}")
for c in r["likely_consequences"][:3]:
    color = GR if c["valence"] > 0 else RD
    print(f"  → {c['word']:<15} p={c['probability']:.2f}  "
          f"{color}v={c['valence']:+.3f}{W}")

# Тест 2: что будет если кто-то поможет?
print(f"\n{BD}2. Что будет если «помогла»?{W}")
r = emotion.predict_outcome("помогла")
print(f"  Валентность: {AM}{r['overall_valence']:+.3f}{W}  "
      f"Уверенность: {r['confidence']}")
for c in r["likely_consequences"][:3]:
    color = GR if c["valence"] > 0 else RD
    print(f"  → {c['word']:<15} p={c['probability']:.2f}  "
          f"{color}v={c['valence']:+.3f}{W}")

# Тест 3: что будет если кто-то напугал?
print(f"\n{BD}3. Что будет если «напугал»?{W}")
r = emotion.predict_outcome("напугал")
print(f"  Валентность: {AM}{r['overall_valence']:+.3f}{W}  "
      f"Уверенность: {r['confidence']}")
for c in r["likely_consequences"][:3]:
    color = GR if c["valence"] > 0 else RD
    print(f"  → {c['word']:<15} p={c['probability']:.2f}  "
          f"{color}v={c['valence']:+.3f}{W}")

# Тест 4: что будет если кто-то потерял?
print(f"\n{BD}4. Что будет если «потерял»?{W}")
r = emotion.predict_outcome("потерял")
print(f"  Валентность: {AM}{r['overall_valence']:+.3f}{W}  "
      f"Уверенность: {r['confidence']}")
for c in r["likely_consequences"][:3]:
    color = GR if c["valence"] > 0 else RD
    print(f"  → {c['word']:<15} p={c['probability']:.2f}  "
          f"{color}v={c['valence']:+.3f}{W}")

# ── Последовательности ─────────────────────────────────────────────
print(f"\n{BD}{'='*60}{W}")
print(f"{BD}  ПОСЛЕДОВАТЕЛЬНОСТИ: что идёт после слова?{W}")
print(f"{BD}{'='*60}{W}")

for word in ["лиса", "маша", "заяц", "кот"]:
    seq = emotion.predict_sequence(word)
    if seq:
        print(f"\n  {BD}«{word}»:{W}")
        for s in seq[:4]:
            color = GR if s["valence"] > 0 else (RD if s["valence"] < 0 else DM)
            print(f"    → {s['next']:<15} p={s['probability']:.2f}  "
                  f"{color}v={s['valence']:+.3f}{W}")

# ── Полные отчёты ──────────────────────────────────────────────────
print(f"\n{BD}{'='*60}{W}")
print(f"{BD}  ПОЛНЫЕ ОТЧЁТЫ ИНТУИЦИИ{W}")
print(f"{BD}{'='*60}{W}")

for word in ["обидела", "помогла", "поиграл", "потерял"]:
    r = emotion.intuition_report(word)
    color = GR if r["valence"] > 0 else (RD if r["valence"] < 0 else DM)
    print(f"\n  {BD}«{word}»:{W}")
    print(f"    Валентность: {color}{r['valence']:+.3f}{W}")
    print(f"    Рекомендация: {r['recommendation']}")
    if r["prediction"]["likely_consequences"]:
        top = r["prediction"]["likely_consequences"][0]
        print(f"    Прогноз: «{top['word']}» (p={top['probability']:.2f})")

print(f"\n{DM}{'─'*60}{W}")
print(f"{DM}Интуиция работает: из ретроспективных эмоций → прогноз будущего{W}\n")
