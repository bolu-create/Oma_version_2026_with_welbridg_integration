"""
The modules in this package import each other by bare module name
(`from db import *`, `from functions_1 import *`, ...). Those names only
resolve when the interpreter's working directory is this folder, which is how
these files get run locally.

Under gunicorn the working directory is the project root, so the bare names are
not importable and `create_app()` dies at import time with
`ModuleNotFoundError: No module named 'functions_for_emails'`.

Putting this directory on sys.path keeps the flat imports working from any
working directory, so the same files run locally and in deployment.
"""

import os
import sys

_SERVICES_DIR = os.path.dirname(os.path.abspath(__file__))

if _SERVICES_DIR not in sys.path:
    sys.path.insert(0, _SERVICES_DIR)
