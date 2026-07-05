"""
app/server_api.py — HTTP-сервер Active Corpus Server на FastAPI.

Запуск:
  py -X utf8 app/server_api.py --port 8100
  py -X utf8 app/server_api.py --port 8100 --db data/gen_base.db

Или через uvicorn:
  uvicorn app.server_api:app --port 8100 --reload

Эндпоинты
─────────
  POST /documents           — добавить документ
  GET  /documents           — список документов
  POST /search              — поиск по дырявому шаблону
  POST /probe               — зондировать позицию
  POST /shift               — сдвинуть курсор
  GET  /read                — прочитать N токенов
  GET  /stats               — статистика сервера
  POST /loop/start          — запустить автономный цикл в фоне
  POST /loop/stop           — остановить цикл
  GET  /loop/status         — статус цикла
  POST /probe_chain         — выполнить ProbeChain

Модели запросов и ответов — Pydantic.
"""
from __future__ import annotations

import argparse
import asyncio
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# FastAPI
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Внутренние модули
from app.text_server import ActiveTextServer, ZoomLevel
from core.query_builder import LeakyTemplate, TemplateSlot
from core.exploration import ExplorationPolicy, ProbeChain


# ══════════════════════════════════════════════════════════════════════════════
# FastAPI app
# ══════════════════════════════════════════════════════════════════════════════

