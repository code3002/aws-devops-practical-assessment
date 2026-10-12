from datetime import datetime, timezone
from flask import Flask, jsonify, render_template_string

app = Flask(__name__)

HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>AWS EKS Python Time App</title>
</head>
<body>
    <h1>Python Application Running on AWS EKS</h1>
    <h2 id="clock">Loading...</h2>

    <script>
        async function updateTime() {
            const response = await fetch('/time');
            const data = await response.json();
            document.getElementById('clock').innerText = data.time;
        }

        updateTime();
        setInterval(updateTime, 1000);
    </script>
</body>
</html>
"""

@app.get("/")
def index():
    return render_template_string(HTML)

@app.get("/time")
def time():
    return jsonify(time=datetime.now(timezone.utc).isoformat())

@app.get("/health")
def health():
    return jsonify(status="healthy")
