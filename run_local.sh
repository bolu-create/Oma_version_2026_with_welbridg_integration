#!/usr/bin/env bash
# Local development only: run Oma inside WSL (Ubuntu) on http://localhost:5000.
#
#   bash run_local.sh
#
# Loads .env BEFORE importing the app. Several service modules read API keys
# at import time (functions_for_emails builds its LLM client on import), which
# works on Railway because the variables are already in the environment, but
# locally they have to come from .env first.
#
# Uses the Linux virtualenv at ~/oma-venv (Python 3.12). Not used in deployment;
# Railway runs the Procfile.

cd "$(dirname "$0")" || exit 1
exec "$HOME/oma-venv/bin/python" -c '
from dotenv import load_dotenv
load_dotenv(".env")
from app import create_app
create_app().run(host="0.0.0.0", port=5000, threaded=True, use_reloader=False)
'
