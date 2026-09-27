import sys
from pathlib import Path

# Make the project root importable so "from app.config import ..." works
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.main import app  # noqa: E402