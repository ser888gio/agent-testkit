"""Test discovery/loading: YAML/JSON declarative packs + basic Python test modules."""

from __future__ import annotations

import importlib.util
import inspect
import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from agentkit.core.assertions import REGISTRY as ASSERTION_REGISTRY
from agentkit.core.schema import Category, Risk, TestCase


class LoaderError(Exception):
    pass


@dataclass
class PythonTestCase:
    """A `def test_*(agent, sandbox)` function collected as a test-equivalent."""

    id: str
    category: Category
    risk: Risk
    fn: Callable[[Any, Any], None]
    tags: list[str] = field(default_factory=list)
    timeout_s: float = 30.0


def meta(
    *,
    category: str | None = None,
    risk: str | None = None,
    tags: list[str] | None = None,
):
    """Decorator to override the default category/risk/tags for a Python test function."""

    def _decorator(fn):
        fn._agentkit_meta = {"category": category, "risk": risk, "tags": tags or []}
        return fn

    return _decorator


def _check_enum(path: Path, field_name: str, value: str, enum: type[Enum]) -> None:
    valid = {member.value for member in enum}
    if value not in valid:
        raise LoaderError(
            f"{path}: invalid {field_name} '{value}' (valid: {', '.join(sorted(valid))})"
        )


def _build_test_case(raw: dict[str, Any], path: Path) -> TestCase:
    if not isinstance(raw, dict):
        raise LoaderError(f"{path}: expected a mapping, got {type(raw).__name__}")
    for required in ("id", "assertions"):
        if required not in raw:
            raise LoaderError(f"{path}: missing required field '{required}'")
    if ("input" in raw) == ("turns" in raw):
        raise LoaderError(f"{path}: exactly one of 'input' or 'turns' is required")

    if "category" in raw:
        _check_enum(path, "category", raw["category"], Category)
    if "risk" in raw:
        _check_enum(path, "risk", raw["risk"], Risk)

    try:
        test_case = TestCase.model_validate(raw)
    except ValidationError as exc:
        raise LoaderError(f"{path}: {exc}") from exc

    for a in test_case.assertions:
        if a.name not in ASSERTION_REGISTRY:
            raise LoaderError(
                f"{path}: unknown assertion '{a.name}' in test '{test_case.id}'"
            )

    return test_case


def load_tests_from_rows(rows: list[dict[str, Any]]) -> list[TestCase]:
    """Same validation as load_file, for tests stored as DB rows instead of files."""
    tests: list[TestCase] = []
    seen: dict[str, int] = {}
    for index, raw in enumerate(rows):
        test = _build_test_case(raw, Path(f"<row {index}>"))
        if test.id in seen:
            raise LoaderError(
                f"<row {index}>: duplicate test id '{test.id}' "
                f"(first seen in <row {seen[test.id]}>)"
            )
        seen[test.id] = index
        tests.append(test)
    return tests


def load_file(path: str | Path) -> list[TestCase]:
    path = Path(path)
    text = path.read_text(encoding="utf-8")

    try:
        if path.suffix == ".json":
            raw = json.loads(text)
        else:
            raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        line = f":{mark.line + 1}" if mark else ""
        raise LoaderError(f"malformed YAML at {path}{line}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise LoaderError(f"malformed JSON at {path}:{exc.lineno}: {exc}") from exc

    if isinstance(raw, dict):
        items = [raw]
    elif isinstance(raw, list):
        items = raw
    else:
        raise LoaderError(f"{path}: expected a mapping or list of mappings")

    return [_build_test_case(item, path) for item in items]


def load_python_module(path: str | Path) -> list[PythonTestCase]:
    path = Path(path)
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        raise LoaderError(f"{path}: cannot load as a Python module")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise LoaderError(f"{path}: error importing module: {exc}") from exc

    tests: list[PythonTestCase] = []
    for name, fn in inspect.getmembers(module, inspect.isfunction):
        if not name.startswith("test_"):
            continue
        params = list(inspect.signature(fn).parameters)
        if params[:2] != ["agent", "sandbox"]:
            continue

        override = getattr(fn, "_agentkit_meta", {})
        category_raw = override.get("category") or "action_safety"
        risk_raw = override.get("risk") or "medium"

        _check_enum(path, "category", category_raw, Category)
        _check_enum(path, "risk", risk_raw, Risk)

        tests.append(
            PythonTestCase(
                id=f"{path.stem}.{name}",
                category=Category(category_raw),
                risk=Risk(risk_raw),
                fn=fn,
                tags=override.get("tags", []),
            )
        )
    return tests


def discover(root: str | Path) -> list[TestCase | PythonTestCase]:
    root = Path(root)
    paths = sorted(
        p
        for p in root.rglob("*")
        if p.is_file()
        and (
            p.suffix in (".yaml", ".yml", ".json")
            or (p.name.startswith("test_") and p.suffix == ".py")
        )
    )

    tests: list[TestCase | PythonTestCase] = []
    seen: dict[str, Path] = {}

    for path in paths:
        if path.suffix == ".py":
            loaded: Iterable[TestCase | PythonTestCase] = load_python_module(path)
        else:
            loaded = load_file(path)

        for test in loaded:
            if test.id in seen:
                raise LoaderError(
                    f"duplicate test id '{test.id}' in {seen[test.id]} and {path}"
                )
            seen[test.id] = path
            tests.append(test)

    return sorted(tests, key=lambda t: (str(seen[t.id]), t.id))


def filter_tests(
    tests: list[TestCase | PythonTestCase],
    *,
    tags: list[str] | None = None,
    categories: list[Category] | None = None,
    ids: list[str] | None = None,
) -> list[TestCase | PythonTestCase]:
    result = tests
    if tags:
        tag_set = set(tags)
        result = [t for t in result if tag_set & set(t.tags)]
    if categories:
        cat_set = set(categories)
        result = [t for t in result if t.category in cat_set]
    if ids:
        id_set = set(ids)
        result = [t for t in result if t.id in id_set]
    return result
