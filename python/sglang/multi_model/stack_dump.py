"""Opt-in Python stack dumps on SIGUSR1, to see where every process is stuck during a freeze (F1.1, T1).

With PRISM_STACK_DUMPS=1, a process that calls enable_stack_dumps() dumps all its threads' stacks to
/dev/shm/prism_stack_<user>_<pid>.txt each time it receives SIGUSR1 (faulthandler, so it works even when the
process is blocked in a C call), and lists itself in /dev/shm/prism_stack_<user>_<pid>.pid so that
polyaxon/run_examples.sh (PRISM_STACK_DUMP_AT) knows which processes it can signal. Off by default: SIGUSR1 keeps
its default action (terminate) in processes that did not register.
"""
import faulthandler
import os
import signal

_files = []  # keep the dump files open for the life of the process


def enable_stack_dumps(name: str):
    if os.environ.get("PRISM_STACK_DUMPS", "0") != "1":
        return
    prefix = f"/dev/shm/prism_stack_{os.environ.get('USER', 'prism')}_{os.getpid()}"
    f = open(prefix + ".txt", "a")
    f.write(f"# {name} pid {os.getpid()}\n")
    f.flush()
    _files.append(f)
    faulthandler.register(signal.SIGUSR1, file=f, all_threads=True)
    with open(prefix + ".pid", "w") as p:
        p.write(name)
