export const meta = {
  name: 'investigate-segment',
  description: 'Run one checkpoint segment of a multi-lane investigation: scope, plan, investigate+verify, synthesize, judge',
  whenToUse: 'Launched by /investigate:run with args from `board.py wf-args`; not meant to be run by hand',
  phases: [
    { title: 'Scope & plan', detail: 'per lane: scope brief, then task plan (pipelined, no barrier across lanes)' },
    { title: 'Investigate', detail: 'task chains under the global pool: investigator, challenger, revise, salvage' },
    { title: 'Synthesize', detail: 'dedupe, contradictions, promote to the shared board' },
    { title: 'Judge', detail: 'criteria vs shared board; a met verdict must survive a refuter' },
    { title: 'Checkpoint', detail: 'drain long tasks, clean leftovers, write the report' },
  ],
}

// ------------------------------------------------------------------ inputs
// args come from `board.py wf-args` (see DESIGN.md §5). The script cannot read files,
// so everything it needs to schedule arrives here or in agent return values.
if (!args || !args.inv || !args.board || !args.budget || !Array.isArray(args.lanes)) {
  throw new Error('investigate-segment needs args from `board.py wf-args` (inv, board, lanes, budget, ...). Use /investigate:run.')
}
const A = args
const INV = A.inv
const BOARD = A.board
const B = A.budget
const LANES = A.lanes
const EXCL = new Set(A.exclusive || [])
const RESERVE = 4 // synthesize + judge + refuter + checkpoint are always affordable
const SWEEP_CAP = B.max_sweep_items ?? 12
const pad = n => String(n).padStart(2, '0')

// ------------------------------------------------------------------ schemas
const str = (max) => (max ? { type: 'string', maxLength: max } : { type: 'string' })
const strs = { type: 'array', items: { type: 'string' } }
const SCOPE = {
  type: 'object', required: ['idle', 'brief_path', 'summary', 'resources'],
  properties: {
    idle: { type: 'boolean' },
    brief_path: str(),
    summary: str(600),
    resources: { type: 'array', items: { type: 'object', required: ['name', 'ok'],
      properties: { name: str(), ok: { type: 'boolean' }, note: str(300) } } },
  },
}
const PLAN = {
  type: 'object', required: ['dispatch', 'summary'],
  properties: {
    plan_version: { type: 'integer' },
    summary: str(600),
    dispatch: { type: 'array', items: { type: 'object', required: ['id', 'title', 'resources', 'deps', 'verify', 'size'],
      properties: {
        id: str(), title: str(200), kind: str(), items: strs, resources: strs, deps: strs,
        verify: { type: 'string', enum: ['none', 'light', 'adversarial'] },
        size: { type: 'string', enum: ['short', 'long'] },
      } } },
  },
}
const RESULT = {
  type: 'object', required: ['status', 'summary'],
  properties: {
    status: { type: 'string', enum: ['done', 'partial', 'failed', 'blocked'] },
    summary: str(600), board_ids: strs, artifacts: strs,
  },
}
const VERDICT = {
  type: 'object', required: ['verdict', 'summary'],
  properties: { verdict: { type: 'string', enum: ['accept', 'revise', 'redo'] }, summary: str(600), objections: strs },
}
const SYNTH = {
  type: 'object', required: ['summary'],
  properties: {
    merged: { type: 'integer' }, promoted: { type: 'integer' }, contradictions: { type: 'integer' },
    flagged: { type: 'integer' }, escalations: { type: 'integer' }, summary: str(800),
  },
}
const JUDGE = {
  type: 'object', required: ['met', 'progress', 'gaps', 'summary'],
  properties: { met: { type: 'boolean' }, progress: { type: 'boolean' }, gaps: strs, summary: str(800) },
}
const REFUTE = {
  type: 'object', required: ['upheld', 'summary'],
  properties: { upheld: { type: 'boolean' }, objections: strs, summary: str(800) },
}
const CHECKPOINT = {
  type: 'object', required: ['report_path', 'summary'],
  properties: { report_path: str(), summary: str(2000), open_questions: { type: 'integer' }, leftovers_cleaned: { type: 'integer' } },
}

