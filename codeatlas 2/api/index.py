"""Vercel serverless entrypoint: exposes the CodeAtlas Flask app.

Vercel's Python runtime imports this file and serves the ``app`` object.
``requirements.txt`` at the project root is installed automatically.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from codeatlas.app import app  # noqa: E402  (must come after sys.path fix)

# Vercel looks for `app` in this module.
