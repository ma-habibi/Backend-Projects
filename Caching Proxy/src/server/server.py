"""
File: server.py
Author: Mahdi Habibi

Desc:
    server: use Flask
    to create a server on localhost
    listen for request, fetch
    and return data.
"""

from flask import Flask, request
import requests

app = Flask(__name__)

cache = dict()

@app.route("/", methods=["POST"])
def index():
    # Get the origin arg.
    json_res = request.get_json()
    origin = json_res.get("origin")

    # Get data and return in json
    res = requests.get(origin)
    res.raise_for_status()

    return res.json()

def run(port):
    """
    Serve on port.
    """

    app.run(debug=True, port=port)