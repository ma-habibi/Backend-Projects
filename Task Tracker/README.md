The application runs from the command line,
accept user actions and inputs as arguments,
and store the tasks in a JSON file.

A solution to the project at https://roadmap.sh/projects/task-tracker written in python using procedural paradigm.

`main.py` Obtains arguments from `args.py` using python <a href="https://docs.python.org/3/library/argparse.html"> built-in module module </a>. Then uses the module `task_tracker.py` 
to run the program logic and obtain an error.

### HOW TO RUN
<b> Note: Use python3.10 or later. </b>

Navigate to Directory:
```sh
cd Task\ Tracker
```

Examples:
```sh
# Adding a new task
python main.py add "Buy groceries"
# Output: Task added successfully (ID: 1)

# Updating and deleting tasks
python main.py update 1 "Buy groceries and cook dinner"
python main.py delete 1

# Marking a task as in progress or done
python main.py mark-in-progress 1
python main.py mark-done 1

# Listing all tasks
python main.py list

# Listing tasks by status
python main.py list done
python main.py list todo
python main.py in-progress
```
