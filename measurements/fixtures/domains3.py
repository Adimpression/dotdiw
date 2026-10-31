# -*- coding: utf-8 -*-
"""Six more domains for the eleven-project matrix. Same shape as the first
five: the project's own files, two or three formulas in natural places, and
one job that a formula covers."""

NEW = {}

NEW["vinyl-press"] = {
 "job": "A 500-unit repress of the Hollow Coast LP is booked for the week of the 14th. "
        "Get it set up: the lacquer is already cut and on the shelf, the order is confirmed, "
        "and press 2 is free. Work out what has to happen and get it moving.",
 "files": {
  "README.md": """# Northgate Pressing

A small vinyl pressing plant. Two presses, one lathe, one plating bath.
We take orders from labels, cut lacquers, plate stampers and press records.

Capacity is roughly 1,200 units a week across both presses. Press 1 is the
older Toolex and runs 7" best. Press 2 is the SMT and does the 12" work.

Everything we press is logged against an order number. Nothing goes on a press
without a signed test pressing.
""",
  "press/machines.md": """# The presses

## Press 1 (Toolex Alpha, 1979)
Reliable on 7". The steam line needs twenty minutes to come up to pressure.
Mould temperature runs hot; keep an eye on flash at the edge.

## Press 2 (SMT, 2019)
Automated cycle, does 12" and 10". The extruder jams if the pellets are damp,
so the hopper gets checked at the start of every run.

Changeover between formats is about ninety minutes, mostly mould swap.
""",
  "qc/standards.md": """# What we reject

Every run gets a test pressing before the main run, and the label has to sign
it off. After that we pull one in fifty off the line.

Reject for: non-fill at the edge, stitching in the lead-out, warp over 1mm,
visible stampers marks, off-centre spindle hole, or any audible click that
repeats on a second copy.

A run that goes over 8% rejects gets stopped and the stampers get inspected.
""",
  "cutting/lacquers.md": """# Cutting

The lathe is a Neumann VMS-70. Lacquers come in from the supplier in boxes of
ten and have a shelf life — a lacquer older than six weeks cuts badly.

Cut level depends on the programme. Anything over 22 minutes a side needs the
level dropped or it will not track.

Every lacquer is cut in pairs, A and B, and goes straight to plating. A
lacquer left overnight before plating is a lacquer we re-cut.
""",
  "orders/backlog.md": """# Open orders

| Order | Label | Title | Units | Format | Status |
|-------|-------|-------|-------|--------|--------|
| 2411 | Saltmarsh | Hollow Coast | 500 | 12" | lacquer cut, awaiting press |
| 2412 | Saltmarsh | Low Tide EP | 300 | 7" | plating |
| 2415 | Fenmouth | Various: Winter Sides | 1000 | 12" | awaiting lacquer |
| 2416 | Private | Wedding single | 50 | 7" | quoted |

Lead time we quote is six weeks. We are running at eight.
""",
  "docs/suppliers.md": """# Suppliers

Pellets come from Hartwell in 25kg sacks — black compound only, we do not do
colour. Order two weeks ahead; they have been short since the spring.

Lacquers from Transco, boxes of ten, 14" blanks. Jackets and labels come from
whoever the label has used, which is usually Pressplay or Dorne.

Nickel for the plating bath comes from Vantage. Keep one spare anode.
""",
 },
 "formulas": {
  "press/new-run.formula.toml": '''formula = "mol-new-run"
description = "Set a pressing run up from a confirmed order: check the stampers and stock, book the press, cut and sign off a test pressing, then run and pack. Use when an order is ready to go on a press, or a repress has been booked."
examples = [
  "Set up the Hollow Coast repress",
  "Get order 2411 onto press 2 next week",
  "Book the 500 twelve-inch run for Saltmarsh",
  "Press the Low Tide EP",
]
version = 1
type = "workflow"

[[steps]]
id = "stampers"
title = "Check the stampers are plated and sound"

[[steps]]
id = "stock"
title = "Check pellets, jackets and labels are in"

[[steps]]
id = "book"
title = "Book the press and the changeover"
needs = ["stampers", "stock"]

[[steps]]
id = "test"
title = "Run a test pressing and get the label to sign it off"
needs = ["book"]

[[steps]]
id = "run"
title = "Run the order, pulling one in fifty for inspection"
needs = ["test"]

[[steps]]
id = "pack"
title = "Pack, label the boxes and book the courier"
needs = ["run"]
''',
  "qc/reject-batch.formula.toml": '''formula = "mol-reject-batch"
description = "Deal with a run going over the reject limit: stop the press, work out whether it is the stampers, the compound or the machine, and decide what gets repressed. Use when rejects climb past eight percent, or inspection keeps finding the same fault."
examples = [
  "Rejects are over ten percent on order 2412",
  "Stop press 1, we are getting non-fill on every other copy",
  "Same click on three copies in a row",
  "The 7\\" run keeps warping",
]
version = 1
type = "workflow"

[[steps]]
id = "stop"
title = "Stop the press and quarantine what has been pressed"

[[steps]]
id = "cause"
title = "Inspect the stampers, the compound and the mould temperature"
needs = ["stop"]

[[steps]]
id = "decide"
title = "Decide: re-plate, re-cut, or adjust and carry on"
needs = ["cause"]

[[steps]]
id = "tell"
title = "Tell the label what it means for their date"
needs = ["decide"]

[[steps]]
id = "repress"
title = "Repress the quarantined units"
needs = ["decide"]
''',
  "cutting/cut-lacquer.formula.toml": '''formula = "mol-cut-lacquer"
description = "Take a master from the label and get it cut and plated: check the programme length and level, cut both sides, and get the lacquers into the bath the same day. Use when a new title arrives for cutting, or a lacquer has to be re-cut."
examples = [
  "Cut the lacquers for Winter Sides",
  "New master in from Fenmouth, needs cutting",
  "Re-cut side B, the lead-out is stitching",
  "Order 2415 is waiting on a lacquer",
]
version = 1
type = "workflow"

[[steps]]
id = "programme"
title = "Check the programme: side lengths and cut level"

[[steps]]
id = "blanks"
title = "Check the blanks are in date"

[[steps]]
id = "cut"
title = "Cut side A and side B"
needs = ["programme", "blanks"]

[[steps]]
id = "plate"
title = "Get both lacquers into the plating bath the same day"
needs = ["cut"]

[[steps]]
id = "log"
title = "Log the cut against the order"
needs = ["cut"]
''',
 },
}

