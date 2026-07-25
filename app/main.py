"""
Page Pulse — Flask API + static frontend.

Deliberately thin: request parsing, error-to-status-code mapping, and
serving the static frontend. All real logic lives in audit.py so it can be
unit tested without spinning up Flask or hitting the network.
"""
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

from .audit import AuditError, fetch_and_analyze

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

app = Flask(__name__, static_folder=str(STATIC_DIR), static_url_path="")


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/api/health")
def health():
    return jsonify({"status": "ok"})


@app.post("/api/audit")
def audit():
    body = request.get_json(silent=True) or {}
    url = body.get("url") or request.args.get("url")

    try:
        report = fetch_and_analyze(url)
    except AuditError as exc:
        # Every expected failure mode returns clean JSON, not a stack trace.
        return jsonify({"error": exc.message}), exc.status_code
    except Exception as exc:  # noqa: BLE001 - last-resort safety net
        # Anything truly unexpected still returns JSON, never a 500 crash
        # page. Logged server-side in a real deployment.
        app.logger.exception("Unhandled error auditing %s", url)
        return jsonify({"error": "Something went wrong analyzing that URL."}), 500

    return jsonify(report.to_dict()), 200


if __name__ == "__main__":
    app.run(debug=True, port=5000)
