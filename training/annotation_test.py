"""Проверка: учительская разметка перезаписывает опыт."""
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
ann = AnnotationDriver()
emotion = EmotionDriver(annotation_driver=ann)
d = TextDriver("demo")

# Разметка учителя (включая обнимания и тёплые слова)
ann.batch_annotate({
    "помогла": +1, "помог": +1, "угостила": +1, "угостил": +1,
    "обрадовался": +1, "поблагодарил": +1, "поблагодарила": +1,
    "играли": +0.8, "смеялись": +0.8, "весело": +0.8,
    "обняла": +1, "обнял": +1, "обнимаю": +1, "обнимает": +1,
    "тепло": +0.8, "радостно": +0.8,
    "улыбнулся": +0.8, "улыбнулась": +0.8,
    "обманула": -1, "напугал": -1,
    "расстроился": -0.8, "испугался": -0.8,
    "убежал": -0.7, "спрятался": -0.7, "ушёл": -0.5,
})

# Обучение
train = [
    "маша помогла зайцу заяц обрадовался поблагодарил",
    "лиса обманула зайца заяц расстроился убежал",
    "маша и ослик играли вместе весело смеялись",
    "лиса обманула кота кот расстроился ушёл",
    "медведь помог лисе лиса обрадовалась поблагодарила",
    "волк напугал зайца заяц испугался спрятался",
]
for s in train:
    for tok in d.produce(s):
        r = app.system.process_token(tok)
        emotion.record(
            tuple(app.system.engine.context.active_gen_ids()),
            r.outcome.name, getattr(tok, "label", "") or "",
        )
    app.system.reset_context()

print(f"{BD}ПРОВЕРКА: учительская разметка перезаписывает опыт{W}\n")

# Новая история
new = "маша обняла зайца зайц стало тепло и радостно он улыбнулся"
print(f"{BD}Новая история:{W} {MG}{new}{W}\n")

# ДО обработки
print(f"{BD}ДО обработки:{W}")
for w in ["обняла", "зайца", "тепло", "радостно", "улыбнулся", "обманула", "напугал"]:
    v = emotion.get_word_valence(w)
    has_ann = ann.has_annotation(w)
    color = GR if v > 0.1 else (RD if v < -0.1 else DM)
    src = f"{AM}[teacher]{W}" if has_ann else f"{DM}[experience]{W}"
    print(f"  {w:<15} {color}{v:>6.3f}{W}  {src}")

# Обработка
for tok in d.produce(new):
    r = app.system.process_token(tok)
    emotion.record(
        tuple(app.system.engine.context.active_gen_ids()),
        r.outcome.name, getattr(tok, "label", "") or "",
    )
app.system.reset_context()

# ПОСЛЕ обработки
print(f"\n{BD}ПОСЛЕ обработки:{W}")
for w in ["обняла", "зайца", "тепло", "радостно", "улыбнулся", "обманула", "напугал"]:
    v = emotion.get_word_valence(w)
    has_ann = ann.has_annotation(w)
    color = GR if v > 0.1 else (RD if v < -0.1 else DM)
    src = f"{AM}[teacher]{W}" if has_ann else f"{DM}[experience]{W}"
    print(f"  {w:<15} {color}{v:>6.3f}{W}  {src}")

# Вторая новая история
print(f"\n{BD}Вторая новая история:{W} {MG}волк обнял зайца и зайц стало тепло{W}\n")
for tok in d.produce("волк обнял зайца и зайц стало тепло"):
    r = app.system.process_token(tok)
    emotion.record(
        tuple(app.system.engine.context.active_gen_ids()),
        r.outcome.name, getattr(tok, "label", "") or "",
    )
app.system.reset_context()

# Итоговая интуиция
print(f"{BD}Итоговая интуиция:{W}")
for w in ["обняла", "обнял", "обманула", "помогла", "напугал", "тепло", "улыбнулся"]:
    report = emotion.intuition_report(w)
    v = report["valence"]
    color = GR if v > 0.1 else (RD if v < -0.1 else DM)
    src = f"{AM}[teacher]{W}" if ann.has_annotation(w) else f"{DM}[exp]{W}"
    print(f"  {w:<15} {color}v={v:+.3f}{W}  {src}  {report['recommendation']}")