NEW["clinic-rota"] = {
 "job": "Dr Adeyemi has gone off sick and will be out for at least the next two weeks. "
        "She holds Monday and Thursday mornings plus the Wednesday minor surgery list. "
        "Sort out the cover.",
 "files": {
  "README.md": """# Fairbourne Medical Practice

A four-partner GP practice, about 9,400 patients. Two sites: the main surgery
on Fairbourne Road and a branch at Carlow Street open three days a week.

Clinical team: four GP partners, two salaried GPs, three practice nurses, one
nurse practitioner, two HCAs. Reception and admin are six people.

This repository holds the practice's own working documents — the rota, patient
recall lists, campaign plans and letter templates.
""",
  "rota/duty.md": """# Duty and session cover

The week runs as eighteen GP sessions. Every session needs a named clinician
and a named duty doctor for on-the-day calls.

Monday AM: Adeyemi, Whitlock
Monday PM: Whitlock, Bose
Tuesday AM: Bose, Ferreira
Tuesday PM: Ferreira
Wednesday AM: Adeyemi (minor surgery), Bose
Wednesday PM: Whitlock
Thursday AM: Adeyemi, Ferreira
Thursday PM: Bose, Whitlock
Friday AM: Ferreira, Bose
Friday PM: Whitlock

Locum rates are agreed with Medacs and Castle. Partners cover each other
unpaid for up to three sessions; past that we book a locum.
""",
  "patients/recalls.md": """# Recall lists

Patients on long-term condition registers get called in on a cycle. The
registers we hold:

- Diabetes (QOF) — 612 patients, six-monthly HbA1c and annual review
- Hypertension — 1,140 patients, annual BP and bloods
- Asthma — 480 patients, annual review and inhaler technique
- Anticoagulation — 94 patients, INR per protocol
- Learning disability — 38 patients, annual health check

Recalls go out by text first, then letter after two weeks, then a phone call.
Anyone not seen after three attempts gets flagged to their usual GP.
""",
  "docs/immunisation.md": """# Immunisation

Childhood schedule runs through the nurse clinics. Uptake is reported monthly
and we are below target on the pre-school booster.

Seasonal flu runs September to the end of November. Eligible cohorts are the
over-65s, at-risk registers, pregnant patients, carers and two-and-three year
olds. We run three Saturday clinics plus opportunistic vaccination in normal
appointments.

Shingles and pneumococcal run year-round off the birthday list.
""",
  "docs/cqc.md": """# CQC and governance

Last inspection rated us Good overall, Requires Improvement on
responsiveness — the complaint was telephone access at 8am.

Significant events get written up within a week and discussed at the monthly
clinical meeting. The log lives with the practice manager.

Policies on review this year: safeguarding, chaperoning, infection control,
and the business continuity plan.
""",
  "templates/letters.md": """# Letter templates

We keep these as text so they can be merged from the clinical system.

- Recall, first attempt (text message, 160 characters)
- Recall, second attempt (letter)
- Did not attend, after three attempts
- Referral acknowledgement
- Results normal / results need a conversation
- Clinician absence, patient-facing notice

Anything patient-facing goes past the practice manager before it goes out.
""",
 },
 "formulas": {
  "rota/cover-absence.formula.toml": '''formula = "mol-cover-absence"
description = "Cover a clinician who is away: work out which sessions are uncovered, offer them internally, book a locum for what is left, then move the patients and tell them. Use when someone goes off sick, has taken leave at short notice or in an emergency, or a session is suddenly unstaffed."
examples = [
  "Dr Adeyemi is off sick for two weeks",
  "Who is covering Thursday morning",
  "Ferreira has taken emergency leave from Monday",
  "We are a clinician short next week",
]
version = 1
type = "workflow"

[[steps]]
id = "sessions"
title = "List the uncovered sessions, including duty and minor surgery"

[[steps]]
id = "internal"
title = "Offer the sessions internally first"
needs = ["sessions"]

[[steps]]
id = "locum"
title = "Book locums for whatever is left"
needs = ["internal"]

[[steps]]
id = "patients"
title = "Move or rebook the affected appointments"
needs = ["internal", "locum"]

[[steps]]
id = "notice"
title = "Put a notice up and brief reception"
needs = ["patients"]
''',
  "patients/recall-round.formula.toml": '''formula = "mol-recall-round"
description = "Run a round of recalls against a long-term condition register: pull the list of who is due, text them, letter the ones who do not answer, then flag whoever is still unseen. Use when a register is due its cycle, or uptake on a review has slipped."
examples = [
  "Run the diabetes recalls for this quarter",
  "The hypertension register is overdue a sweep",
  "Call in everyone due an asthma review",
  "Chase the patients we have not seen on the LD register",
]
version = 1
type = "workflow"

[[steps]]
id = "pull"
title = "Pull the list of patients due from the register"

[[steps]]
id = "text"
title = "Send the first-attempt text"
needs = ["pull"]

[[steps]]
id = "letter"
title = "Letter whoever has not booked after two weeks"
needs = ["text"]

[[steps]]
id = "call"
title = "Phone the remainder"
needs = ["letter"]

[[steps]]
id = "flag"
title = "Flag anyone still unseen to their usual GP"
needs = ["call"]
''',
  "docs/flu-campaign.formula.toml": '''formula = "mol-flu-campaign"
description = "Run the seasonal vaccination campaign: order the stock, build the eligible cohorts, book the Saturday clinics, invite patients and report uptake. Use when the autumn campaign is starting or uptake in a cohort needs pushing."
examples = [
  "Start the flu campaign for this autumn",
  "Get the over-65s invited for their jab",
  "Book the Saturday vaccination clinics",
  "Our uptake in the at-risk cohort is behind",
]
version = 1
type = "workflow"

[[steps]]
id = "stock"
title = "Order vaccine stock against expected uptake"

[[steps]]
id = "cohorts"
title = "Build the eligible cohorts from the registers"

[[steps]]
id = "clinics"
title = "Book the Saturday clinics and staff them"
needs = ["stock", "cohorts"]

[[steps]]
id = "invite"
title = "Invite patients, text first then letter"
needs = ["clinics"]

[[steps]]
id = "report"
title = "Report uptake and chase the cohorts that are behind"
needs = ["invite"]
''',
 },
}

