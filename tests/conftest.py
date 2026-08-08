"""Import the Streamlit app once, in bare mode, for the pure-function tests.

Nothing here touches the network or Earth Engine: every test in this suite covers logic
that runs entirely in-process. The engine calls are deliberately left to manual
verification against the live services.
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
warnings.filterwarnings("ignore")


@pytest.fixture(scope="session")
def omnisite():
    import app

    return app