// ------------------------------------------------------------------ agent pool
let agentsUsed = 0
let capHit = false
let tokenStop = false
const slots = { free: Math.max(1, B.max_concurrent), waiters: [] }
const acquire = () => (slots.free > 0 ? (slots.free--, Promise.resolve()) : new Promise(r => slots.waiters.push(r)))
const release = () => { const w = slots.waiters.shift(); if (w) w(); else slots.free++ }
const tokenLow = () => {
  if (budget.total && budget.remaining() < 40000) { tokenStop = true; return true }
  return false
}
const canAfford = (n) => agentsUsed + n + RESERVE <= B.max_agents_per_segment

function opts(role, o) {
  const x = { ...o }
  if (A.models && A.models[role]) x.model = A.models[role]
  if (A.effort && A.effort[role]) x.effort = A.effort[role]
  if (A.agent_types && A.agent_types[role]) x.agentType = A.agent_types[role]
  return x
}

// A run of consecutive dead agents means the API itself is failing (rate or session
// limit, outage) rather than one bad task: stop spending agents and checkpoint.
const FAIL_STOP = Math.max(3, LANES.length)
let failStreak = 0
const systemic = () => failStreak >= FAIL_STOP

// Every agent goes through here: global concurrency pool + agent accounting.
// Returns null (never throws) so callers treat budget exhaustion like a dead agent.
async function run(prompt, o) {
  if (systemic()) return null
  agentsUsed++
  await acquire()
  let r = null
  try {
    r = await agent(prompt, o)
  } catch (e) {
    log(`agent ${o.label} errored: ${String(e).slice(0, 200)}`)
  } finally {
    release()
  }
  failStreak = r ? 0 : failStreak + 1
  if (failStreak === FAIL_STOP) log(`${FAIL_STOP} consecutive agent failures — likely an API, rate or session limit; stopping this segment.`)
  return r
}

// ------------------------------------------------------------------ prompts
// Prompts carry parameters only; role instructions live in the investigation's prompt pack.
function header(role, round, who, lane, briefArgs = '') {
  return [
    `You are the ${role.toUpperCase()} in a structured investigation.`,
    `Investigation directory: ${INV}`,
    `Board CLI: ${BOARD}   (an executable; pass --as ${who} on every call)`,
    `Round: ${round}${lane ? `   Lane: ${lane}` : ''}`,
    `Your first action: ${BOARD} brief --role ${role}${lane ? ` --lane ${lane}` : ''}${briefArgs} --as ${who}`,
    `It prints the protocol, your role instructions, ${lane ? 'your lane, ' : ''}the manifest essentials and the state you need. Follow them exactly.`,
  ].join('\n')
}

const scopePrompt = (lane, round, ctx) => [
  header('scope', round, `${lane}/scope`, lane),
  `Write your brief with: ${BOARD} write --path lanes/${lane}/scope/round-${pad(round)}.md --as ${lane}/scope <<'EOF' ... EOF`,
  `In flight from earlier rounds (still running, not yours to re-plan): ${ctx.inflight.join(', ') || 'none'}`,
  `Deferred last round (still queued; planner must resubmit or drop): ${ctx.deferred.join(', ') || 'none'}`,
  `Exclusive resources held by running tasks (any lane): ${ctx.held.join('; ') || 'none'}`,
  `Return brief_path = lanes/${lane}/scope/round-${pad(round)}.md, idle=true only if the lane has nothing worth doing this round.`,
].join('\n\n')

