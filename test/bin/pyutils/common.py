#!/usr/bin/env python3

import os
import pathlib
import psutil
import sys
import subprocess
import time
import threading
from typing import List


PUSHD_DIR_STACK = []
JUNIT_LOGFILE = None
JUNIT_LOCK = threading.Lock()


def start_junit(groupdir):
    """Create a new junit file with the group name and timestampt header"""
    # Initialize the junit log file path
    global JUNIT_LOGFILE
    group = basename(groupdir)
    JUNIT_LOGFILE = os.path.join(get_env_var('IMAGEDIR'), "build-logs", group, "junit.xml")

    print_msg(f"Creating '{JUNIT_LOGFILE}'")
    # Create the output directory
    create_dir(os.path.dirname(JUNIT_LOGFILE))
    # Create a new junit file with a header
    delete_file(JUNIT_LOGFILE)
    timestamp = get_timestamp("%Y-%m-%dT%H:%M:%S")
    append_file(JUNIT_LOGFILE, f'''<?xml version="1.0" encoding="UTF-8"?>
<testsuite name="microshift-test-framework:{group}" timestamp="{timestamp}">''')


def close_junit():
    """Close the junit file"""
    global JUNIT_LOGFILE
    if not JUNIT_LOGFILE:
        raise Exception("Attempt to close junit without starting it first")
    # Close the unit
    append_file(JUNIT_LOGFILE, '</testsuite>')
    # Reset the junit log directory
    JUNIT_LOGFILE = None


def record_junit(object, step, status):
    """Add a message for the specified object and step with OK, SKIP or FAIL status.
    Recording messages is synchronized and it can be called from different threads.
    """
    try:
        # BEGIN CRITICAL SECTION
        JUNIT_LOCK.acquire()

        append_file(JUNIT_LOGFILE, f'<testcase classname="{object}" name="{step}">')
        # Add a message according to the status
        if status == "OK":
            pass
        elif status.startswith("SKIP"):
            append_file(JUNIT_LOGFILE, f'<skipped message="{status}" type="{step}-skipped" />')
        elif status.startswith("FAIL"):
            append_file(JUNIT_LOGFILE, f'<failure message="{status}" type="${step}-failure" />')
        else:
            raise Exception(f"Invalid junit status '{status}'")
        # Close the test case block
        append_file(JUNIT_LOGFILE, '</testcase>')
    except Exception:
        # Propagate the exception to the caller
        raise
    finally:
        # END CRITICAL SECTION
        JUNIT_LOCK.release()


def get_timestamp(format: str = "%H:%M:%S"):
    """Return a timestamp in the specified format with nanoseconds"""
    # Get current time in secs
    cts = time.time()
    # Extract seconds and nanoseconds
    secs = int(cts)
    nsecs = int((cts - secs) * 1_000_000_000)
    # Use time.strftime to format the time part
    time_str = time.strftime(format, time.localtime(secs))

    # Construct the final timestamp string with nanoseconds
    return f"{time_str}.{nsecs:09d}"


def print_msg(msg: str, file=sys.stderr):
    print(get_timestamp(), msg, file=file)


def get_env_var(var_name: str, def_val: str = None):
    """Get an environment variable or exit if not set."""
    value = os.environ.get(var_name)
    if value:
        return value
    if def_val:
        return def_val
    print_msg(f"Error: {var_name} environment variable not set.")
    sys.exit(1)


def run_command(command: List[str], dry_run: bool):
    """Run the command or print the command line depending on the dry run argument"""
    if dry_run:
        print_msg(f"[DRY RUN] {' '.join(command)}")
        return None

    print_msg(f"[RUN] {' '.join(command)}")
    return subprocess.run(command, check=True)


def run_command_in_shell(command: List[str], dry_run: bool = False,
                         stdout=subprocess.PIPE, stderr=sys.stderr):
    """Run the command through shell and return its standard output"""
    """If output file descriptors are specified, the appropriate output is redirected"""
    # Convert command to a string if necessary
    if isinstance(command, list):
        command = ' '.join(command)
    if dry_run:
        print_msg(f"[DRY RUN] {command}")
        return ""

    print_msg(f"[SHELL] {command}")
    # Run the command and return its output
    result = subprocess.run(
        command,
        check=True, shell=True, text=True,
        env=os.environ.copy(),
        stdout=stdout, stderr=stderr)
    return result.stdout.strip() if result.stdout else ""


def create_dir(dir: str):
    """Attempt recursive directory creation ignoring errors if it already exists"""
    path = pathlib.Path(dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def pushd(dir: str):
    """Change directory saving the current directory in the stack"""
    global PUSHD_DIR_STACK
    PUSHD_DIR_STACK.append(os.getcwd())
    os.chdir(dir)


def popd():
    """Restore the current directory from the stack"""
    if not PUSHD_DIR_STACK:
        raise Exception("Directory stack is empty")
    dir = PUSHD_DIR_STACK.pop()
    os.chdir(dir)


def read_file(file_path: str):
    """Read the file contents and return them to the caller"""
    with open(file_path, 'r') as file:
        content = file.read()
    return content


def append_file(file_path: str, content: str):
    """Append the specified content to a file"""
    with open(file_path, 'a') as file:
        file.write(content)


def delete_file(file_path: str):
    """Attempt file deletion ignoring errors when a file does not exist"""
    try:
        os.remove(file_path)
    except FileNotFoundError:
        pass


def basename(path: str):
    """Return a base name of the path"""
    return pathlib.Path(path).name


def find_subprocesses(ppid=None):
    """Find and return a list of all the sub-processes of a parent PID"""
    # Get current process if not specified
    if not ppid:
        ppid = psutil.Process().pid
    # Get all child process objects recursively
    children = psutil.Process(ppid).children(recursive=True)
    # Collect the child process IDs
    pids = []
    for child in children:
        pids.append(child.pid)
    return pids


def terminate_process(pid, wait=True):
    """Terminate a process, waiting for 10s until it exits"""
    try:
        proc = psutil.Process(pid)
        # Check if the process runs elevated
        if proc.uids().effective == 0:
            run_command(["sudo", "kill", "-TERM", f"{pid}"], False)
        else:
            proc.terminate()
        if not wait:
            return

        # Wait for process to terminate
        try:
            proc.wait(timeout=10)
        except psutil.TimeoutExpired:
            print_msg(f"The {pid} PID did not exit after 10s")
    except psutil.NoSuchProcess:
        # Ignore non-existent processes
        pass
    except Exception:
        # Propagate the exception to the caller
        raise
