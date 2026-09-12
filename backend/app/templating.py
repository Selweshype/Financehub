"""Shared Jinja2 environment.

Every module previously constructed ``Jinja2Templates(directory="app/templates")``
with a path relative to the process working directory, so templates resolved
only when the app happened to be started from ``backend/``.  Resolving the
directory from this module's own location makes it independent of cwd.

Autoescaping is on by default in Starlette's Jinja2Templates, which is what
keeps transaction descriptions and other bank-supplied strings from becoming
stored XSS — do not disable it.
"""
from __future__ import annotations

import os

from fastapi.templating import Jinja2Templates

TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")

templates = Jinja2Templates(directory=TEMPLATES_DIR)
