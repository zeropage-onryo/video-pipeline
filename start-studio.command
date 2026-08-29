#!/bin/bash
# Starts the Zero Page Films pipeline server (Dev Studio + regular Studio share one process).
# Double-click this file in Finder, or run it from Terminal.
cd "/Users/iphone/Documents/PRODUCTION PIPLINE .GIT"
venv/bin/uvicorn app.main:app --reload --timeout-graceful-shutdown 3
