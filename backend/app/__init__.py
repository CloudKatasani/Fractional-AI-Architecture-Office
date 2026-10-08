"""Fractional AI Architecture Office — backend package."""

import sys
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parents[2])
if _ROOT not in sys.path:  # make the data_gen package (catalogs, loaders) importable from the backend
    sys.path.append(_ROOT)
