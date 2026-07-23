"""Ensures the repo root is importable so tests can `from tests import ...`
and `import src...` regardless of the invocation directory."""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
