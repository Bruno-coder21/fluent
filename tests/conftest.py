"""Load the plugin directory as the package ``fluent``, the way Hermes loads it.

Hermes imports a plugin's ``__init__.py`` with ``spec_from_file_location`` and
``submodule_search_locations=[plugin_dir]``. Doing the same here means the tests do
not depend on the name of the folder the repo was cloned into.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"

if "fluent" not in sys.modules:
    _spec = importlib.util.spec_from_file_location(
        "fluent", ROOT / "__init__.py", submodule_search_locations=[str(ROOT)]
    )
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules["fluent"] = _mod
    _spec.loader.exec_module(_mod)