NEW["seed-bank"] = {
 "job": "A box of 40 landrace barley samples has arrived from the Orkney collector, "
        "with a handwritten list and no accession numbers. Get them into the bank properly.",
 "files": {
  "README.md": """# Caldermoor Seed Bank

A regional seed bank holding landrace and heritage crop varieties for the
north and the islands. About 4,100 accessions, mostly cereals and brassicas.

We take in collections from growers and collectors, test them, dry them to
storage moisture, and hold them at -18C. We send samples out to anyone who
asks and can use them.

Nothing enters the cold store without a germination figure against it.
""",
  "accessions/register.md": """# The register

Every accession gets a number: CAL-NNNNN, sequential, never reused. The
register records the number, the species, the local name, who collected it,
where and when, the quantity, and the germination figure.

Collections arrive as boxes of envelopes, usually with a collector's list that
does not match what is in the box. The count is done on arrival, twice, by two
people.

Current gaps in the register: 112 accessions with no germination figure, 40 of
them from the 2019 Hebrides trip.
""",
  "lab/germination.md": """# Germination testing

Standard test is 100 seeds on moist filter paper, four replicates of 25, at
20C with a 12-hour photoperiod. Counted at 7 and 14 days.

Cereals: 85% is the threshold for going into long-term store. Below that the
accession goes on the regeneration list.

Brassicas need a cold stratification first — three weeks at 4C — or the
figures come out meaninglessly low.

Dormant samples get a second test after six months before we call them
non-viable.
""",
  "docs/storage.md": """# Storage

Two stores. Active collection at 4C for material we send out; base collection
at -18C for long-term.

Seed goes in at 6-7% moisture content, dried down in the cabinet at 15C and
15% RH. Anything put in wet will be dead in five years and look fine.

Containers: laminated foil for base, screw-top jars for active. Every
container carries the accession number and the pack date.
""",
  "docs/distribution.md": """# Sending samples out

We send to growers, researchers, community seed libraries and other banks.
Requests come in by email and go on the request list.

A standard sample is 50 seeds, or 25 for anything with fewer than 500 in
store. Anything below 200 in store is not distributed — it goes on the
regeneration list instead.

Every sample goes out with the accession's passport data and a note asking for
the grower's results back. Phytosanitary paperwork for anything leaving the
country.
""",
  "collections/grains.md": """# Cereal collections

Barley is the bulk of what we hold — 1,340 accessions, mostly six-row
landraces from the islands. Bere barley alone is 210 accessions.

Oats: 680, including the black oats from Shetland.
Wheat: 290, mostly nineteenth-century types.
Rye: 70.

The island material is the part nobody else holds, and the part we are most
behind on testing.
""",
 },
 "formulas": {
  "accessions/accession.formula.toml": '''formula = "mol-accession"
description = "Bring a collection into the bank and onto the register: count what actually arrived, give each sample a number, record the passport data, dry it down and put it into store. Use when a box of seed arrives, when a deposit comes in from a collector, grower or seed library, or when material turns up without numbers."
examples = [
  "A box of barley samples has arrived from Orkney",
  "Forty envelopes in from the collector, no numbers on them",
  "Get the new Shetland oats into the register",
  "Take in the deposit from the community seed library",
]
version = 1
type = "workflow"

[[steps]]
id = "count"
title = "Count what arrived, twice, against the collector's list"

[[steps]]
id = "number"
title = "Assign accession numbers in sequence"
needs = ["count"]

[[steps]]
id = "passport"
title = "Record the passport data: species, local name, collector, place, date"
needs = ["number"]

[[steps]]
id = "dry"
title = "Dry down to storage moisture in the cabinet"
needs = ["number"]

[[steps]]
id = "test"
title = "Put a germination test on"
needs = ["dry"]

[[steps]]
id = "store"
title = "Pack and place into the base and active stores"
needs = ["test", "passport"]
''',
  "lab/viability-test.formula.toml": '''formula = "mol-viability-test"
description = "Test whether an accession is still alive: set up the replicates, count at seven and fourteen days, and either clear it for store or put it on the regeneration list. Use when an accession has no figure, is due a retest, or came out low the first time."
examples = [
  "Test the 2019 Hebrides accessions, they have no figures",
  "Retest CAL-02211, it came out at sixty percent",
  "Put a germination test on the new barley",
  "Are these oats still viable",
]
version = 1
type = "workflow"

[[steps]]
id = "setup"
title = "Set up four replicates of 25 on moist paper"

[[steps]]
id = "strat"
title = "Cold stratify first if it is a brassica"

[[steps]]
id = "count7"
title = "Count at seven days"
needs = ["setup", "strat"]

[[steps]]
id = "count14"
title = "Count at fourteen days"
needs = ["count7"]

[[steps]]
id = "decide"
title = "Clear for store, or put on the regeneration list"
needs = ["count14"]
''',
  "docs/send-sample.formula.toml": '''formula = "mol-send-sample"
description = "Send seed to someone who has asked for it: check there is enough in store to spare, pack the sample, put the passport data with it and the paperwork if it is leaving the country. Use when a request comes in from a grower, a researcher or another bank."
examples = [
  "A grower in Caithness wants bere barley",
  "Send 50 seeds of the black oats to the university",
  "Request in for three accessions, one going to Norway",
  "Can we spare a sample of the Shetland material",
]
version = 1
type = "workflow"

[[steps]]
id = "stock"
title = "Check the store count: under 200 means regenerate instead"

[[steps]]
id = "pack"
title = "Count and pack the sample"
needs = ["stock"]

[[steps]]
id = "passport"
title = "Put the passport data and a results-back note in with it"
needs = ["pack"]

[[steps]]
id = "phyto"
title = "Do the phytosanitary paperwork if it is leaving the country"
needs = ["pack"]

[[steps]]
id = "send"
title = "Send it and log the distribution"
needs = ["passport", "phyto"]
''',
 },
}

