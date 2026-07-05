"""Тело / ключи: доступ LLM-учителей без секретов в git (О-7, З-0023).

Инвариант SPEC §1.6: Тело не имеет права на семантику. Этот модуль только
резолвит учётные данные учителей; что и когда спрашивать — дело ядра.

Схема для исследователя:
  1. Скопировать .secrets/keys.env.example → .secrets/keys.env, вписать ключи.
  2. Скопировать teachers.example.toml → teachers.local.toml, описать СВОИХ
     учителей (имя, провайдер, модель, ИМЯ переменной с ключом — не сам ключ).
  3. load_teachers() вернёт реестр; available_teachers() — тех, чей ключ задан.

Порядок разрешения ключа (первый найденный побеждает):
  1. переменная окружения, уже установленная в системе/CI;
  2. .secrets/keys.env (KEY=VALUE; в git не попадает по .gitignore).

Совместимость со стендом: имена провайдеров и переменных совпадают с
core/llm_providers._PROVIDER_MAP (clients_from_env), так что после
load_secrets_env() стендовый автодетектор работает без изменений.
"""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SECRETS_ENV = ROOT / ".secrets" / "keys.env"
TEACHERS_LOCAL = ROOT / "teachers.local.toml"
TEACHERS_EXAMPLE = ROOT / "teachers.example.toml"

# Совпадает с _PROVIDER_MAP стенда + свой/self-hosted endpoint.
KNOWN_PROVIDERS = {
    "claude", "openai", "grok", "deepseek", "qwen", "gemini",
    "openai_compatible",
}


def load_secrets_env(path: Path = SECRETS_ENV, *, override: bool = False) -> int:
    """Подгрузить KEY=VALUE из .secrets/keys.env в os.environ.

    Системное окружение главнее файла: уже установленные переменные
    не перезаписываются (если не передан override=True).
    Возвращает число загруженных переменных.
    """
    if not path.exists():
        return 0
    loaded = 0
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if not key:
            continue
        if override or not os.environ.get(key):
            os.environ[key] = value
            loaded += 1
    return loaded


@dataclass(frozen=True)
class TeacherConfig:
    """Описание одного LLM-учителя. Секрета внутри нет — только key_env."""
    name: str                 # имя учителя в рое, напр. "anna-deepseek"
    provider: str             # один из KNOWN_PROVIDERS
    model: str
    key_env: str              # ИМЯ переменной окружения с ключом
    base_url: str | None = None   # только для openai_compatible

    @property
    def api_key(self) -> str:
        return os.environ.get(self.key_env, "").strip()

    @property
    def is_available(self) -> bool:
        return bool(self.api_key)


def load_teachers(path: Path | None = None) -> list[TeacherConfig]:
    """Прочитать реестр учителей (teachers.local.toml, иначе шаблон).

    Валидация: провайдер известен; openai_compatible требует base_url;
    имена учителей уникальны. Ключи подтягиваются через load_secrets_env().
    """
    load_secrets_env()
    p = path if path is not None else (
        TEACHERS_LOCAL if TEACHERS_LOCAL.exists() else TEACHERS_EXAMPLE
    )
    if not p.exists():
        return []
    data = tomllib.loads(p.read_text(encoding="utf-8"))
    teachers: list[TeacherConfig] = []
    seen: set[str] = set()
    for entry in data.get("teacher", []):
        name = entry["name"]
        provider = entry["provider"]
        if provider not in KNOWN_PROVIDERS:
            raise ValueError(
                f"Учитель '{name}': неизвестный provider '{provider}'. "
                f"Допустимы: {sorted(KNOWN_PROVIDERS)}"
            )
        if provider == "openai_compatible" and not entry.get("base_url"):
            raise ValueError(
                f"Учитель '{name}': provider 'openai_compatible' требует base_url"
            )
        if name in seen:
            raise ValueError(f"Дубликат имени учителя: '{name}'")
        seen.add(name)
        teachers.append(TeacherConfig(
            name=name,
            provider=provider,
            model=entry["model"],
            key_env=entry["key_env"],
            base_url=entry.get("base_url"),
        ))
    return teachers


def available_teachers(path: Path | None = None) -> list[TeacherConfig]:
    """Учителя, чей ключ реально доступен в окружении."""
    return [t for t in load_teachers(path) if t.is_available]


if __name__ == "__main__":
    ts = load_teachers()
    print(f"Реестр: {len(ts)} учителей")
    for t in ts:
        mark = "КЛЮЧ ЕСТЬ" if t.is_available else f"нет ключа (задайте {t.key_env})"
        print(f"  {t.name:24s} {t.provider:18s} {t.model:28s} {mark}")
