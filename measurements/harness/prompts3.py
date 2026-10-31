"""One prompt per run. Identical across states: the only difference between a
cold, warm and live run is what is on disk when the agent gets there."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

WHO = {
 "ramen-shop":    "a small ramen shop. You handle the menu, the recipes, the suppliers and the prep.",
 "paws-shelter":  "an animal shelter. You handle intake, adoptions, vaccinations and the paperwork.",
 "tinybill":      "a small open-source billing library, one module, a handful of dependencies.",
 "edgeops":       "the operations team for a fleet of edge nodes, managed with terraform.",
 "corpsec":       "the company secretary of a private company. You keep the registers, the minutes and the filings.",
 "vinyl-press":   "a small vinyl pressing plant: two presses, one lathe, one plating bath.",
 "clinic-rota":   "the practice manager of a four-partner GP practice with about 9,400 patients.",
 "seed-bank":     "a regional seed bank holding landrace and heritage crop varieties.",
 "tidepool":      "a small team building a tide and surf forecast app for iOS and Android.",
 "grange-farm":   "a mixed farm: a suckler herd, 180 acres of arable, and a stewardship agreement.",
 "archive-fonds": "a county record office: 900 fonds, four archivists, a reading room.",
}

TEMPLATE = """You work at %(who)s

Your working directory is %(path)s -- everything you do happens in there, and \
nowhere else on this machine. Do not read or write anything outside it.

The job:

%(job)s

Do the job properly, the way someone who will still be here next year would do \
it. You have a shell and the usual tools. Decide for yourself what the work \
involves and carry it out.

When you are finished, say in two or three sentences what you did."""

def build():
    S = os.path.dirname(os.path.abspath(__file__))
    jobs = dict(l.rstrip("\n").split("\t", 1)
                for l in open(S + "/jobs3.tsv", encoding="utf-8") if l.strip())
    out = []
    for line in open(S + "/runmap3.tsv", encoding="utf-8"):
        rid, proj, state, path = line.rstrip("\n").split("\t")
        out.append({"id": rid, "project": proj, "state": state, "path": path,
                    "prompt": TEMPLATE % {"who": WHO[proj], "path": path,
                                          "job": jobs[proj]}})
    return out

if __name__ == "__main__":
    import json
    rows = build()
    json.dump(rows, open(os.path.dirname(os.path.abspath(__file__))
                         + "/prompts3.json", "w"), indent=1)
    print("%d prompts" % len(rows))
    print(rows[0]["prompt"][:400])