NEW["tidepool"] = {
 "job": "Build 4.2 is cut and green on CI. Get it out to the App Store and Play Store.",
 "files": {
  "README.md": """# Tidepool

A tide and surf forecast app. iOS and Android, shared Kotlin Multiplatform
core, native UI on both sides.

About 240,000 monthly actives, heaviest in the UK and Portugal. Free with a
subscription tier for the 10-day forecast and offline charts.

Releases go out roughly every three weeks on a train. Hotfixes go out whenever
they have to.
""",
  "app/README.md": """# Build and run

    ./gradlew :core:build
    ./gradlew :android:assembleRelease
    (cd ios && xcodebuild -scheme Tidepool -configuration Release)

The core module holds the tide model, the station database and the
subscription logic. Platform code is UI and system integration only.

Station data is vendored from the hydrographic offices and refreshed quarterly.
A station whose datum changes will silently produce wrong heights, so the
refresh has its own checks.
""",
  "docs/release-train.md": """# The release train

Branch cut on a Monday, soak on internal testing for two days, then phased
rollout. Android goes to 10% for a day, then 50%, then 100%. iOS goes to
phased release over seven days.

Version numbers are major.minor, build numbers monotonic across both stores.

What has to be true before a build leaves: CI green, no P1 crashes in the soak,
store metadata and screenshots updated if the UI changed, and the subscription
paywall smoke-tested on both platforms against the sandbox.

Release notes go in store metadata and on the changelog page. Someone has to
actually write them.
""",
  "docs/crash-triage.md": """# Crash triage

Crashes come in through Sentry. We look at crash-free sessions daily; the line
we hold is 99.5%.

A spike is a 0.2 point drop or any new crash over 50 sessions in an hour.
First question is always whether it tracks a rollout — if it does, halt the
rollout before anything else.

Known recurring: the chart renderer OOMs on very old Android devices when the
10-day view is opened twice; the tide station picker crashes if location
permission is revoked while the app is backgrounded.
""",
  "store/metadata.md": """# Store listings

Both listings carry the same six screenshots, generated from the UI test
suite, and the same description text in seven locales.

Apple has rejected us three times: once for the subscription terms not being
visible before purchase, once for using the word "free" in a screenshot, and
once for background location without a clear enough justification string.

Play has never rejected a build but has twice flagged the data safety form as
inconsistent with what the app actually collects.
""",
  "docs/experiments.md": """# Experiments

Feature flags are server-driven, fetched at launch with a cached fallback. A
flag that fails to fetch must default to off.

Running now: the new chart renderer at 20%, the onboarding rewrite at 50%, and
the annual subscription price test in Portugal only.

An experiment that touches the paywall needs the subscription smoke test run
against both stores' sandboxes before it goes above 10%.
""",
 },
 "formulas": {
  "docs/ship-build.formula.toml": '''formula = "mol-ship-build"
description = "Get a build out to both stores: soak it on internal testing, check crashes and the paywall, update the listings, write the notes and start the phased rollout. Use when a build is cut and ready to go to users, or a version needs shipping."
examples = [
  "Build 4.2 is ready for the stores",
  "Ship 4.1 to the App Store and Play",
  "Get this version out to users",
  "Start the rollout for the new release",
]
version = 1
type = "workflow"

[[steps]]
id = "soak"
title = "Put it on internal testing and soak it for two days"

[[steps]]
id = "crashes"
title = "Check the soak for P1 crashes"
needs = ["soak"]

[[steps]]
id = "paywall"
title = "Smoke-test the subscription paywall on both sandboxes"
needs = ["soak"]

[[steps]]
id = "metadata"
title = "Update screenshots and store metadata if the UI changed"

[[steps]]
id = "notes"
title = "Write the release notes"

[[steps]]
id = "rollout"
title = "Submit and start the phased rollout"
needs = ["crashes", "paywall", "metadata", "notes"]
''',
  "docs/triage-crash.formula.toml": '''formula = "mol-triage-crash"
description = "Work a crash spike: find out whether it tracks a rollout and halt it if so, pin down the device and version it hits, fix or revert, and get the fix out. Use when crash-free sessions drop, a new crash climbs, or users start reporting the app closing."
examples = [
  "Crash-free sessions dropped to 99.1 overnight",
  "New crash in the chart renderer, climbing fast",
  "Users on old Androids say the app closes on the 10-day view",
  "Something in 4.1 is crashing",
]
version = 1
type = "workflow"

[[steps]]
id = "rollout"
title = "Check whether it tracks a rollout, and halt the rollout if it does"

[[steps]]
id = "scope"
title = "Pin down the devices, OS versions and app version affected"
needs = ["rollout"]

[[steps]]
id = "cause"
title = "Find the cause from the stack and the breadcrumbs"
needs = ["scope"]

[[steps]]
id = "fix"
title = "Fix it, or revert the change that caused it"
needs = ["cause"]

[[steps]]
id = "ship"
title = "Get the fix out and confirm the rate recovers"
needs = ["fix"]
''',
  "store/store-rejection.formula.toml": '''formula = "mol-store-rejection"
description = "Answer a store review rejection: read what guideline they actually cited, fix the app or the listing, reply in the review thread and resubmit. Use when Apple rejects a build, when Play flags the data safety form, or when a listing gets flagged in review."
examples = [
  "Apple rejected 4.2 over the subscription terms",
  "Review came back citing guideline 3.1.2",
  "Play flagged our data safety form",
  "The build got rejected again",
]
version = 1
type = "workflow"

[[steps]]
id = "read"
title = "Read the rejection and find the guideline actually cited"

[[steps]]
id = "decide"
title = "Decide whether it is the app or the listing that has to change"
needs = ["read"]

[[steps]]
id = "change"
title = "Make the change"
needs = ["decide"]

[[steps]]
id = "reply"
title = "Reply in the review thread saying what changed"
needs = ["change"]

[[steps]]
id = "resubmit"
title = "Resubmit and watch the review state"
needs = ["reply"]
''',
 },
}