app = FastAPI(
    title="Active Corpus Server",
    description="Gen-система с курсорной навигацией по корпусу",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Глобальный сервер и состояние цикла
_server: ActiveTextServer = ActiveTextServer()
_policy: ExplorationPolicy = ExplorationPolicy()
_loop_thread: Optional[threading.Thread] = None
_loop_running: bool = False
_loop_stats: Dict[str, Any] = {"cycles": 0, "hits": 0, "misses": 0, "started_at": None}


# ══════════════════════════════════════════════════════════════════════════════
# Pydantic модели
# ══════════════════════════════════════════════════════════════════════════════

class AddDocRequest(BaseModel):
    doc_id:  str
    content: str
    domain:  str = ""
    title:   str = ""


class SlotModel(BaseModel):
    kind:    str        # "anchor"|"required"|"alternative"|"wildcard"
    words:   List[str] = []
    max_gap: int = 0
    min_gap: int = 0


class SearchRequest(BaseModel):
    slots:      List[SlotModel]
    source:     str   = "api"
    confidence: float = 0.5
    zoom:       str   = "CORPUS"   # CORPUS|DOCUMENT|PARAGRAPH
    max_hits:   int   = 10


class ProbeRequest(BaseModel):
    expected: str
    delta:    int   = 0


class ShiftRequest(BaseModel):
    delta:  int
    doc_id: Optional[str] = None


class ReadRequest(BaseModel):
    length: int = 10


class ProbeChainRequest(BaseModel):
    steps: List[Dict[str, Any]]   # {expected, delta, critical}
    anchor_delta: int = 0


class LoopStartRequest(BaseModel):
    max_cycles:    int  = 0    # 0 = бесконечно
    training_text: str  = ""   # начальный текст для прогрева (опц.)


# ══════════════════════════════════════════════════════════════════════════════
# Документы
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/documents", summary="Добавить документ")
def add_document(req: AddDocRequest) -> Dict:
    _server.add_document(req.doc_id, req.content, domain=req.domain, title=req.title)
    return {"ok": True, "doc_id": req.doc_id, "corpus_size": _server.document_count()}


@app.get("/documents", summary="Список документов")
def list_documents(domain: str = "") -> Dict:
    docs = _server.list_documents(domain=domain)
    return {"docs": docs, "total": len(docs)}


# ══════════════════════════════════════════════════════════════════════════════
# Навигация
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/search", summary="Поиск по дырявому шаблону")
def search(req: SearchRequest) -> Dict:
    slots = [
        TemplateSlot(
            kind    = s.kind,
            words   = s.words,
            max_gap = s.max_gap,
            min_gap = s.min_gap,
        )
        for s in req.slots
    ]
    template = LeakyTemplate(slots=slots, source=req.source, confidence=req.confidence)
    try:
        zoom = ZoomLevel[req.zoom.upper()]
    except KeyError:
        raise HTTPException(400, f"Unknown zoom level: {req.zoom}")

    hits = _server.search(template, zoom=zoom, max_hits=req.max_hits)

    # Применить ExplorationPolicy: выбрать лучшее совпадение
    best = _policy.select(hits, _server._corpus, top_k=req.max_hits)

    return {
        "hits":  [
            {
                "doc_id":    h.doc_id,
                "para_idx":  h.para_idx,
                "token_idx": h.token_idx,
                "fragment":  h.fragment,
                "score":     h.score,
            }
            for h in hits
        ],
        "best_order": [
            {"doc_id": h.doc_id, "para_idx": h.para_idx}
            for h in best
        ],
        "regex":    template.to_regex().pattern,
        "total":    len(hits),
    }


@app.post("/probe", summary="Зондировать позицию cursor+delta")
def probe(req: ProbeRequest) -> Dict:
    result = _server.probe(req.expected, delta=req.delta)
    return {
        "hit":          result.hit,
        "actual_token": result.actual_token,
        "expected":     result.expected,
        "shift_to_next": result.shift_to_next,
    }


@app.post("/shift", summary="Сдвинуть курсор")
def shift(req: ShiftRequest) -> Dict:
    _server.shift(req.delta, doc_id=req.doc_id)
    return {"ok": True, "stats": _server.stats}


@app.get("/read", summary="Прочитать N токенов")
def read(length: int = 10) -> Dict:
    frag = _server.read(length)
    return {
        "doc_id":    frag.doc_id,
        "para_idx":  frag.para_idx,
        "tokens":    frag.tokens,
        "start_idx": frag.start_idx,
    }


@app.post("/probe_chain", summary="Выполнить ProbeChain")
def probe_chain(req: ProbeChainRequest) -> Dict:
    from core.exploration import ProbeStep
    chain = ProbeChain(
        steps=[
            ProbeStep(
                expected = s["expected"],
                delta    = s.get("delta", 0),
                critical = s.get("critical", True),
            )
            for s in req.steps
        ]
    )
    result = chain.run(_server, anchor_delta=req.anchor_delta)
    return {
        "passed":       result.passed,
        "steps_run":    result.steps_run,
        "steps_passed": result.steps_passed,
        "abort_reason": result.abort_reason,
        "confidence":   result.confidence,
    }


# ══════════════════════════════════════════════════════════════════════════════
# Статистика
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/stats", summary="Статистика сервера")
def stats() -> Dict:
    return {
        "server":      _server.stats,
        "exploration": _policy.stats,
        "loop":        _loop_stats,
    }


# ══════════════════════════════════════════════════════════════════════════════
# Фоновый цикл
# ══════════════════════════════════════════════════════════════════════════════

def _loop_worker(max_cycles: int) -> None:
    global _loop_running, _loop_stats
    _loop_stats["started_at"] = time.time()
    cycle = 0

    try:
        from core.learning import LearningSystem
        from core.capacity import CapacityBudget
        from drivers.text_driver import TextDriver

        system = LearningSystem(capacity_budget=CapacityBudget(max_gens=10_000))
        driver = TextDriver(system)

        def on_cycle(c: int, status: str) -> None:
            _loop_stats["cycles"] = c
            if "hit" in status:
                _loop_stats["hits"] = _loop_stats.get("hits", 0) + 1
            elif "miss" in status:
                _loop_stats["misses"] = _loop_stats.get("misses", 0) + 1

        _server.run_active_loop(
            system,
            driver,
            max_cycles=max_cycles,
            on_cycle=on_cycle,
        )
    finally:
        _loop_running = False
        _loop_stats["stopped_at"] = time.time()


@app.post("/loop/start", summary="Запустить автономный цикл")
def loop_start(req: LoopStartRequest) -> Dict:
    global _loop_thread, _loop_running

    if _loop_running:
        raise HTTPException(409, "Loop already running")

    _loop_running = True
    _loop_stats.update({"cycles": 0, "hits": 0, "misses": 0, "started_at": None})

    t = threading.Thread(target=_loop_worker, args=(req.max_cycles,), daemon=True)
    t.start()
    _loop_thread = t

    return {"ok": True, "max_cycles": req.max_cycles}


@app.post("/loop/stop", summary="Остановить автономный цикл")
def loop_stop() -> Dict:
    global _loop_running
    # Устанавливаем флаг — loop_worker завершится на следующей итерации
    # (ActiveTextServer не имеет внешнего stop-флага, поэтому просто помечаем)
    _loop_running = False
    return {"ok": True}


@app.get("/loop/status", summary="Статус автономного цикла")
def loop_status() -> Dict:
    return {
        "running": _loop_running,
        **_loop_stats,
    }


# ══════════════════════════════════════════════════════════════════════════════
# Навигация по гетерархии и любопытство
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/hierarchy/{word}", summary="Путь от корня до слова в гетерархии")
def hierarchy_path(word: str) -> Dict:
    """Найти путь от корня до слова: все Gen, содержащие это слово."""
    from drivers.narrator_driver import NarratorDriver
    from core.generalization import GeneralizationBase

    # Используем Gen из ActiveTextServer (если есть) или пустую базу
    base = getattr(_server, '_base', None)
    if base is None:
        return {"word": word, "path": [], "error": "no base available"}

    narrator = NarratorDriver(base)
    path = narrator.hierarchy_path(word)
    return {"word": word, "path": path, "total": len(path)}


@app.get("/hierarchy/{word}/branches", summary="Альтернативы на развилке")
def branch_variants(word: str) -> Dict:
    """Найти альтернативы на развилке для данного слова."""
    from drivers.narrator_driver import NarratorDriver

    base = getattr(_server, '_base', None)
    if base is None:
        return {"word": word, "variants": [], "error": "no base available"}

    narrator = NarratorDriver(base)
    variants = narrator.branch_variants(word)
    return {"word": word, "variants": variants, "total": len(variants)}


@app.get("/anchors", summary="Опоры модели (персонажи/предметы)")
def anchors(min_sig: float = 0.5) -> Dict:
    """Анализ опор: слова с высокой значимостью."""
    from drivers.narrator_driver import NarratorDriver

    base = getattr(_server, '_base', None)
    if base is None:
        return {"anchors": [], "error": "no base available"}

    narrator = NarratorDriver(base)
    result = narrator.anchor_analysis(min_sig=min_sig)
    return {"anchors": result, "total": len(result)}


@app.get("/curious", summary="Текущие вопросы модели")
def curious() -> Dict:
    """Генерировать вопросы на основе текущего состояния базы."""
    from core.curiosity import CharacterCuriosityEngine

    base = getattr(_server, '_base', None)
    if base is None:
        return {"queries": [], "error": "no base available"}

    engine = CharacterCuriosityEngine(base)
    anchors = engine.find_anchors()
    unfamiliar = engine.find_unfamiliar(anchors)
    queries = engine.generate_queries(anchors, unfamiliar, max_queries=10)

    return {
        "anchors_count": len(anchors),
        "unfamiliar_count": len(unfamiliar),
        "queries": queries,
        "top_anchors": [{"word": a.word, "sig": a.significance, "count": a.gen_count}
                        for a in anchors[:10]],
        "unfamiliar": [{"word": a.word, "sig": a.significance, "count": a.gen_count}
                       for a in unfamiliar[:10]],
    }


# ══════════════════════════════════════════════════════════════════════════════
# CLI запуск
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn

    parser = argparse.ArgumentParser(description="Active Corpus Server HTTP API")
    parser.add_argument("--port", type=int, default=8100)
    parser.add_argument("--host", type=str, default="127.0.0.1")
    parser.add_argument("--db",   type=str, default="")
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    print(f"Active Corpus Server → http://{args.host}:{args.port}")
    print(f"Docs → http://{args.host}:{args.port}/docs")

    uvicorn.run(
        "app.server_api:app",
        host    = args.host,
        port    = args.port,
        reload  = args.reload,
        log_level = "info",
    )
