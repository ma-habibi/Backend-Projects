import sys
import os

sys.path.insert(0, 
                os.path.abspath(
                    os.path.join(
                        os.path.dirname(
                            __file__), 
                        "src")))

import task_tracker
from args import __args


# Error for task_tracker
OK: bool = False
class Error:
    """
    Custom error type.
    """

    st: bool = OK
    msg: str

def main():
    e = Error()
    task_tracker.task_tracker(__args(), e)
    if e.st != OK:
        print(f"Error: {e.msg}")
        sys.exit(1)

    sys.exit(0)

if __name__ == "__main__":
    main()
