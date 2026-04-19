from __future__ import annotations

from pathlib import Path


FIXTURES_DIR = Path(__file__).parent / "fixtures"


def read_fixture(*parts: str) -> str:
    return (FIXTURES_DIR / Path(*parts)).read_text()
