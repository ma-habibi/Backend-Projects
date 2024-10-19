import argparse
import sys

def args():
    """
    Initialize args: read user input
    and returns a <argparse.Namespace>.
    """

    parser = argparse.ArgumentParser(
            prog="Caching Proxy",
            description="A caching server that\
                caches responses from other servers.")

    # Port
    parser.add_argument("-p", "--port", type=int,
                        help="is the port on which the caching proxy server will run.")
    # Origin
    parser.add_argument("-o", "--origin", type=str,
                        help="is the URL of the server to which the requests will be\
                        forwarded.")
    # Clear chache
    parser.add_argument('--clear-cache', action='store_true',
                        help="Clear the cache if passed")

    # Parse and return
    return parser.parse_args()
