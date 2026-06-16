import json
import os

from flask import Flask, jsonify, render_template, request

app = Flask(__name__)


def load_data(filename):
    if os.path.exists(filename):
        with open(filename, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/daily-rotation", methods=["GET"])
def daily_rotation():
    return jsonify({"status": "success", "data": "daily_rotation_data_here"})


@app.route("/api/registry", methods=["GET"])
def get_registry():
    data = load_data("config/registry.json")
    return jsonify(data)


@app.route("/api/subnet/<subnet_id>", methods=["GET"])
def get_subnet(subnet_id):
    data = load_data("config/registry.json")
    subnet_data = data.get(str(subnet_id))
    if subnet_data is None:
        return jsonify({"error": "Subnet not found"}), 404
    return jsonify({"subnet_id": subnet_id, "data": subnet_data})


@app.route("/api/mindmap/feedback", methods=["POST"])
def post_feedback():
    feedback = request.get_json(silent=True)
    return jsonify({"status": "received", "feedback": feedback})


@app.route("/health", methods=["GET"])
def health():
    return "OK"


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 50745))
    app.run(host="0.0.0.0", port=port, debug=True)
