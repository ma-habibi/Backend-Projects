
"""********************************************
File: task_tracker.py
Author: Mahdi Habibi

Desc. :
    Task Tracker Program.
********************************************"""

import json
import sys
from datetime import datetime

# Read json into dict
PATH = "data/data.json"
with open(PATH, "r") as f:
    tasks = json.load(f)

def get_max_id() -> int:
    return len(tasks)

def print_task(task):
    """
    Writes task to stdout
    with specific format.
    """

    task_id = task["id"]
    task_desc = task["description"]
    print(f".{task_id}: {task_desc} - {task['status']}")

def run(args, error):
    """
    Runs the logic of the tasktracker.
    edit the json. put and return error.
    """
    
    match args.cmd:
        case "list":
            # If list is filtered
            if "status" in args:
                for task in tasks:
                    status = task["status"]
                    if status == args.status:
                        print_task(task)
            else:
                # Out all the items
                for task in tasks:
                    print_task(task)

        case "add":
            """
            add_task(create_task()),
            Create a dict and read write
            to json.
            """

            # Create task
            if not args.task_body:
                error.st = True
                error.msg = "Can't add an empty task"
                return error

            task = {"id": f"{get_max_id() + 1}",
                    "description": f"{args.task_body}",
                    "status": "todo",
                    "createdAt": f"{datetime.now().ctime()}",
                    "updatedAt": f"{datetime.now().ctime()}"}

            tasks.append(task)

            # Print report
            print(f"Task {task['description']} added."
                  f" (id = {task['id']})")

        case "update":
            if not args.id:
                error.st = True
                error.msg = f"Must especify id"
            else:
                new_body = args.new_task_body

                # Find by id - read in
                for task in tasks:
                    if int(args.id) == int(task['id']):
                        # Set new Body
                        task["description"] = new_body
                        task["updatedAt"] = datetime.now().ctime()

                        # Report to user
                        print(f"Updated \'{task['description']}\'"
                        f" to \'{new_body}\'")
                        return error

                # Reached end of tasks
                error.st = True
                error.msg = f"No task with the id {args.id}"

        case "delete":
            # Check
            i = int(args.id) - 1
            if i < 0 or i >= len(tasks):
                error.st = True
                error.msg = f"No task with the id: {args.id}"
                return error

            # Delete and shift
            print(tasks[i])
            tasks.pop(i)
            print(tasks)
            for task in tasks[i:]: # Shift ids
                task["id"] = str(int(
                    task["id"]) - 1)

        case "mark-in-progress" | "mark-done":
            if not args.id:
                error.st = True
                error.msg = f"Must especify id"

            else:
                status = "in-progress" if args.cmd ==\
                        "mark-in-progress" else "done"

                # Update status
                for task in tasks:
                    if int(args.id) == int(task['id']):
                        task["status"] = status
                        return error

                error.st = True
                error.msg = f"No task with the id: {args.id}"
                return error

        case _:
            error.st = True
            error.msg = f"Ivanlid argument: {args.cmd}"

    return error

def task_tracker(args, error):
    """
    Runs the program by 
    making a call to run
    obtain and reuturn the
    status and msg in error.
    """

    error = run(args, error)
    # Write dict into json
    with open(PATH, 'w') as f:
        json.dump(tasks, f, indent=4)

    return error
