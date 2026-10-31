"""Score a formula by its closest part, not by the average of all of them.

The first embedding run mean-pooled one string per formula: name, directory,
description and every example concatenated. That dilutes -- a title close to
one example is averaged against three it has nothing to do with. Embed each
part on its own instead and score the formula by its best-matching part, which
is what the examples are for.
"""
import os
import importlib.machinery, importlib.util, io, json, subprocess, sys

spec = importlib.util.spec_from_loader("dd", importlib.machinery.SourceFileLoader(
    "dd", "../dotdiw"))
dd = importlib.util.module_from_spec(spec); spec.loader.exec_module(dd)
S = os.environ.get("DOTDIW_SIM_ROOT",
    "./sim-root")
sys.path.insert(0, S)
from cover_sweep import NEG

POOL, MODEL = S + "/pool", S + "/embedmodel/nomic.gguf"
flat = lambda s: " ".join(str(s).split())
forms = dd.load_formulas(POOL)
ALL = [t for v in NEG.values() for t in v]
DROP = {v[0] for v in NEG.values()}
KEEP = [t for t in ALL if t not in DROP]

texts, meta = [], []
for i, f in enumerate(forms):
    texts.append("search_document: " + flat("%s. %s" % (f["words"], f["desc"])))
    meta.append(("desc", i, None))
    for j, ex in enumerate(f["examples"]):
        texts.append("search_document: " + flat(ex))
        meta.append(("ex", i, j))
for i, f in enumerate(forms):
    for j, ex in enumerate(f["examples"]):
        texts.append("search_query: " + flat(ex))
        meta.append(("pos", i, j))
for k, q in enumerate(KEEP):
    texts.append("search_query: " + flat(q))
    meta.append(("neg", k, None))

inp = S + "/embed_in2.txt"
io.open(inp, "w", encoding="utf-8").write("\n".join(texts) + "\n")
print("%d texts (%d descriptions, %d example documents, %d positives, %d negatives)"
      % (len(texts), len(forms), sum(1 for m in meta if m[0] == "ex"),
         sum(1 for m in meta if m[0] == "pos"), len(KEEP)))
r = subprocess.run(["llama-embedding", "-m", MODEL, "-f", inp,
                    "--embd-output-format", "json", "--pooling", "mean",
                    "-c", "2048", "-b", "2048", "--embd-normalize", "2"],
                   capture_output=True, text=True)
if r.returncode != 0:
    sys.stderr.write(r.stderr[-2000:]); sys.exit(1)
vec = [d["embedding"] for d in json.loads(r.stdout)["data"]]
json.dump({"meta": meta, "vec": vec}, open(S + "/embed_max.json", "w"))
print("wrote %d vectors" % len(vec))
