"""Run registry mutants (`qa_mutation_runner.M`) in a COPY of the tree, never the live one.

`qa_mutation_runner.py` mutates the working tree and restores by `git checkout`, so it loses uncommitted work
and loads mutants into any scheduled job that imports the repo meanwhile. This applies each entry whose name
starts with one of the given prefixes to `<copy>` only, runs the tests there, prints KILLED / SURVIVED, and
restores the file byte for byte.

    tar --exclude=__pycache__ -cf - newscrawler scripts tests __main__.py pytest.ini EXPERIMENTS.md | tar -x -C <copy>
    venv\\Scripts\\python.exe scripts\\experiments\\run_registry_mutants_in_copy.py <copy> sys171_ sys172_ ...

MUTANT_TESTS overrides the tests (default: the four arc suites). Exit 1 when any mutant survives or is not found.
"""
import ast
import os
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PY = os.path.join(REPO, "venv", "Scripts", "python.exe")
ARC_TESTS = ("tests/unit/test_story_arc.py tests/unit/test_source_check.py tests/unit/test_arc_style.py "
             "tests/unit/test_replay_story_arcs.py tests/unit/test_causal_check.py")   # SYS-152 added the fifth


def registry(root: str) -> list:
    path = os.path.join(root, "scripts", "experiments", "qa_mutation_runner.py")
    tree = ast.parse(open(path, encoding="utf-8").read())
    node = next(n for n in tree.body
                if isinstance(n, ast.Assign) and any(getattr(t, "id", None) == "M" for t in n.targets))
    return ast.literal_eval(node.value)


def main(root: str, prefixes: list) -> int:
    tests = os.environ.get("MUTANT_TESTS", ARC_TESTS).split()
    scratch = tempfile.mkdtemp(prefix="registry_mutants_")
    env = dict(os.environ, VECTOR_DB_NAME_L1=os.path.join(scratch, "NOPE_L1"),
               VECTOR_DB_NAME_L2=os.path.join(scratch, "NOPE_L2"), POSTGRES_DB_PORT="1", TELEGRAM_BOT_TOKEN="",
               PYTHONDONTWRITEBYTECODE="1")
    tally = {}
    for name, path, old, new in registry(root):
        if not name.startswith(tuple(prefixes)):
            continue
        p = os.path.join(root, path)
        original = open(p, "rb").read()
        src = original.decode("utf-8")
        o, n = (old, new) if src.count(old) == 1 else (old.replace("\n", "\r\n"), new.replace("\n", "\r\n"))
        if src.count(o) != 1:
            verdict, tail = "NOT FOUND", [f"{src.count(o)} matches"]
        else:
            try:
                open(p, "wb").write(src.replace(o, n).encode("utf-8"))
                r = subprocess.run([PY, "-m", "pytest", *tests, "-q", "-p", "no:cacheprovider"], cwd=root, env=env,
                                   capture_output=True, text=True, encoding="utf-8", errors="replace")
                verdict = "SURVIVED" if r.returncode == 0 else "KILLED"
                tail = [line for line in r.stdout.splitlines() if " passed" in line or " failed" in line][-1:]
            finally:
                open(p, "wb").write(original)
        print(f"{name}: {verdict} {tail}", flush=True)
        tally[verdict] = tally.get(verdict, 0) + 1
    print(tally)
    return 0 if set(tally) <= {"KILLED"} and tally else 1


if __name__ == "__main__":
    if os.path.abspath(sys.argv[1]) == REPO:
        sys.exit("refusing to mutate the live tree: pass a copy")
    sys.exit(main(sys.argv[1], sys.argv[2:]))
