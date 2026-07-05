"""
Шаг 6: SessionManager — менеджер сессий.

Сохраняет и загружает состояние LearningSystem через pickle.
Поддерживает именованные сессии, метаданные, список и удаление.

Использование:
    mgr = SessionManager("sessions")
    path = mgr.save("cats_training", system, metadata={"notes": "..."})
    system2, meta = mgr.load("cats_training")
"""

from __future__ import annotations

import os
import pickle
import time
from typing import Any, Dict, List, Optional, Tuple

from .learning import LearningSystem


class SessionManager:
    """
    Менеджер сессий: сохранение/загрузка LearningSystem через pickle.

    Каждая сессия хранится в файле <sessions_dir>/<name>.pkl
    вместе со словарём метаданных (время создания, статистика, заметки).
    """

    def __init__(self, sessions_dir: str = "sessions") -> None:
        self._dir = sessions_dir
        os.makedirs(self._dir, exist_ok=True)

    # ------------------------------------------------------------------
    # Сохранение / загрузка

    def save(
        self,
        name: str,
        system: LearningSystem,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Сохранить систему как сессию с именем name.
        Возвращает путь к файлу.
        """
        path = self._path(name)
        stats = system.stats()
        meta = {
            "name":       name,
            "created_at": time.time(),
            "base_size":  stats["base_size"],
            "features":   stats["features"],
            "steps":      stats["steps"],
        }
        if metadata:
            meta.update(metadata)

        with open(path, "wb") as f:
            pickle.dump({"system": system, "meta": meta}, f, protocol=5)
        return path

    def load(self, name: str) -> Tuple[LearningSystem, Dict[str, Any]]:
        """
        Загрузить сессию по имени.
        Возвращает (LearningSystem, metadata_dict).
        Поднимает FileNotFoundError если сессии не существует.
        """
        path = self._path(name)
        if not os.path.exists(path):
            raise FileNotFoundError(f"Сессия '{name}' не найдена: {path}")
        with open(path, "rb") as f:
            data = pickle.load(f)
        return data["system"], data["meta"]

    # ------------------------------------------------------------------
    # Управление

    def list_sessions(self) -> List[Dict[str, Any]]:
        """
        Список всех сессий отсортированный по времени создания (новые первые).
        """
        result = []
        for fname in os.listdir(self._dir):
            if not fname.endswith(".pkl"):
                continue
            path = os.path.join(self._dir, fname)
            try:
                with open(path, "rb") as f:
                    data = pickle.load(f)
                result.append(data.get("meta", {"name": fname[:-4]}))
            except Exception:
                result.append({"name": fname[:-4], "created_at": 0})
        result.sort(key=lambda m: m.get("created_at", 0), reverse=True)
        return result

    def delete(self, name: str) -> None:
        """Удалить сессию. Поднимает FileNotFoundError если нет."""
        path = self._path(name)
        if not os.path.exists(path):
            raise FileNotFoundError(f"Сессия '{name}' не найдена")
        os.remove(path)

    def exists(self, name: str) -> bool:
        """Проверить существование сессии."""
        return os.path.exists(self._path(name))

    def latest(self) -> Optional[str]:
        """Имя самой свежей сессии или None."""
        sessions = self.list_sessions()
        return sessions[0]["name"] if sessions else None

    # ------------------------------------------------------------------
    # Вспомогательное

    def _path(self, name: str) -> str:
        # Sanitize: разрешаем только буквы, цифры, дефис, подчёркивание
        safe = "".join(c for c in name if c.isalnum() or c in "-_")
        if not safe:
            raise ValueError(f"Недопустимое имя сессии: {name!r}")
        return os.path.join(self._dir, safe + ".pkl")

    def __repr__(self) -> str:
        n = len([f for f in os.listdir(self._dir) if f.endswith(".pkl")])
        return f"SessionManager(dir={self._dir!r}, sessions={n})"
