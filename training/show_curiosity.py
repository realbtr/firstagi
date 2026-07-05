"""Показать сгенерированные вопросы любопытства."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.app import CoreApplication
from core.curiosity import CharacterCuriosityEngine
from drivers.emotion_driver import EmotionDriver
from drivers.annotation_driver import AnnotationDriver
from drivers.text_driver import TextDriver

W = "\033[0m"; BD = "\033[1m"; DM = "\033[90m"
GR = "\033[92m"; RD = "\033[91m"; AM = "\033[93m"; MG = "\033[95m"

app = CoreApplication(config={"mock_teacher": True, "feature_tolerance": 0.15})
app.startup()

ann = AnnotationDriver()
ann.batch_annotate({
    "помогла": +1, "помог": +1, "обрадовался": +1, "поблагодарил": +1,
    "играли": +0.8, "смеялись": +0.8, "весело": +0.8,
    "обняла": +1, "обнял": +1, "тепло": +0.8, "радостно": +0.8,
    "обманула": -1, "напугал": -1, "расстроился": -0.8,
    "убежал": -0.7, "спрятался": -0.7,
})
emotion = EmotionDriver(annotation_driver=ann)

d = TextDriver("demo")
stories = [
    "маша пошла в лес и встретила медведя медведь обрадовался",
    "маша принесла медведю пирог медведь поел поблагодарил",
    "заяц и лиса играли в прятки в лесу смеялись весело",
    "лиса обманула зайца заяц расстроился убежал",
    "медведь нашёл мёд принёс зайцу заяц поблагодарил",
    "кот сидит на окне кот мяукает кот хочет есть",
    "собака бежит по улице собака громко лает",
]
for s in stories:
    for tok in d.produce(s):
        r = app.system.process_token(tok)
        emotion.record(
            tuple(app.system.engine.context.active_gen_ids()),
            r.outcome.name, getattr(tok, "label", "") or "",
        )
    app.system.reset_context()

engine = CharacterCuriosityEngine(app.system.base)
anchors = engine.find_anchors()
unfamiliar = engine.find_unfamiliar(anchors)
queries = engine.generate_queries(anchors, unfamiliar, max_queries=15)

print(f"{BD}АНКОРЫ МОДЕЛИ:{W}")
for a in anchors[:12]:
    v = emotion.get_word_valence(a.word)
    color = GR if v > 0.1 else (RD if v < -0.1 else DM)
    has_ann = ann.has_annotation(a.word)
    src = f" {AM}[ann]{W}" if has_ann else ""
    print(f"  {a.word:<15} {color}v={v:+.3f}{W}  gen={a.gen_count:>3}{src}")

print(f"\n{BD}UNFAMILIAR (хочет узнать больше):{W}")
for a in unfamiliar[:8]:
    v = emotion.get_word_valence(a.word)
    color = GR if v > 0.1 else (RD if v < -0.1 else DM)
    print(f"  {MG}*{W} {a.word:<15} gen={a.gen_count:>3}  {color}v={v:+.3f}{W}")

print(f"\n{BD}ЗАПРОСЫ К УЧИТЕЛЮ ({len(queries)} всего):{W}")
for i, q in enumerate(queries, 1):
    prio = {1: f"{RD}!!{W}", 2: f"{AM}!{W}", 3: f"{DM}.{W}"}.get(q["priority"], "")
    question = q["question"]
    context = q["context"][:80]
    print(f"  {BD}{i:>2}.{W} {prio} {question}")
    print(f"      {DM}{context}...{W}")
