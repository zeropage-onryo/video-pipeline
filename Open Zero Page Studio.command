#!/bin/bash
# Double-click this from Finder to launch the Zero Page studio.
# It starts the local server from wherever this file lives and opens
# the Studio page in your browser. Close the Terminal window (or Ctrl-C)
# to stop the server.
cd "$(dirname "$0")" || exit 1

if [ ! -x "venv/bin/uvicorn" ]; then
  echo "No venv found here. First-time setup, from this folder:"
  echo "  python3 -m venv venv && venv/bin/pip install -r requirements.txt && venv/bin/pip install -e ."
  echo
  read -r -p "Press return to close."
  exit 1
fi

echo "Starting Zero Page Studio…  (close this window to stop)"
# open the browser once the server has had a moment to bind the port
( sleep 2 && open "http://127.0.0.1:8000/studio" ) &
exec venv/bin/uvicorn app.main:app --reload
