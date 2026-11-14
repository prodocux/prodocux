"""Single-request subprocess for the EML admission boundary."""

import json
import sys
from importlib import import_module
from pathlib import Path
from types import ModuleType

# Load the adjacent parser modules without running the public intake package
# initializer, which imports unrelated Office and PDF dependencies.
package = ModuleType("_prodocux_eml")
package.__path__ = [str(Path(__file__).resolve().parent)]
sys.modules[package.__name__] = package

MAX_TEXT_SOURCE = import_module("_prodocux_eml.structured").MAX_TEXT_SOURCE
project = import_module("_prodocux_eml.structured_view").project


def main():
    payload = sys.stdin.buffer.read(MAX_TEXT_SOURCE + 1)
    try:
        result = project("message.eml", payload)
    except ValueError as exc:
        message = str(exc)
        code = (
            message
            if message.startswith(("EML_", "HTML_", "INTAKE_"))
            else "EML_PARSE_REJECTED"
        )
        print(json.dumps({"error": code}))
        return
    print(json.dumps({"projection": result}, ensure_ascii=True))


if __name__ == "__main__":
    main()