const planPrompt = (lane, round, brief, ctx) => [
  header('plan', round, `${lane}/plan`, lane, ` --round ${round}`),
  `Scope summary: ${brief.summary}   (the full scope brief is included in your brief output)`,
  `At most ${B.max_tasks_per_lane_round} queued tasks. New task ids: ${lane}-r${pad(round)}-01, -02, ...`,
  `In flight (leave out of the plan): ${ctx.inflight.join(', ') || 'none'}`,
  `Exclusive resources held by running tasks (any lane): ${ctx.held.join('; ') || 'none'} — a task claiming one of these waits until it is released.`,
  `Save with: ${BOARD} plan save --lane ${lane} --round ${round} --inflight "${ctx.inflight.join(',')}" --as ${lane}/plan <<'EOF' {json} EOF`,
  `Return the "dispatch" list and "version" exactly as plan save printed them (dispatch=[] if you queued nothing).`,
].join('\n\n')

const investigatorPrompt = (t, round, rev) => [
  header('investigator', round, `${t.lane}/${t.id}`, t.lane),
  `Task: ${t.id} — ${t.title}`,
  `Start with: ${BOARD} task start --id ${t.id} --as ${t.lane}/${t.id}   (prints the full task spec)`,
  rev
    ? `This is REVISION ${rev} of this task. A challenger objected: read ${INV}/lanes/${t.lane}/tasks/${t.id}/review-${rev}.json and your prior result.json first, and address every objection.`
    : `This is the first attempt in this round.`,
  `You may spawn at most ${t.max_children ?? B.max_children} child subagent(s). Finish with ${BOARD} task finish ... and return the same status/summary.`,
].join('\n\n')

const sweepItemPrompt = (t, round, item, k, n) => [
  header('investigator', round, `${t.lane}/${t.id}`, t.lane),
  `Task: ${t.id} — ${t.title}`,
  `SWEEP ITEM ${k}/${n}: ${item}`,
  `Read the task spec with: ${BOARD} task show --id ${t.id}. Apply its per-item instructions to THIS ITEM ONLY; other agents handle the other items in parallel.`,
  `Record your item result with: ${BOARD} task item --id ${t.id} --n ${k} --status done|partial|failed|blocked --summary "..." [--board-ids ...] --as ${t.lane}/${t.id}`,
  `Do NOT call task finish — a reducer aggregates all items afterwards.`,
].join('\n\n')

const reducePrompt = (t, round, n, rev) => [
  header('investigator', round, `${t.lane}/${t.id}`, t.lane),
  `Task: ${t.id} — ${t.title}`,
  rev
    ? `REDUCE, REVISION ${rev}: a challenger objected — read review-${rev}.json in the task directory and address every objection.`
    : `REDUCE: all ${n} sweep items have run; \`${BOARD} task show --id ${t.id}\` lists each item's result.`,
  `Aggregate the item results into the task's deliverable, post what it establishes to the board, then ${BOARD} task finish ... and return the same status/summary.`,
].join('\n\n')

const refuterPrompt = (round) => [
  header('refuter', round, 'refuter', null),
  `The judge declared every success criterion met in round ${round} (judge/round-${pad(round)}.json). The investigation stops if this verdict stands.`,
  `If a criterion is not actually met, record it with: ${BOARD} judge refute --round ${round} --objection "..." [--objection ...] --as refuter`,
  `Return upheld=true only if every criterion survives your attempt to refute it.`,
].join('\n\n')

const challengerPrompt = (t, round, n, allowRevise) => [
  header('challenger', round, `${t.lane}/challenger`, t.lane, ` --task ${t.id}`),
  `Review task ${t.id} — ${t.title}   (verify level: ${t.verify}, review ${n})`,
  `Allowed verdicts: ${allowRevise ? 'accept | revise | redo' : 'accept | redo  (no revisions left)'}`,
  `Record it with: ${BOARD} task review --id ${t.id} --verdict V --summary S [--objection O ...] --as ${t.lane}/challenger`,
].join('\n\n')

const salvagePrompt = (t, round, why) => [
  header('salvage', round, `skunkworks/salvage-${t.id}`, null, ` --task ${t.id}`),
  `Task ${t.id} (lane ${t.lane}) lost its agent: ${why}.`,
].join('\n\n')

