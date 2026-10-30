"""``reviso deck validate`` -- check a deck before publishing it.

The server owns the contract gate, so the CLI asks it rather than re-implementing
rules in Python. That keeps one source of truth: whatever diagnostics a failing
``publish`` would return, ``validate`` prints first, before anything is created.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from ..errors import ValidationError

DEFAULT_CONTRACT_VERSION = "html-deck/1"

_VERSION_ATTR = re.compile(r'data-contract-version=["\']([^"\']+)["\']')
_DECK_ROOT = re.compile(r'class=["\'][^"\']*\bhr-deck\b')


def read_deck(path: str) -> tuple[str, str]:
    """Read a deck file and return (content, contract_version).

    The version comes from the root attribute so a deck written against a
    future contract is not silently validated as this one. A file without a
    deck root is rejected locally -- there is nothing for the server to check.
    """
    file = Path(path)
    if not file.is_file():
        raise ValidationError(f"no such file: {path}")
    try:
        content = file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ValidationError(f"cannot read {path}: {exc}") from exc
    if not content.strip():
        raise ValidationError(f"{path} is empty")
    if not _DECK_ROOT.search(content):
        raise ValidationError(
            f"{path} is not a deck: no element carries class=\"hr-deck\"")
    match = _VERSION_ATTR.search(content)
    return content, (match.group(1) if match else DEFAULT_CONTRACT_VERSION)


def cmd_deck_validate(args) -> None:
    content, version = read_deck(args.file)
    result = args.client_factory().validate_deck(
        content, deck_contract_version=version)
    _print_result(result, json_output=args.json, path=args.file)
    # A failed validation is a real answer, not a crash: exit non-zero so a
    # script or CI step can gate on it, without an exception traceback.
    if result.get("status") != "pass":
        raise SystemExit(1)


def _print_result(result: dict, *, json_output: bool, path: str) -> None:
    if json_output:
        print(json.dumps(result, indent=2, sort_keys=True))
        return
    status = result.get("status", "unknown")
    elapsed = result.get("elapsed_ms")
    suffix = f" in {elapsed} ms" if elapsed is not None else ""
    print(f"{path}: {status}{suffix}")
    for diagnostic in result.get("diagnostics") or []:
        code = diagnostic.get("code", "")
        message = diagnostic.get("message", "")
        hint = diagnostic.get("fix_hint", "")
        where = _where(diagnostic)
        print(f"  [{code}] {where}{message}")
        if hint:
            print(f"    fix: {hint}")


def _where(diagnostic: dict) -> str:
    slide = diagnostic.get("slide_id") or ""
    line = diagnostic.get("line")
    parts = []
    if slide:
        parts.append(f"slide {slide}")
    if line:
        parts.append(f"line {line}")
    return f"{', '.join(parts)}: " if parts else ""
