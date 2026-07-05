"""Демо: 5 историй × 3 повторения — как меняются эмоции."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.app import CoreApplication
from drivers.text_driver import TextDriver
from drivers.emotion_driver import EmotionDriver

W = "\033[0m"; BD = "\033[1m"; DM = "\033[90m"
GR = "\033[92m"; RD = "\033[91m"; AM = "\033[93m"

app = CoreApplication(config={"mock_teacher": True, "feature_tolerance": 0.15})
app.startup()
emotion = EmotionDriver()
d = TextDriver("demo")

stories = [
    ("маша и ослик пошли в лес вместе", "Знакомство"),
    ("лиса обманула ослика ослик расстроился", "Конфликт"),
    ("маша помогла ослику ослик обрадовался", "Помощь"),
    ("маша и ослик снова пошли в лес вместе", "Восстановление"),
    ("лиса пришла к ослику и извинилась ослик простил", "Примирение"),
]

print(f"{BD}5 историй, по 3 повторения каждая{W}\n")

for rep in range(3):
    print(f"{BD}--- Повторение {rep + 1} ---{W}")
    for story, title in stories:
        n_c = n_r = n_co = 0
        for tok in d.produce(story):
            result = app.system.process_token(tok)
            o = result.outcome.name
            if o == "CONFIRMED":
                n_c += 1
            elif o == "REFUTED":
                n_r += 1
            elif o == "COMPLETED":
                n_co += 1
            active = tuple(app.system.engine.context.active_gen_ids())
            emotion.record(active, o, getattr(tok, "label", "") or "")
        app.system.reset_context()

        color = GR if n_c + n_co > n_r else RD
        print(f"  {title:<15} {color}+{n_c} *{n_co} -{n_r}{W}")

    # Состояние после повторения
    print(f"\n  {BD}Эмоции после повторения {rep + 1}:{W}")
    word_vals = []
    for w, vals in emotion._word_emotion.items():
        if len(vals) >= 1:
            avg = sum(vals) / len(vals)
            word_vals.append((w, avg, len(vals)))
    word_vals.sort(key=lambda x: x[1], reverse=True)
    for w, v, c in word_vals[:10]:
        color = GR if v > 0.1 else (RD if v < -0.1 else DM)
        bar = "+" * int(abs(v) * 10) if v > 0 else "-" * int(abs(v) * 10)
        print(f"    {w:<15} {color}{v:>6.3f}{W}  (x{c})  {DM}{bar}{W}")
    print()

print(f"{BD}Итог:{W}")
s = emotion.stats()
print(f"  Записей: {s['entries']}  Gen: {s['unique_gens']}  Связей: {s['relationships']}")
print(f"  {GR}+{s['positive']}{W}  {RD}-{s['negative']}{W}  {DM}~{s['neutral']}{W}")

rels = emotion.get_relationships(min_co=2)
if rels:
    print(f"\n  {BD}Связи:{W}")
    for r in rels[:5]:
        color = GR if r.avg_valence > 0 else (RD if r.avg_valence < 0 else DM)
        print(f"    {r.gen_a[:12]:<13} <-> {r.gen_b[:12]:<13} "
              f"co={r.co_count} {color}v={r.avg_valence:+.3f}{W}")