const synthPrompt = (round, results) => [
  header('synthesizer', round, 'synthesizer', null, ` --round ${round}`),
  `Lanes: ${LANES.join(', ')}`,
  `Tasks finished since the last synthesis: ${results.map(r => `${r.id}=${r.status}`).join(', ') || 'none'}`,
].join('\n\n')

const judgePrompt = (round, stall) => [
  header('judge', round, 'judge', null),
  `Rounds without progress so far: ${stall} (stop threshold ${B.stall_rounds}).`,
  `Save with: ${BOARD} judge save --round ${round} --as judge <<'EOF' {"met":..,"progress":..,"gaps":[..],"summary":".."} EOF`,
].join('\n\n')

const checkpointPrompt = (first, last, reason, extra) => [
  header('checkpoint', Math.max(first, last), 'checkpoint', null),
  last >= first ? `Segment covered rounds ${first}-${last}. Stop reason: ${reason}.`
    : `No round ran this segment (next round would have been ${first}). Stop reason: ${reason}.`,
  `Agents used this segment, including you: ${agentsUsed + 1}/${B.max_agents_per_segment}.`,
  `Deferred (not started) tasks: ${extra.deferred.join(', ') || 'none'}`,
  `Tasks whose agent and salvage both died: ${extra.lost.join(', ') || 'none'}`,
  `Finished after the last synthesis (not yet on the shared board — cover them): ${extra.late.join(', ') || 'none'}`,
  last >= first
    ? `Close the segment with: ${BOARD} segment close --start ${first} --end ${last} --reason ${reason} --as checkpoint`
    : `Do not close a segment (no rounds ran).`,
].join('\n\n')

// ------------------------------------------------------------------ task chains
// investigator → [challenger → (revise → challenger)*]; a dead investigator is replaced by salvage.
async function runTask(t, round) {
  const verdicts = []
  let unverified = false
  const sweep = t.kind === 'sweep' && Array.isArray(t.items) && t.items.length > 0
  let items = sweep ? t.items : []
  const work = async (rev) => {
    const r = sweep
      ? await run(reducePrompt(t, round, items.length, rev),
          opts('investigator', { label: `${t.id} reduce${rev ? ` rev${rev}` : ''}`, phase: 'Investigate', schema: RESULT }))
      : await run(investigatorPrompt(t, round, rev),
          opts('investigator', { label: `${t.id}${rev ? ` rev${rev}` : ''}`, phase: 'Investigate', schema: RESULT }))
    if (r) return r
    log(`${t.id}: investigator lost → salvage`)
    return run(salvagePrompt(t, round, rev ? `died during revision ${rev}` : 'died or was stopped'),
      opts('salvage', { label: `salvage ${t.id}`, phase: 'Investigate', schema: RESULT }))
  }
  if (sweep) {
    const affordable = Math.max(0, B.max_agents_per_segment - agentsUsed - RESERVE - 1)
    const cap = Math.min(SWEEP_CAP, affordable)
    if (items.length > cap) { log(`${t.id}: sweep capped at ${cap} of ${items.length} items (${cap < SWEEP_CAP ? 'agent budget' : 'max_sweep_items'})`); items = items.slice(0, cap) }
    const doItem = (it, i) => run(sweepItemPrompt(t, round, it, i + 1, items.length),
      opts('investigator', { label: `${t.id} item ${i + 1}/${items.length}`, phase: 'Investigate', schema: RESULT }))
    let itemResults = []
    if (exclusiveOf(t).length) for (let i = 0; i < items.length; i++) itemResults.push(await doItem(items[i], i))  // one at a time on an exclusive resource
    else itemResults = await Promise.all(items.map(doItem))
    const lostItems = itemResults.filter(r => !r).length
    if (lostItems) log(`${t.id}: ${lostItems} of ${items.length} sweep items lost; the reducer sees which are missing`)
  }
  let res = await work(0)
  if (!res) return { id: t.id, lane: t.lane, status: 'lost', summary: 'investigator and salvage both failed', verdicts }
  if (t.verify !== 'none' && (res.status === 'done' || res.status === 'partial')) {
    const maxReviews = t.verify === 'adversarial' ? Math.max(1, B.verify_rounds) : 1
    for (let n = 1; n <= maxReviews; n++) {
      if (!canAfford(1) || tokenLow()) { unverified = true; log(`${t.id}: verification skipped (budget)`); break }
      const allowRevise = t.verify === 'adversarial' && n < maxReviews
      const v = await run(challengerPrompt(t, round, n, allowRevise),
        opts('challenger', { label: `challenge ${t.id} #${n}`, phase: 'Investigate', schema: VERDICT }))
      if (!v) { unverified = true; break }
      verdicts.push(v.verdict)
      if (v.verdict === 'accept') break
      if (v.verdict === 'redo' || !allowRevise) { res = { ...res, status: 'needs_redo', summary: v.summary }; break }
      if (!canAfford(1)) { unverified = true; log(`${t.id}: revision skipped (agent cap)`); break }
      const r2 = await work(n)
      if (!r2) { res = { ...res, status: 'lost', summary: 'revision lost' }; break }
      res = r2
    }
  }
  return { id: t.id, lane: t.lane, status: res.status, summary: res.summary, verdicts, unverified }
}

