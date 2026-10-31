"""A fourth state: a project that has adopted all of this, given work none of
its formulas covers.

The first three states cannot test capture. Every live run's job was covered by
a formula -- by construction, so that discovery had something to find -- and 22
of the 30 create titles the live runs actually typed retrieved one. Authoring a
formula was never the right move, so measuring zero of them says nothing.
This state is the one where it is: real work, several steps, repeatable, and
outside the formula set.
"""
import os, shutil, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build3, domains3

S = build3.S
RUNS = S + "/runs4"

UNCOVERED = {
 "ramen-shop":    "Hire and train a new kitchen hand. We have had three leave in a year and every time it is a scramble.",
 "paws-shelter":  "Run a weekend fundraising open day at the shelter next month.",
 "tinybill":      "Someone has reported a security vulnerability in the amount parser, privately, by email. Handle it.",
 "edgeops":       "Bring a new region, eu-central-1, into the fleet.",
 "corpsec":       "The company is moving office. Change the registered office address.",
 "vinyl-press":   "A new label, Coldharbour, wants to put work through us. Take them on as a customer.",
 "clinic-rota":   "A patient has put in a written complaint about a missed diagnosis. Take it through to a response.",
 "seed-bank":     "CAL-01882 is down to 140 seeds in store, below the distribution threshold. Regenerate it.",
 "tidepool":      "The quarterly hydrographic station data refresh is due. Do it.",
 "grange-farm":   "The sprayer needs its NSTS test and both operator certificates are up for renewal.",
 "archive-fonds": "A freedom of information request has come in about the 1974 boundary review papers. Answer it.",
}

if __name__ == "__main__":
    projects = build3.OLD + list(domains3.NEW)
    shutil.rmtree(RUNS, ignore_errors=True)
    os.makedirs(RUNS)
    rows = []
    for i, proj in enumerate(projects, 34):
        if proj in build3.OLD:
            files, forms = build3.read_old(proj)
        else:
            d = domains3.NEW[proj]
            files, forms = dict(d["files"]), dict(d["formulas"])
        rid = "r%02d" % i
        root = "%s/%s/%s" % (RUNS, rid, proj)
        build3.build(root, "live", files, forms)
        rows.append((rid, proj, "uncovered", root))
    with open(S + "/runmap4.tsv", "w") as fh:
        for r in rows:
            fh.write("\t".join(r) + "\n")
    with open(S + "/jobs4.tsv", "w") as fh:
        for p in projects:
            fh.write("%s\t%s\n" % (p, UNCOVERED[p]))
    print("built %d repos" % len(rows))
