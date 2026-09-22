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
      ...c, cell: c.id, id: `${mk}/${c.id}-${i + 1}`, inv: `${args.base}/${mk}/${c.id}-${i + 1}`, model, round: c.round || 1,
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
  plan: {
    type: 'object', required: ['dispatch', 'summary'],
    properties: {
      plan_version: { type: 'integer' }, summary: str(600),
      dispatch: { type: 'array', items: { type: 'object', required: ['id', 'title', 'resources', 'deps', 'verify', 'size'],
        properties: { id: str(), title: str(200), kind: str(), items: strs, resources: strs, deps: strs,
          verify: { type: 'string', enum: ['none', 'light', 'adversarial'] }, size: { type: 'string', enum: ['short', 'long'] } } } },
    },
  },
  investigator: {
    type: 'object', required: ['status', 'summary'],
    properties: {
      status: { type: 'string', enum: ['done', 'partial', 'failed', 'blocked'] },
      summary: str(600), board_ids: strs, artifacts: strs,
    },
  },
  position: {
    type: 'object', required: ['hypotheses', 'directive', 'summary'],
    properties: {
      hypotheses: { type: 'array', maxItems: 6, items: { type: 'object', required: ['name', 'status', 'reason'], properties: {
        name: str(200), based_on: strs, status: { type: 'string', enum: ['leading', 'live', 'deprioritised', 'refuted'] }, reason: str(700) } } },
      directive: { type: 'array', maxItems: 4, items: { type: 'object', required: ['lane', 'experiment'], properties: {
        lane: str(40), experiment: str(600), separates: str(300), predictions: str(500) } } },
      not_pursuing: str(900), summary: str(900), chosen_from: str(60), dissent_funded: { type: 'boolean' },
    },
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

// experimental strategy roles (x3): briefed by bin/xbrief.py, which the experiment installs into the trial
function xheader(t, role, who, briefArgs) {
  return [
    `You are the ${role.toUpperCase()} in a structured investigation.`,
    `Investigation directory: ${t.inv}`,
    `Board CLI: ${t.inv}/bin/board.py   (an executable; pass --as ${who} literally on every call — never via a shell variable)`,
    `Round: ${t.round}${t.lane ? `   Lane: ${t.lane}` : ''}`,
    `Your first action: ${t.inv}/bin/xbrief.py --role ${role}${briefArgs} --as ${who}`,
    `It prints the protocol, your role instructions, the manifest essentials and the state you need. Follow them exactly.`,
    `Round ${t.round} has just been judged; your position is for round ${t.round + 1}. Return it as structured output.`,
  ].join('\n')
}

const PROMPTS = {
  plan: t => [
    header(t, 'plan', `${t.lane}/plan`, t.lane, ` --round ${t.round}`),
    `Scope summary: see the scope brief in your brief output   (the full scope brief is included in your brief output)`,
    `At most ${t.max_tasks || 2} queued tasks. New task ids: ${t.lane}-r${pad(t.round)}-01, -02, ...`,
    `In flight (leave out of the plan): none`,
    `Exclusive resources held by running tasks (any lane): none — a task claiming one of these waits until it is released.`,
    `Save with: ${t.inv}/bin/board.py plan save --lane ${t.lane} --round ${t.round} --inflight "" --as ${t.lane}/plan <<'EOF' {json} EOF`,
    `Return the "dispatch" list and "version" exactly as plan save printed them (dispatch=[] if you queued nothing).`,
  ].join('\n\n'),
  strategist: t => xheader(t, 'strategist', 'strategist', t.persona ? ` --persona ${t.persona}` : ''),
  chair: t => xheader(t, 'chair', 'council/chair', ''),
  member: t => xheader(t, 'member', `council/${t.persona}`, ` --persona ${t.persona}`),
  advocate: t => xheader(t, 'advocate', `${t.lane}/advocate`, ` --lane ${t.lane}`),
  investigator: t => [
    header(t, 'investigator', `${t.lane}/${t.task}`, t.lane),
    `Task: ${t.task} — ${t.title}`,
    `Start with: ${t.inv}/bin/board.py task start --id ${t.task} --as ${t.lane}/${t.task}   (prints the full task spec)`,
    `This is the first attempt in this round.`,
    `You may spawn at most ${t.max_children ?? 0} child subagent(s). Finish with ${t.inv}/bin/board.py task finish ... and return the same status/summary.`,
  ].join('\n\n'),
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
  const o = { label: t.id, phase: 'Trials', schema: SCHEMAS[t.role] || SCHEMAS.position }
  if (t.model) o.model = t.model
  const at = t.agentType || (args.agent_types && args.agent_types[t.role])
  if (at) o.agentType = at
  const r = await agent(PROMPTS[t.role](t) + (t.extra ? `\n\n${t.extra}` : ''), o)
  return { id: t.id, result: r }
}))
const out = args.trials.map((t, i) => results[i] || { id: t.id, result: null })
log(`${out.filter(r => r.result).length}/${out.length} trials returned a result`)
return { run: args.run, results: out }
