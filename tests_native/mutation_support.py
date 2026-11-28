"""Pinned mutmut 3 test support for actual MCP subprocesses, never runtime hooks."""

import os
from pathlib import Path


def prepare_mutation_child(environment):
    if "MUTANT_UNDER_TEST" not in environment:
        return ""
    import librus_mcp

    # Why: a `python -c` child misses mutmut's sys.path, so it must import the mutants.
    source = Path(librus_mcp.__file__).resolve().parents[1]
    if source.parent.name != "mutants":
        raise RuntimeError("mutation child must use the disposable instrumented source")
    environment["PYTHONPATH"] = str(source)
    if environment["MUTANT_UNDER_TEST"] != "stats":
        return ""
    return """import atexit, json, os
from pathlib import Path
import mutmut
def save_mutation_hits():
    path = Path(os.environ['NATIVE_MUTATION_REPORT_DIR']) / (str(os.getpid()) + '.json')
    path.write_text(json.dumps(sorted(mutmut._stats)), encoding='utf-8')
atexit.register(save_mutation_hits)
"""


def mutation_is_collecting():
    return os.environ.get("MUTANT_UNDER_TEST") == "stats"
