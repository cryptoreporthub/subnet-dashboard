from flask import Flask, render_template
import os

app = Flask(__name__)

@app.route('/')
def index():
    return render_template('index.html')

if __name__ == '__main__':
    # Use port 50745 or 58658 as specified in the runtime info, or default to 5000
    port = int(os.environ.get('PORT', 50745))
    app.run(host='0.0.0.0', port=port, debug=True)