// ------------------------------------------------------------------ scheduler
const inflight = new Map()   // id -> { t, p }
const pending = []           // tasks waiting for slot / deps / claims
const finished = new Map()   // id -> status (this segment)
const held = new Set()       // exclusive resources currently claimed
let planningOpen = 0
let sinceSynth = []          // results not yet seen by a synthesizer
const lost = []
let deferredPrev = []        // ids deferred in the previous round (for scope/plan prompts)

let dirty = false
let wake = null
const notify = () => { dirty = true; if (wake) { const w = wake; wake = null; w() } }
const waitChange = async () => { if (!dirty) await new Promise(r => { wake = r }); dirty = false }

const exclusiveOf = t => t.resources.filter(r => EXCL.has(r))
const claimsFree = t => exclusiveOf(t).every(r => !held.has(r))
function depState(t) {
  for (const d of t.deps) {
    if (finished.has(d)) { if (!['done', 'partial'].includes(finished.get(d))) return 'failed'; continue }
    if (inflight.has(d) || pending.some(p => p.id === d)) return 'wait'
    if (planningOpen > 0) return 'wait' // may still be planned this round
    // otherwise it finished in an earlier segment (plan save validated it exists)
  }
  return 'ok'
}
function whyBlocked(t) {
  const ds = depState(t)
  if (ds === 'wait') return `waiting on deps ${t.deps.join(',')}`
  if (!claimsFree(t)) return `resource busy: ${exclusiveOf(t).filter(r => held.has(r)).join(',')}`
  if (systemic()) return 'agents failing (API / rate / session limit)'
  if (capHit) return 'agent cap for this segment'
  if (tokenStop) return 'token budget'
  return 'dependency cycle or no slot'
}

function start(t, round) {
  exclusiveOf(t).forEach(r => held.add(r))
  const p = runTask(t, round)
    .catch(e => ({ id: t.id, lane: t.lane, status: 'lost', summary: String(e).slice(0, 300), verdicts: [] }))
    .then(r => {
      exclusiveOf(t).forEach(x => held.delete(x))
      inflight.delete(t.id)
      finished.set(t.id, r.status)
      sinceSynth.push(r)
      if (r.status === 'lost') lost.push(t.id)
      log(`${t.id} → ${r.status}${r.verdicts.length ? ` [${r.verdicts.join('>')}]` : ''}${r.unverified ? ' (unverified)' : ''}: ${r.summary.slice(0, 140)}`)
      notify()
      return r
    })
  inflight.set(t.id, { t, p })
}

