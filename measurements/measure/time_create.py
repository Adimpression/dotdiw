"""How long the create path takes, and how much of it is dotdiw's own.

Ten runs of `dotdiw create` in a throwaway repository adopted under an
isolated home, then ten of the bare tracker's create in the same tracker, so
that the difference is dotdiw's part: the match, the declaration, the check,
and from 0.5.0 the door. The law is one second for the whole, measured on an
idle machine; a sample taken while anything else runs is load, not a
measurement. The numbers are in ../README.md.

    python3 -I measure/time_create.py [path/to/dotdiw] [-n RUNS]

Run from `measurements/`; the default is ../dotdiw. bd must be on PATH.
"""
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time

argv = sys.argv[1:]
runs = 10
if "-n" in argv:
    i = argv.index("-n")
    runs = int(argv[i + 1])
    del argv[i:i + 2]
DOTDIW = os.path.abspath(argv[0] if argv else "../dotdiw")
BD = shutil.which("bd")
assert BD, "bd is not on PATH"

home = tempfile.mkdtemp(prefix="time-home-")
repo = tempfile.mkdtemp(prefix="time-repo-")
env = dict(os.environ, HOME=home)
env.pop("BEADS_DIR", None)
env.pop("DOTDIW_WITNESS", None)


def git(*args):
    subprocess.run(["git", "-C", repo] + list(args), capture_output=True, check=True)


def timed(cmd, title):
    out = []
    for i in range(runs):
        t = time.perf_counter()
        p = subprocess.run(cmd + ["%s %d" % (title, i)], cwd=repo, env=cmd_env[cmd[0]],
                           capture_output=True, text=True)
        out.append(time.perf_counter() - t)
        assert p.returncode == 0, p.stdout + p.stderr
    return out


def report(label, times):
    print("%s: median %.3f s, min %.3f, max %.3f (%d runs)"
          % (label, statistics.median(times), min(times), max(times), len(times)))


git("init", "-q")
git("config", "user.email", "t@example.invalid")
git("config", "user.name", "t")
git("config", "beads.role", "maintainer")
subprocess.run([sys.executable, "-I", DOTDIW, "init", "--prefix", "tm"], cwd=repo, env=env,
               capture_output=True, check=True)
key = subprocess.run(["git", "-C", repo, "config", "--local", "--get", "dotdiw.workspace"],
                     capture_output=True, text=True).stdout.strip()
cmd_env = {sys.executable: env,
           BD: dict(env, BEADS_DIR=os.path.join(home, ".dotdiw", key, ".beads"))}
try:
    print("dotdiw at %s" % DOTDIW)
    dotdiw = timed([sys.executable, "-I", DOTDIW, "create"], "probe")
    bare = timed([BD, "create"], "bare")
    report("dotdiw create", dotdiw)
    report("bd create alone", bare)
    print("dotdiw's own part: %.3f s (median less median)"
          % (statistics.median(dotdiw) - statistics.median(bare)))
finally:
    shutil.rmtree(home, True)
    shutil.rmtree(repo, True)
