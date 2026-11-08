"""Single-request subprocess for the EML admission boundary."""

import json
import sys
from pathlib import Path

# Isolated Python ignores PYTHONPATH. Import only the adjacent package.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from prodocux_kernel.intake.documents.structured import MAX_TEXT_SOURCE
from prodocux_kernel.intake.documents.structured_view import project


def main():
    payload = sys.stdin.buffer.read(MAX_TEXT_SOURCE + 1)
    try:
        result = project("message.eml", payload)
    except ValueError as exc:
        message = str(exc)
        code = message if message.startswith(("EML_", "HTML_", "INTAKE_")) else "EML_PARSE_REJECTED"
        print(json.dumps({"error": code}))
        return
    print(json.dumps({"projection": result}, ensure_ascii=True))


if __name__ == "__main__":
    main()
