"""
Шаг 6: HTTP API сервер для FirstAGI (FastAPI).

Запуск:
    py -m app.server
    py -m app.server --host 0.0.0.0 --port 8000

Эндпоинты:
    POST /learn            — обучить системе тексту
    GET  /status           — полный снапшот
    GET  /narrative        — нарративный отчёт
    GET  /attractors       — карта аттракторов
    GET  /base             — топ обобщений
    POST /reset            — сбросить контекст
    POST /teachers/order   — поставить ордер на награду
    GET  /teachers/log     — последние N записей TeachingLog
    GET  /sessions         — список сессий
    POST /sessions/save    — сохранить сессию
    POST /sessions/load    — загрузить сессию
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

try:
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import JSONResponse
    from pydantic import BaseModel
    import uvicorn
except ImportError as _e:
    sys.exit(
        "Необходимы зависимости: py -m pip install fastapi 'uvicorn[standard]'\n"
        f"  ({_e})"
    )

from core.app import CoreApplication
from core.teacher import RewardOrder


# ── Единственный экземпляр приложения ─────────────────────────────────
_app_instance: CoreApplication | None = None


def get_app() -> CoreApplication:
    global _app_instance
    if _app_instance is None:
        _app_instance = CoreApplication()
        _app_instance.startup()
    return _app_instance


# ── FastAPI ────────────────────────────────────────────────────────────
api = FastAPI(
    title="FirstAGI API",
    description="HTTP интерфейс к ядру FirstAGI (прямое исчисление аттрактора).",
    version="0.6.0",
)


# ── Модели запросов ────────────────────────────────────────────────────

class LearnRequest(BaseModel):
    text: str
    driver_id: str = "text"
    reset_after: bool = True


class TeacherOrderRequest(BaseModel):
    required_gens: list[str]
    reward: float = 30.0
    label: str = ""
    max_fires: int = 1


class SessionSaveRequest(BaseModel):
    name: str
    notes: str = ""


class SessionLoadRequest(BaseModel):
    name: str


# ── Эндпоинты ─────────────────────────────────────────────────────────

@api.get("/status", summary="Полный снапшот системы")
def status():
    return get_app().status()


@api.post("/learn", summary="Обучить систему тексту")
def learn(req: LearnRequest):
    result = get_app().learn(
        req.text,
        driver_id=req.driver_id,
        reset_after=req.reset_after,
    )
    return result


@api.get("/narrative", summary="Нарративный отчёт")
def narrative():
    app = get_app()
    return {"report": app.voice.state_report()}


@api.get("/attractors", summary="Карта аттракторов")
def attractors():
    app = get_app()
    enc = app.system.encoder
    attrs = enc.find_attractors(min_strength=0.0)
    return {
        "count": len(attrs),
        "attractors": [
            {
                "strength":   a.strength,
                "core_count": len(a.core_gen_ids),
                "basin_size": a.basin_size,
                "core_ids":   list(a.core_gen_ids)[:5],
            }
            for a in attrs[:20]
        ],
        "report": app.voice.attractor_report(),
    }


@api.get("/base", summary="Топ обобщений из базы")
def base(n: int = 20):
    app = get_app()
    gens = app.system.base.rank()[:n]
    return {
        "total": app.system.base.size(),
        "returned": len(gens),
        "generalizations": [
            {
                "gen_id":      g.gen_id,
                "label":       g.label,
                "significance": round(g.significance, 4),
                "level":       g.generalization_level,
                "success":     g.success_count,
                "stop":        g.stop_count,
            }
            for g in gens
        ],
    }


@api.post("/reset", summary="Сбросить текущий контекст")
def reset():
    get_app().system.reset_context()
    return {"ok": True}


@api.post("/teachers/order", summary="Поставить ордер на награду")
def teacher_order(req: TeacherOrderRequest):
    app = get_app()
    if not req.required_gens:
        raise HTTPException(status_code=400, detail="required_gens не может быть пустым")
    order = RewardOrder(
        required_gen_ids=set(req.required_gens),
        reward=req.reward,
        label=req.label,
        max_fires=req.max_fires,
    )
    app.system.teaching_log.push_reward_order(order)
    return {"ok": True, "label": order.label, "reward": order.reward}


@api.get("/teachers/log", summary="Последние N записей TeachingLog")
def teacher_log(n: int = 20):
    app = get_app()
    entries = app.system.teaching_log.get_recent(n)
    return {
        "total_entries": app.system.teaching_log.size(),
        "returned": len(entries),
        "entries": entries,
    }


@api.get("/sessions", summary="Список сохранённых сессий")
def sessions_list():
    app = get_app()
    return {"sessions": app.sessions.list_sessions()}


@api.post("/sessions/save", summary="Сохранить текущую сессию")
def sessions_save(req: SessionSaveRequest):
    app = get_app()
    try:
        path = app.save_session(req.name, metadata={"notes": req.notes} if req.notes else None)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "path": path, "name": req.name}


@api.post("/sessions/load", summary="Загрузить сессию")
def sessions_load(req: SessionLoadRequest):
    app = get_app()
    if not app.sessions.exists(req.name):
        raise HTTPException(status_code=404, detail=f"Сессия '{req.name}' не найдена")
    meta = app.load_session(req.name)
    return {"ok": True, "meta": meta}


# ── Точка входа ────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="FirstAGI HTTP API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    parser.add_argument("--sessions-dir", default="sessions")
    args = parser.parse_args()

    # Инициализировать с параметрами
    global _app_instance
    _app_instance = CoreApplication(config={"sessions_dir": args.sessions_dir})
    _app_instance.startup()

    print(f"FirstAGI API → http://{args.host}:{args.port}")
    print(f"  Документация: http://{args.host}:{args.port}/docs")
    uvicorn.run(
        "app.server:api",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