NEW["grange-farm"] = {
 "job": "Heifer 118 is due to calve this week and it is her first. "
        "She is in the far paddock. Get it organised.",
 "files": {
  "README.md": """# Grange Farm

A mixed farm, 340 acres. Suckler herd of 70 Aberdeen Angus cross cows, 180
acres of arable in a six-year rotation, the rest permanent pasture and a
twelve-acre block of woodland in a stewardship agreement.

Two of us full time, plus contractors for harvest and slurry.

This repository holds the farm's working records: the herd book, the rotation,
spray plans and the subsidy paperwork.
""",
  "livestock/herd.md": """# The herd

70 suckler cows plus followers. Calving is split: forty in the spring block
from late February, thirty in autumn from September.

Bulls: two Angus, one running with each block. Heifers go to the bull at
fifteen months and calve at twenty-four.

Tags are three digits. Anything in the 100s is a 2024-born heifer, so 118 is a
first calver this year.

Health plan: BVD accredited, Johne's testing annually, fluke drench in autumn,
and a mineral bolus pre-calving.
""",
  "fields/rotation.md": """# Rotation

Six-year: winter wheat, winter barley, oilseed rape, winter wheat, spring
beans, then a year of grass.

Fields: Long Acre (42), Mill Field (38), Church Piece (30), Hollow (26), Top
Field (24), Far Paddock (20, permanent pasture).

Soil is a heavy clay on the north side and lighter over the gravel in Mill
Field. Long Acre does not travel until April in a wet spring.

Beans go in by mid-March or they do not yield.
""",
  "docs/spraying.md": """# Spraying

The sprayer is a 24m trailed, 3000 litre. NSTS tested in May, operator
certificates current for both of us.

Windows matter more than anything. Wind under 7mph for anything with drift
risk, no spraying within 48 hours of forecast heavy rain, and nothing within
the 5m buffer along the brook in Hollow.

Every application gets recorded: product, rate, area, date, wind, operator.
That record is what gets inspected, and a missing one is a cross-compliance
breach.

T1 and T2 fungicide timings on the wheat are the two that cannot slip.
""",
  "docs/subsidy.md": """# Subsidy and stewardship

The stewardship agreement covers the woodland block, two hedgerow options and
a six-metre buffer strip along the brook. Annual claim window opens in March
and closes mid-May.

What the claim needs: the field parcel map checked against what is actually
cropped, the stewardship options evidenced, the spray and fertiliser records
complete, and the livestock numbers as at the census date.

An inspection in 2023 found our hedgerow cutting dates undocumented. That cost
us a deduction and it is not happening again.
""",
  "docs/machinery.md": """# Machinery

Two tractors: a 150hp for the heavy work and a 90hp for the yard and the
grass. Combine is shared with the neighbour on a half-share.

Servicing in the winter, before anything else starts. The 150 is due a new
front linkage pin and the sprayer needs its nozzles replaced this year.

Slurry tanker and the muck spreader come with the contractor.
""",
 },
 "formulas": {
  "livestock/calving.formula.toml": '''formula = "mol-calving"
description = "Bring a cow or heifer through calving: get her in where she can be watched, check her and the calf through, make sure the calf gets colostrum, then tag and register it. Use when an animal is close to calving, is calving now, or a first calver needs watching."
examples = [
  "Heifer 118 is due this week and it is her first",
  "Cow 043 is calving in the far paddock",
  "Get the first calvers in before the weekend",
  "Calf born overnight, needs tagging",
]
version = 1
type = "workflow"

[[steps]]
id = "bring"
title = "Bring her in somewhere she can be watched"

[[steps]]
id = "watch"
title = "Check her through, and call the vet if she is not progressing"
needs = ["bring"]

[[steps]]
id = "colostrum"
title = "Make sure the calf is up and has had colostrum within six hours"
needs = ["watch"]

[[steps]]
id = "navel"
title = "Dress the navel and check the calf over"
needs = ["colostrum"]

[[steps]]
id = "tag"
title = "Tag the calf and register the birth"
needs = ["navel"]

[[steps]]
id = "book"
title = "Write it up in the herd book"
needs = ["tag"]
''',
  "fields/spray-window.formula.toml": '''formula = "mol-spray-window"
description = "Get a field sprayed inside the window it has: check the forecast and the buffers, work out the product and rate, do it, and write the application down. Use when a timing is coming up, a field needs doing before rain, or a fungicide spray cannot slip."
examples = [
  "Long Acre needs its T1 before the weather turns",
  "Get the wheat sprayed while the wind is down",
  "T2 timing is on us",
  "Spray Mill Field before the rain on Thursday",
]
version = 1
type = "workflow"

[[steps]]
id = "forecast"
title = "Check wind and rain against the window"

[[steps]]
id = "plan"
title = "Work out product, rate and area, and the buffer strips"

[[steps]]
id = "mix"
title = "Mix and load"
needs = ["forecast", "plan"]

[[steps]]
id = "spray"
title = "Spray it"
needs = ["mix"]

[[steps]]
id = "record"
title = "Record product, rate, area, date, wind and operator"
needs = ["spray"]

[[steps]]
id = "wash"
title = "Wash out and dispose of the washings properly"
needs = ["spray"]
''',
  "docs/subsidy-claim.formula.toml": '''formula = "mol-subsidy-claim"
description = "Put the annual claim in: check the parcel map against what is actually cropped, evidence the stewardship options, make sure the records are complete, then submit before the window shuts. Use when the claim window opens, or an inspection is coming."
examples = [
  "Get this year's claim in before mid-May",
  "The claim window is open",
  "Check the parcel map against what we actually drilled",
  "Inspection coming, are the records straight",
]
version = 1
type = "workflow"

[[steps]]
id = "map"
title = "Check the field parcel map against what is actually cropped"

[[steps]]
id = "options"
title = "Evidence the stewardship options, cutting dates included"

[[steps]]
id = "records"
title = "Check the spray and fertiliser records are complete"

[[steps]]
id = "stock"
title = "Take the livestock numbers as at the census date"

[[steps]]
id = "submit"
title = "Submit the claim"
needs = ["map", "options", "records", "stock"]
''',
 },
}

