"""Embed the pooled corpus with a local model, for the same two curves.

The document text is exactly the fields dotdiw matches on -- name words, the
directory, the description, the example titles -- so the only thing that
differs from the bm25 measurement is how the comparison is made. Leave-one-out
needs a separate document per example, with that example removed, or the test
only shows that an indexed string finds itself.

nomic-embed-text wants its task prefixes; documents and queries get theirs.
"""
import importlib.machinery, importlib.util, io, json, os, subprocess, sys

spec = importlib.util.spec_from_loader("dd", importlib.machinery.SourceFileLoader(
    "dd", "../dotdiw"))
dd = importlib.util.module_from_spec(spec); spec.loader.exec_module(dd)

S = os.environ.get("DOTDIW_SIM_ROOT",
    "./sim-root")
sys.path.insert(0, S)
from cover_sweep import NEG

POOL = S + "/pool"
MODEL = S + "/embedmodel/nomic.gguf"
NEGS = [t for v in NEG.values() for t in v]

def flat(s):
    return " ".join(str(s).split())

def doc_text(f, drop=None):
    ex = [e for k, e in enumerate(f["examples"]) if k != drop]
    return flat("%s %s %s %s" % (f["words"], f["where"], f["desc"], " ".join(ex)))

forms = dd.load_formulas(POOL)
texts, meta = [], []

for i, f in enumerate(forms):
    texts.append("search_document: " + doc_text(f))
    meta.append(("doc", i, None))
    for j in range(len(f["examples"])):
        texts.append("search_document: " + doc_text(f, drop=j))
        meta.append(("doc_loo", i, j))

for i, f in enumerate(forms):
    for j, ex in enumerate(f["examples"]):
        texts.append("search_query: " + flat(ex))
        meta.append(("pos", i, j))

for k, q in enumerate(NEGS):
    texts.append("search_query: " + flat(q))
    meta.append(("neg", k, None))

inp = S + "/embed_in.txt"
with io.open(inp, "w", encoding="utf-8") as fh:
    fh.write("\n".join(texts) + "\n")
print("%d texts to embed (%d formulas, %d leave-one-out docs, %d positives, %d negatives)"
      % (len(texts), len(forms),
         sum(1 for m in meta if m[0] == "doc_loo"),
         sum(1 for m in meta if m[0] == "pos"),
         sum(1 for m in meta if m[0] == "neg")))

out = subprocess.run(
    ["llama-embedding", "-m", MODEL, "-f", inp,
     "--embd-output-format", "json", "--pooling", "mean",
     "-c", "2048", "-b", "2048", "--embd-normalize", "2"],
    capture_output=True, text=True)
if out.returncode != 0:
    sys.stderr.write(out.stderr[-3000:])
    sys.exit(1)
data = json.loads(out.stdout)["data"]
assert len(data) == len(texts), (len(data), len(texts))
json.dump({"meta": meta, "vec": [d["embedding"] for d in data]},
          open(S + "/embed.json", "w"))
print("wrote %d vectors, dim %d" % (len(data), len(data[0]["embedding"])))
