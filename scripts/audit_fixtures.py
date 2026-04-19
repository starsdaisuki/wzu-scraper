"""Check test fixtures for accidental sensitive data."""

from __future__ import annotations

import re
import sys
from pathlib import Path


FIXTURES_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
DENY_PATTERNS = {
    "student_id": re.compile(r"\b\d{11}\b"),
    "password_field": re.compile(r"password=", re.IGNORECASE),
    "cookie_name": re.compile(r"\b(?:SOURCEID_TGC|JSESSIONID|SESSION)\b", re.IGNORECASE),
    "cookie_header": re.compile(r"\bSet-Cookie\b", re.IGNORECASE),
    "ticket": re.compile(r"ticket=ST-", re.IGNORECASE),
    "uid_query": re.compile(r"uid=\d{8,}", re.IGNORECASE),
}


def main() -> int:
    violations: list[str] = []

    for path in sorted(FIXTURES_DIR.rglob("*")):
        if not path.is_file():
            continue

        text = path.read_text()
        for label, pattern in DENY_PATTERNS.items():
            if pattern.search(text):
                violations.append(f"{path}: matched {label}")

    if violations:
        print("Fixture audit failed:")
        for violation in violations:
            print(f"  - {violation}")
        return 1

    print("Fixture audit passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
