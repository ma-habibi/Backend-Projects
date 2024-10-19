"""
File: main.py
Author: Mahdi Habibi

Desc:
    Runs caching server and client on
    parallel threads.
"""

# Built-in
import sys
import os
import time
import json

# Set up relative path
sys.path.insert(0, 
                os.path.abspath(
                    os.path.join(
                        os.path.dirname(
                            __file__), 
                        "src")))

# Locals
from args import args
from server.server import run

# Third party
from requests import post

def fetch(args):
    """
    Send a POST req to the internal server
    to GET cached data from origin.
    """

    # Set internal server address
    localhost = f"http://127.0.0.1:{args.port}"

    # Set origin in a json to POST
    json_origin = {"origin": f"{args.origin}"}

    # POST send origin data to internal server
    r = post(localhost, json=json_origin)
    r.raise_for_status()

    return r.text

if __name__ == "__main__":
    def write_cache(table):
        with open("data.json", mode="w") as f:
            json.dump(table, f, indent=4)

    def main():
        a = args()

        if a.clear_cache:
            write_cache(dict()) # Write empty json
            return 0

        # Load cached table from json
        cached = dict()
        with open(file="data.json", mode="r") as f:
            try:
                cached = json.load(f)
            except:
                pass

        # Lookup, return cached if exist
        if a.origin in cached:
            return {'X-Cached': 'HIT',
                   'data': f'{cached[a.origin]}'}

        # Run server and fetch on parallel processes
        pid = os.fork()
        if pid == 0:
            # Run the server on args.port
            run(a.port)
        else:
            time.sleep(2) # Make sure server is initiated

            # Get cached and put error
            cached[a.origin] = fetch(a)
            write_cache(cached)

            return {'X-Cached': 'MISS',
                   'data': f'{cached[a.origin]}'}

        return 0

    print(main())