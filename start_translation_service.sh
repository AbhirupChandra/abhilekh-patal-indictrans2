#!/bin/bash
# IndicTrans2 Translation Service — Stable launcher
#
# DEV (macOS): Uses waitress (no fork, MPS-safe)
# PROD (Linux): Uses gunicorn (fork + CPU = stable)
#
# Usage:  ./start_translation_service.sh
# Stop:   kill $(lsof -i :5002 -t)

cd "$(dirname "$0")/implementation_files"

echo "========================================"
echo "  IndicTrans2 Translation Service"
echo "========================================"

OS=$(uname -s)

if [ "$OS" = "Darwin" ]; then
    # macOS — Gunicorn fork() crashes MPS (Apple Silicon GPU).
    # Use waitress instead: thread-based, no forking, stable with MPS.
    echo "  Platform: macOS (using waitress)"
    echo "========================================"
    exec ../.venv/bin/waitress-serve \
        --host=0.0.0.0 \
        --port=5002 \
        --threads=1 \
        --channel-timeout=30 \
        --recv-bytes=65536 \
        indictrans2_translation_service:app
else
    # Linux — Gunicorn works perfectly (no MPS, CPU-only).
    echo "  Platform: Linux (using gunicorn)"
    echo "========================================"
    exec ../.venv/bin/gunicorn \
        --bind 0.0.0.0:5002 \
        --workers 2 \
        --threads 1 \
        --timeout 30 \
        --max-requests 500 \
        --max-requests-jitter 50 \
        --graceful-timeout 10 \
        --preload \
        --access-logfile - \
        --error-logfile - \
        --log-level info \
        indictrans2_translation_service:app
fi
