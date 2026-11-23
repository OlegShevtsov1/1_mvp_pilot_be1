---
name: Python Best Practices
description: "Use when writing or reviewing Python code. Covers Pythonic idioms, modern tooling (uv, ruff, pyright), project layout, and pytest conventions."
---

# Python Best Practices

Python optimizes for readability and expressiveness. "There should be one -- and preferably only one -- obvious way to do it." Modern Python (3.10+) has powerful type hints, structural pattern matching, and a mature packaging ecosystem.

## Idioms & Conventions

- **List/dict/set comprehensions over loops** for transformations: `[x.name for x in users if x.active]`.
- **Context managers (`with`)** for any resource that needs cleanup -- files, connections, locks. Write custom ones with `contextlib.contextmanager`.
- **Generators for large sequences.** Use `yield` instead of building lists in memory. Chain with `itertools`.
- **Structural pattern matching** (3.10+) for complex branching: `match event: case Click(x, y): ...`.
- **Type hints everywhere.** Use `str | None` (3.10+) over `Optional[str]`. Annotate function signatures and class attributes.
- **Dataclasses or Pydantic models** instead of plain dicts for structured data. Use `@dataclass(frozen=True)` for immutable value objects.
- **f-strings** for interpolation, never `%` or `.format()` in new code.
- **`pathlib.Path`** over `os.path` for filesystem operations.

## Tooling

| Tool | Purpose |
|---|---|
| `uv` | Fast package manager and virtualenv creator (replaces pip + venv) |
| `ruff` | Linter and formatter (replaces flake8 + isort + black) |
| `mypy` / `pyright` | Static type checking -- use `strict` mode |
| `pytest` | Test runner |
| `pre-commit` | Git hook manager for automated checks |

## Project Structure

```
pyproject.toml        # Single source of truth for metadata, deps, tool config
src/
  mypackage/
    __init__.py
    config.py
    models.py
    services/
      __init__.py
      user_service.py
tests/
  conftest.py         # Shared fixtures
  test_models.py
  test_services/
    test_user_service.py
```

Use the `src/` layout to prevent accidental imports of the source tree. All tool configuration belongs in `pyproject.toml` -- avoid `setup.cfg`, `setup.py`, `tox.ini` in new projects.

## Testing with pytest

- **Name files `test_*.py`** and functions `test_*`. Classes: `TestGroupName` (no `__init__`).
- **Fixtures over setup/teardown.** Define in `conftest.py` for shared state. Use `@pytest.fixture(scope="session")` for expensive setup.
- **Parametrize** to test multiple inputs: `@pytest.mark.parametrize("input,expected", [(1, 2), (3, 4)])`.
- **Use `tmp_path` fixture** for filesystem isolation (built-in, no library needed).
- **Mocking:** `unittest.mock.patch` or `pytest-mock`'s `mocker` fixture. Patch where the name is used, not where it is defined.
- **Markers:** `@pytest.mark.slow`, `@pytest.mark.integration` -- skip in CI with `-m "not slow"`.

## Common Pitfalls

| Pitfall | Fix |
|---|---|
| Mutable default arguments (`def f(items=[])`) | Use `None` and assign inside: `items = items or []` |
| Bare `except:` swallowing all errors | Catch specific exceptions; at minimum `except Exception` |
| Circular imports | Move imports inside functions or restructure modules |
| Not using virtual environments | Always isolate: `uv venv` or `python -m venv .venv` |
| Ignoring type checker errors | Run `mypy --strict` or `pyright` in CI -- treat errors as blockers |

## Related Framework Skills

| Framework | Official Skill? | Status |
|-----------|:---:|--------|
| **FastAPI** | Partial | `fastapi-patterns` in this repo |
| **Django** | No | `django-patterns` in this repo |
| **Flask** | No | `flask-patterns` in this repo |
| **Supabase** | [Yes](https://github.com/supabase/agent-skills) (37.7K installs) | `supabase-patterns` in this repo complements it |

## Attribution
**Original** — Datatide, MIT licensed.
