#!/bin/bash
cd "$(dirname "$0")"
command -v python3 >/dev/null || { echo "Python 3 is not installed. Get it from python.org"; read -r; exit 1; }
[ -d .venv ] || python3 -m venv .venv
source .venv/bin/activate
python -m pip install -q -r requirements.txt
python -m streamlit run app.py
