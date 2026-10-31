export const meta = {
  name: 'dotdiw-matrix-round3',
  description: 'Run 33 blind agents across 11 domains in three adoption states',
  phases: [{ title: 'Run', detail: 'one agent per repo, told the job and nothing about the tooling' }],
}

const RESULT = {
  type: 'object',
  properties: {
    summary: { type: 'string', description: 'Two or three sentences on what you did.' },
  },
  required: ['summary'],
}

const TEMPLATE = (r) => `You work at ${r.w}

Your working directory is ${r.d} -- everything you do happens in there, and nowhere else on this machine. Do not read or write anything outside it.

The job:

${r.j}

Do the job properly, the way someone who will still be here next year would do it. You have a shell and the usual tools. Decide for yourself what the work involves and carry it out.

When you are finished, say in two or three sentences what you did.`

phase('Run')
const out = await parallel(args.map(r => () =>
  agent(TEMPLATE(r), {
    label: `${r.id}:${r.p}`,
    phase: 'Run',
    model: 'haiku',
    schema: RESULT,
  }).then(v => ({ id: r.id, project: r.p, summary: (v && v.summary) || null }))
))

const done = out.filter(Boolean)
log(`${done.filter(d => d.summary).length} of ${args.length} returned a summary`)
return done