import sys
from pathlib import Path

# Permet à Vercel (cwd = racine projet) de retrouver le module pyserver.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pyserver.app import app  # noqa: E402  (FastAPI ASGI app exporté pour le runtime Vercel)
