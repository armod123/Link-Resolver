"""
Link Resolver Web Server
Flask app with Server-Sent Events for real-time resolution progress.
"""

import asyncio
import json
import threading
import queue
import uuid
from flask import Flask, render_template, request, jsonify, Response
from resolver import resolve_link, ResolveResult

app = Flask(__name__)

# Store active resolution tasks
tasks: dict[str, dict] = {}


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/resolve", methods=["POST"])
def start_resolve():
    """Start a link resolution task."""
    data = request.get_json()
    url = data.get("url", "").strip()

    if not url:
        return jsonify({"error": "No URL provided"}), 400

    # Ensure URL has protocol
    if not url.startswith("http"):
        url = "https://" + url

    task_id = str(uuid.uuid4())[:8]
    message_queue = queue.Queue()

    tasks[task_id] = {
        "url": url,
        "status": "running",
        "queue": message_queue,
        "result": None,
    }

    # Run resolution in a background thread
    def run_in_thread():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def callback(msg):
            message_queue.put({"type": "step", "message": msg})

        try:
            result = loop.run_until_complete(resolve_link(url, callback=callback))
            tasks[task_id]["result"] = result
            tasks[task_id]["status"] = "done"
            message_queue.put({
                "type": "done",
                "success": result.success,
                "final_url": result.final_url,
                "elapsed": result.elapsed_seconds,
                "error": result.error,
            })
        except Exception as e:
            tasks[task_id]["status"] = "error"
            message_queue.put({"type": "error", "message": str(e)})
        finally:
            loop.close()

    thread = threading.Thread(target=run_in_thread, daemon=True)
    thread.start()

    return jsonify({"task_id": task_id})


@app.route("/stream/<task_id>")
def stream(task_id):
    """SSE endpoint for real-time resolution progress."""
    if task_id not in tasks:
        return jsonify({"error": "Task not found"}), 404

    def generate():
        task = tasks[task_id]
        while True:
            try:
                msg = task["queue"].get(timeout=60)
                yield f"data: {json.dumps(msg)}\n\n"
                if msg.get("type") in ("done", "error"):
                    break
            except queue.Empty:
                # Send keepalive
                yield f"data: {json.dumps({'type': 'keepalive'})}\n\n"

        # Clean up task after streaming is done
        if task_id in tasks:
            del tasks[task_id]

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


if __name__ == "__main__":
    import os

    # The watchdog reloader monitors all imported modules for changes.
    # Playwright spawns a Node.js subprocess that touches files in
    # site-packages, which triggers a spurious reload and kills the
    # browser mid-resolution (EPIPE error).  Disabling the reloader
    # prevents this; debug mode still gives nice tracebacks.
    app.run(
        debug=True,
        host="0.0.0.0",
        port=5000,
        threaded=True,
        use_reloader=False,
    )
