from flask import Flask, render_template, jsonify, request
import json
import os

app = Flask(__name__)

# Helper
def load_data(filename):
    if os.path.exists(filename):
        with open(filename, 'r') as f:
            return json.load(f)
    return {}

# Frontend
@app.route('/')
def index():
    return render_template('index.html')

# API endpoints
@app.route('/api/daily-rotation', methods=['GET'])
def daily_rotation():
    return jsonify({"status": "success", "data": "daily_rotation_data_here"})

@app.route('/api/registry', methods=['GET'])
def get_registry():
    data = load_data('registry.json')
    return jsonify(data)

@app.route('/api/subnet/<int:subnet_id>', methods=['GET'])
def get_subnet(subnet_id):
    return jsonify({"subnet_id": subnet_id, "data": "subnet_details"})

@app.route('/api/mindmap/feedback', methods=['POST'])
def post_feedback():
    feedback = request.json
    return jsonify({"status": "received", "feedback": feedback})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 50745))
    app.run(host='0.0.0.0', port=port, debug=True)