"""Smoke-тесты body/keys.py: env-файл, приоритеты, реестр учителей, валидация."""
import os
import tempfile
from pathlib import Path

from keys import TeacherConfig, load_secrets_env, load_teachers, TEACHERS_EXAMPLE


def _tmp(content: str, suffix: str) -> Path:
    f = tempfile.NamedTemporaryFile("w", suffix=suffix, delete=False,
                                    encoding="utf-8")
    f.write(content)
    f.close()
    return Path(f.name)


def test_env_file_parsed_and_system_env_wins():
    path = _tmp('TK_A=file_a\n# комментарий\nTK_B="file_b"\n\nбез-равно\n', ".env")
    os.environ.pop("TK_A", None)
    os.environ["TK_B"] = "system_b"
    try:
        loaded = load_secrets_env(path)
        assert loaded == 1, "TK_B уже в системе — файл не перезаписывает"
        assert os.environ["TK_A"] == "file_a"
        assert os.environ["TK_B"] == "system_b", "системное окружение главнее файла"
    finally:
        path.unlink()
        os.environ.pop("TK_A", None)
        os.environ.pop("TK_B", None)


def test_missing_env_file_is_ok():
    assert load_secrets_env(Path("no/such/keys.env")) == 0


def test_example_registry_loads_and_holds_no_secrets():
    teachers = load_teachers(TEACHERS_EXAMPLE)
    assert len(teachers) >= 2
    assert all(t.key_env for t in teachers), "каждый учитель ссылается на key_env"
    text = TEACHERS_EXAMPLE.read_text(encoding="utf-8")
    assert "sk-ant-" not in text.replace("sk-ant-...", ""), "секретов в реестре нет"


def test_availability_follows_env():
    t = TeacherConfig(name="t", provider="deepseek", model="m", key_env="TK_KEY")
    os.environ.pop("TK_KEY", None)
    assert not t.is_available
    os.environ["TK_KEY"] = "value"
    try:
        assert t.is_available and t.api_key == "value"
    finally:
        os.environ.pop("TK_KEY", None)


def test_unknown_provider_rejected():
    path = _tmp('[[teacher]]\nname="x"\nprovider="hal9000"\nmodel="m"\nkey_env="K"\n',
                ".toml")
    try:
        load_teachers(path)
        assert False, "ожидали ValueError"
    except ValueError as e:
        assert "hal9000" in str(e)
    finally:
        path.unlink()


def test_openai_compatible_requires_base_url_and_names_unique():
    bad_url = '[[teacher]]\nname="x"\nprovider="openai_compatible"\nmodel="m"\nkey_env="K"\n'
    path = _tmp(bad_url, ".toml")
    try:
        try:
            load_teachers(path)
            assert False, "ожидали ValueError про base_url"
        except ValueError as e:
            assert "base_url" in str(e)
    finally:
        path.unlink()
    dup = ('[[teacher]]\nname="x"\nprovider="qwen"\nmodel="m"\nkey_env="K"\n'
           '[[teacher]]\nname="x"\nprovider="qwen"\nmodel="m"\nkey_env="K"\n')
    path = _tmp(dup, ".toml")
    try:
        try:
            load_teachers(path)
            assert False, "ожидали ValueError про дубликат"
        except ValueError as e:
            assert "Дубликат" in str(e)
    finally:
        path.unlink()


if __name__ == "__main__":
    for f in (test_env_file_parsed_and_system_env_wins, test_missing_env_file_is_ok,
              test_example_registry_loads_and_holds_no_secrets,
              test_availability_follows_env, test_unknown_provider_rejected,
              test_openai_compatible_requires_base_url_and_names_unique):
        f(); print(f"OK {f.__name__}")