NEW["archive-fonds"] = {
 "job": "The Pemberton solicitors' deposit has arrived: twelve boxes, unlisted, "
        "with a covering letter and nothing else. Get it taken in.",
 "files": {
  "README.md": """# Thornbury Record Office

A county record office. Roughly 4km of shelving, 900 fonds, from the twelfth
century to last year.

Four archivists, two conservators, one digitisation officer, and a reading
room open four days a week.

This repository holds our own working documents: the accession register,
appraisal and digitisation policy, and the finding aids as we write them.
""",
  "fonds/register.md": """# Accession register

Every deposit gets an accession number on arrival: ACC/YYYY/NNN. That number
is assigned before anything is opened, and it stays with the material.

What the register records: the number, the depositor, the date of deposit, the
extent as received, the terms (gift, deposit, purchase), access conditions,
and where it is physically sitting.

Recent accessions awaiting listing: ACC/2026/011 (parish records, 3 boxes),
ACC/2026/014 (photographic negatives, 1 box, at risk), ACC/2026/017 (Pemberton
solicitors, 12 boxes).

The backlog of unlisted material is about 180 linear metres.
""",
  "docs/appraisal.md": """# Appraisal

Not everything is kept. Appraisal happens after accession, never before —
material is taken in whole, then assessed.

We keep: anything documenting the administration of the body that created it,
anything evidencing people's rights, and anything of local research value that
is not duplicated elsewhere.

We dispose of: routine financial papers over seven years old with no summary
value, duplicates, and published material held by the library.

Nothing is destroyed without the depositor's written agreement and a note on
the file saying what went and why.
""",
  "docs/digitisation.md": """# Digitisation

Priority is condition first, demand second. Anything at risk gets digitised
whether or not anyone asks for it.

Standards: 400dpi TIFF for the preservation master, derivative JPEGs for the
catalogue. Nitrate and acetate film goes to a specialist.

Every digitised item needs its catalogue entry in place first, or the files
have nothing to hang off.

Copyright is checked before anything goes online. For solicitors' and
business records that usually means it does not.
""",
  "finding-aids/README.md": """# Finding aids

One finding aid per fonds, ISAD(G) structure: fonds, series, file, item.

Description is top-down. The fonds-level description goes in before any file
listing, so there is something usable in the catalogue from the start.

Every finding aid carries an administrative history of the creating body. For
a solicitors' practice that means the partners, the dates, the predecessor
firms, and what kind of work they did.

Half-finished finding aids are worse than none, because they look complete in
the catalogue. Fonds-level first, then go deeper.
""",
  "docs/reading-room.md": """# Reading room

Open Tuesday to Friday. Readers register once, with photo ID, and order up to
five items at a time.

Closed material: anything with access conditions, anything under 100 years
containing personal data, and anything in a condition that will not take
handling. A reader refused access gets told why and who to ask.

Production is twice a day. Nothing leaves the strongroom without being signed
out.
""",
 },
 "formulas": {
  "fonds/accession.formula.toml": '''formula = "mol-accession"
description = "Take a deposit in: give it a number before anything is opened, record the extent and the terms, check its condition, get it shelved and then write a fonds-level description. Use when material arrives from a depositor, or a box turns up unlisted and unnumbered."
examples = [
  "Twelve boxes in from the Pemberton solicitors, unlisted",
  "A deposit has arrived with just a covering letter",
  "Take in the parish records that came yesterday",
  "New material at the loading bay, nothing recorded yet",
]
version = 1
type = "workflow"

[[steps]]
id = "number"
title = "Assign the accession number before anything is opened"

[[steps]]
id = "extent"
title = "Record the extent as received, and the terms of deposit"
needs = ["number"]

[[steps]]
id = "condition"
title = "Check condition and flag anything at risk to conservation"
needs = ["number"]

[[steps]]
id = "shelve"
title = "Shelve it and record where it is"
needs = ["extent", "condition"]

[[steps]]
id = "describe"
title = "Write the fonds-level description into the catalogue"
needs = ["shelve"]

[[steps]]
id = "acknowledge"
title = "Acknowledge the deposit to the depositor"
needs = ["extent"]
''',
  "docs/digitise.formula.toml": '''formula = "mol-digitise"
description = "Get a series digitised: check the catalogue entry exists and the copyright allows it, assess condition, scan to the preservation standard, then attach the derivatives. Use when something is at risk, a reader keeps asking for it, or a series is scheduled for scanning."
examples = [
  "Digitise the negatives before they deteriorate further",
  "The photographic collection is at risk and needs scanning",
  "Readers keep ordering the same series, get it online",
  "Scan the tithe maps",
]
version = 1
type = "workflow"

[[steps]]
id = "catalogue"
title = "Check the catalogue entry is in place to hang the files off"

[[steps]]
id = "copyright"
title = "Check copyright allows it online"

[[steps]]
id = "condition"
title = "Assess whether it will take handling, or needs a specialist"

[[steps]]
id = "scan"
title = "Scan to preservation TIFF and make the derivatives"
needs = ["catalogue", "condition"]

[[steps]]
id = "attach"
title = "Attach the derivatives to the catalogue entry"
needs = ["scan", "copyright"]
''',
  "finding-aids/finding-aid.formula.toml": '''formula = "mol-finding-aid"
description = "Write the finding aid for a fonds: research the creating body, describe top-down from fonds to series to file, set the access conditions and publish it. Use when an accession needs listing, or something in the backlog is being catalogued at last."
examples = [
  "List ACC/2026/017, it is still in the backlog",
  "Catalogue the solicitors' records properly",
  "We need a finding aid for the estate papers",
  "Write up the administrative history for the practice",
]
version = 1
type = "workflow"

[[steps]]
id = "history"
title = "Research the administrative history of the creating body"

[[steps]]
id = "fonds"
title = "Write the fonds-level description first"
needs = ["history"]

[[steps]]
id = "series"
title = "Arrange into series and describe each"
needs = ["fonds"]

[[steps]]
id = "files"
title = "List at file level"
needs = ["series"]

[[steps]]
id = "access"
title = "Set access conditions on anything closed"
needs = ["series"]

[[steps]]
id = "publish"
title = "Publish it to the catalogue"
needs = ["files", "access"]
''',
 },
}