function pump(round) {
  for (let i = 0; i < pending.length;) {
    const t = pending[i]
    const ds = depState(t)
    if (ds === 'failed') {
      pending.splice(i, 1)
      log(`${t.id}: not started — a dependency did not succeed (stays queued for the planner)`)
      continue
    }
    if (ds === 'wait' || !claimsFree(t) || inflight.size >= B.max_concurrent) { i++; continue }
    if (systemic()) { i++; continue }
    if (!canAfford(1) || tokenLow()) { if (!tokenStop) capHit = true; i++; continue }
    pending.splice(i, 1)
    start(t, round)
  }
}

function submit(lane, dispatch, round) {
  const cap = B.max_tasks_per_lane_round
  const ok = []
  for (const d of dispatch) {
    if (!d.id.startsWith(`${lane}-r`)) { log(`${lane}: ignored task ${d.id} (wrong lane prefix)`); continue }
    if (inflight.has(d.id) || pending.some(p => p.id === d.id) || finished.get(d.id) === 'done') {
      log(`${lane}: ignored duplicate ${d.id}`); continue
    }
    ok.push({ ...d, lane })
  }
  if (ok.length > cap) log(`${lane}: planner queued ${ok.length} tasks; dispatching first ${cap}, rest stay queued`)
  pending.push(...ok.slice(0, cap))
  pump(round)
}

// One lane's scope → plan, pipelined: its tasks start as soon as its plan lands.
async function planLane(lane, round) {
  try {
    const ctx = {
      inflight: [...inflight.values()].filter(x => x.t.lane === lane).map(x => x.t.id),
      deferred: deferredPrev.filter(id => id.startsWith(`${lane}-`)),
      held: [...inflight.values()].flatMap(x => exclusiveOf(x.t).map(r => `${r} held by ${x.t.id} (${x.t.size}, lane ${x.t.lane})`)),
    }
    const brief = await run(scopePrompt(lane, round, ctx),
      opts('scope', { label: `r${round} scope:${lane}`, phase: 'Scope & plan', schema: SCOPE }))
    if (!brief) { log(`${lane}: scope agent lost; lane skipped this round`); return }
    const bad = (brief.resources || []).filter(r => !r.ok)
    if (bad.length) log(`${lane}: resources unavailable — ${bad.map(r => `${r.name}${r.note ? ` (${r.note})` : ''}`).join('; ')}`)
    if (brief.idle) { log(`${lane}: idle this round — ${brief.summary.slice(0, 120)}`); return }
    const plan = await run(planPrompt(lane, round, brief, ctx),
      opts('plan', { label: `r${round} plan:${lane}`, phase: 'Scope & plan', schema: PLAN }))
    if (!plan) { log(`${lane}: planner lost; lane skipped this round`); return }
    log(`${lane}: plan v${plan.plan_version ?? '?'} — ${plan.dispatch.length} task(s). ${plan.summary.slice(0, 120)}`)
    submit(lane, plan.dispatch, round)
  } finally {
    planningOpen--
    notify()
  }
}

// ------------------------------------------------------------------ rounds
const first = A.start_round
const last = Math.min(first + Math.max(1, B.rounds_per_checkpoint) - 1, B.max_rounds)
const rounds = []
let reason = 'checkpoint'
let stall = 0
let round = first

if (first > B.max_rounds) {
  reason = 'max_rounds'
  log(`Round ${first} exceeds max_rounds=${B.max_rounds}; only writing a checkpoint report.`)
}

