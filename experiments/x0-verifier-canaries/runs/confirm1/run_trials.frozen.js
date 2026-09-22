export const meta = {
  name: 'exp-trials',
  description: 'Experiment harness: run independent single-role trials, each on its own frozen investigation state',
  whenToUse: 'Launched with args from experiments/harness/prepare.py (runs/<run>/trials.json); not meant to be run by hand',
  phases: [{ title: 'Trials', detail: 'one agent per trial; trials are independent' }],
}

// optional in both forms: agent_types: { role: 'investigate:<role>' } — the plugin's role agents (system prompt, tool limits, turn cap)
// args, compact form (runs/<run>/args.json): { run, base, k (number, or {modelKey: n}), models: {key: modelId}, cells: [{ id, role, lane?, task?, title?, verify?, extra? }] }
//   -> one trial per cell x model x 1..k, in <base>/<modelKey>/<cellId>-<i>/ (the layout prepare.py builds)
// args, explicit form: { run, trials: [{ id, role, inv, model, round, lane?, task?, title?, verify?, review?, allowRevise?, stall?, extra? }] }
// Prompt builders are copied verbatim from investigate/kit/bin/investigate.js so a trial agent
// sees exactly what a production agent sees. Keep them in sync when the kit changes.
if (args && Array.isArray(args.cells) && args.base && args.models) {
  args.trials = args.cells.flatMap(c => Object.entries(args.models).flatMap(([mk, model]) =>
    Array.from({ length: (typeof args.k === 'object' ? args.k[mk] : args.k) || 1 }, (_, i) => ({
      ...c, cell: c.id, id: `${mk}/${c.id}-${i + 1}`, inv: `${args.base}/${mk}/${c.id}-${i + 1}`, model, round: 1,
      review: 1, allowRevise: c.verify === 'adversarial', stall: 0, stallRounds: 2,
    }))))
}
if (!args || !Array.isArray(args.trials) || !args.trials.length) {
  throw new Error('exp-trials needs args from experiments/harness/prepare.py (runs/<run>/args.json)')
}
const pad = n => String(n).padStart(2, '0')
const str = (max) => (max ? { type: 'string', maxLength: max } : { type: 'string' })
const strs = { type: 'array', items: { type: 'string' } }

const SCHEMAS = {
  challenger: {
    type: 'object', required: ['verdict', 'summary'],
    properties: { verdict: { type: 'string', enum: ['accept', 'revise', 'redo'] }, summary: str(600), objections: strs },
  },
  judge: {
    type: 'object', required: ['met', 'progress', 'gaps', 'summary'],
    properties: { met: { type: 'boolean' }, progress: { type: 'boolean' }, gaps: strs, summary: str(800) },
  },
  refuter: {
    type: 'object', required: ['upheld', 'summary'],
    properties: { upheld: { type: 'boolean' }, objections: strs, summary: str(800) },
  },
}

function header(t, role, who, lane, briefArgs = '') {
  const BOARD = `${t.inv}/bin/board.py`
  return [
    `You are the ${role.toUpperCase()} in a structured investigation.`,
    `Investigation directory: ${t.inv}`,
    `Board CLI: ${BOARD}   (an executable; pass --as ${who} literally on every call — never via a shell variable)`,
    `Round: ${t.round}${lane ? `   Lane: ${lane}` : ''}`,
    `Your first action: ${BOARD} brief --role ${role}${lane ? ` --lane ${lane}` : ''}${briefArgs} --as ${who}`,
    `It prints the protocol, your role instructions, ${lane ? 'your lane, ' : ''}the manifest essentials and the state you need. Follow them exactly.`,
  ].join('\n')
}

const PROMPTS = {
  challenger: t => [
    header(t, 'challenger', `${t.lane}/challenger`, t.lane, ` --task ${t.task}`),
    `Review task ${t.task} — ${t.title}   (verify level: ${t.verify}, review ${t.review})`,
    `Allowed verdicts: ${t.allowRevise ? 'accept | revise | redo' : 'accept | redo  (no revisions left)'}`,
    `Record it with: ${t.inv}/bin/board.py task review --id ${t.task} --verdict V --summary S [--objection O ...] --as ${t.lane}/challenger`,
  ].join('\n\n'),
  judge: t => [
    header(t, 'judge', 'judge', null),
    `Rounds without progress so far: ${t.stall} (stop threshold ${t.stallRounds}).`,
    `Save with: ${t.inv}/bin/board.py judge save --round ${t.round} --as judge <<'EOF' {"met":..,"progress":..,"gaps":[..],"summary":".."} EOF`,
  ].join('\n\n'),
  refuter: t => [
    header(t, 'refuter', 'refuter', null),
    `The judge declared every success criterion met in round ${t.round} (judge/round-${pad(t.round)}.json). The investigation stops if this verdict stands.`,
    `If a criterion is not actually met, record it with: ${t.inv}/bin/board.py judge refute --round ${t.round} --objection "..." [--objection ...] --as refuter`,
    `Return upheld=true only if every criterion survives your attempt to refute it.`,
  ].join('\n\n'),
}

phase('Trials')
log(`${args.run}: ${args.trials.length} trial(s)${args.agent_types ? ' with plugin agent types' : ' as plain workflow agents (no turn caps)'}`)
const results = await parallel(args.trials.map(t => async () => {
  if (!PROMPTS[t.role]) throw new Error(`no prompt builder for role ${t.role}`)
  const o = { label: t.id, phase: 'Trials', schema: SCHEMAS[t.role] }
  if (t.model) o.model = t.model
  const at = t.agentType || (args.agent_types && args.agent_types[t.role])
  if (at) o.agentType = at
  const r = await agent(PROMPTS[t.role](t) + (t.extra ? `\n\n${t.extra}` : ''), o)
  return { id: t.id, result: r }
}))
const out = args.trials.map((t, i) => results[i] || { id: t.id, result: null })
log(`${out.filter(r => r.result).length}/${out.length} trials returned a result`)
return { run: args.run, results: out }
