import argparse
import sys

def __args():
    """
    Initialize args: read user input
    and returns a <argparse.Namespace>.
    """

    parser = argparse.ArgumentParser(
            prog="Task Tracker CLI",
            description=" track and manage your tasks")

    # Get cmd
    parser.add_argument("cmd",
                        choices=["add", "list",
                                 "update", "delete",
                                 "mark-in-progress",
                                 "mark-done"])
    if len(sys.argv) < 2:
      parser.print_help()
      exit(0)

    if sys.argv[1] == "list" and len(sys.argv) > 2:
        # Get Status
        parser.add_argument("status",
                            choices=["in-progress",
                                     "todo", "done"])

    if sys.argv[1] == "add":
        if len(sys.argv) < 2:
            print("Task can not be empty!")
        # Get Status
        parser.add_argument("task_body",
                            nargs="?",
                            help="The body of the Task")

    else:
        # Get id
        parser.add_argument("id",
                            nargs="?",
                            help="ID of the task")

        if sys.argv[1] == "update":
            parser.add_argument("new_task_body",
                                nargs="?",
                                help="The updated body "
                                "of the Task")
    # Parse
    args = parser.parse_args()

    return parser.parse_args()