for (; round <= last && reason === 'checkpoint'; round++) {
  const planCost = LANES.length * 2
  if (!canAfford(planCost + 1)) { capHit = true; reason = 'agent_cap'; log(`Agent cap: ${agentsUsed}/${B.max_agents_per_segment} used; not starting round ${round}.`); break }
  if (tokenLow()) { reason = 'token_budget'; log('Token budget nearly spent; not starting another round.'); break }

  log(`— Round ${round} — lanes: ${LANES.join(', ')}${inflight.size ? `; ${inflight.size} long task(s) still running` : ''}`)
  planningOpen = LANES.length
  const planning = LANES.map(l => planLane(l, round))

  // Round ends when planning is done and every short task has finished; long tasks may continue.
  for (;;) {
    pump(round)
    const shortBusy = [...inflight.values()].some(x => x.t.size !== 'long')
    if (planningOpen === 0 && !shortBusy) break
    await waitChange()
  }
  await Promise.all(planning)
  const deferred = pending.splice(0).map(t => { log(`${t.id}: deferred — ${whyBlocked(t)}`); return t.id })
  deferredPrev = deferred
  if (systemic()) { reason = 'error'; break }

  const results = sinceSynth
  sinceSynth = []
  const synth = await run(synthPrompt(round, results),
    opts('synthesizer', { label: `r${round} synthesize`, phase: 'Synthesize', schema: SYNTH }))
  if (synth) log(`synthesis: ${synth.summary.slice(0, 200)}`)
  const verdict = await run(judgePrompt(round, stall),
    opts('judge', { label: `r${round} judge`, phase: 'Judge', schema: JUDGE }))

  rounds.push({
    round,
    tasks: results.map(r => ({ id: r.id, status: r.status, verdicts: r.verdicts, unverified: !!r.unverified })),
    deferred,
    synthesis: synth ? synth.summary : null,
    judge: verdict,
  })
  if (!verdict) { log(`Round ${round}: judge lost — counting as no progress.`); stall++ }
  else {
    log(`Round ${round} judge: met=${verdict.met} progress=${verdict.progress} — ${verdict.summary.slice(0, 200)}`)
    if (verdict.met) {
      // stopping is the costliest decision: a fresh refuter must fail to overturn it
      const check = await run(refuterPrompt(round), opts('refuter', { label: `r${round} refute met`, phase: 'Judge', schema: REFUTE }))
      rounds[rounds.length - 1].refuter = check
      if (!check) { log(`Round ${round}: refuter lost — accepting the judge's met verdict unconfirmed.`); reason = 'met'; break }
      if (check.upheld) { reason = 'met'; break }
      log(`Round ${round}: met verdict refuted — ${(check.objections || []).join('; ').slice(0, 300)}`)
      verdict.met = false
    }
    stall = verdict.progress ? 0 : stall + 1
  }
  if (stall >= B.stall_rounds) { reason = 'stall'; log(`${stall} round(s) without progress; stopping.`); break }
  if (round >= B.max_rounds) { reason = 'max_rounds'; break }
  if (capHit) { reason = 'agent_cap'; log('Agent cap reached during the round; checkpointing.'); break }
  if (tokenStop) { reason = 'token_budget'; break }
}
const lastRound = rounds.length ? rounds[rounds.length - 1].round : first - 1

// ------------------------------------------------------------------ checkpoint
if (inflight.size) {
  log(`Draining ${inflight.size} in-flight long task(s) before the checkpoint: ${[...inflight.keys()].join(', ')}`)
  await Promise.all([...inflight.values()].map(x => x.p))
}
const late = sinceSynth.map(r => ({ id: r.id, status: r.status, verdicts: r.verdicts, unverified: !!r.unverified }))

phase('Checkpoint')
const cp = await run(checkpointPrompt(first, lastRound, reason, { deferred: deferredPrev, lost, late: late.map(r => `${r.id}=${r.status}`) }),
  opts('checkpoint', { label: 'checkpoint report', phase: 'Checkpoint', schema: CHECKPOINT }))

return {
  reason,
  rounds_run: rounds.map(r => r.round),
  next_round: lastRound + 1,
  agents_used: agentsUsed,
  rounds,
  finished_after_last_synthesis: late,
  deferred: deferredPrev,
  lost,
  report_path: cp ? cp.report_path : null,
  summary: cp ? cp.summary
    : reason === 'error'
      ? 'Segment stopped: repeated agent failures (API, rate or session limit). No report was written and the round was not counted; relaunch with /investigate:run once the limit resets.'
      : 'checkpoint agent failed — run `board.py status` and read judge/ for the latest state',
  open_questions: cp ? cp.open_questions : null,
}
