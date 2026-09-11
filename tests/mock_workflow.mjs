// Offline harness for investigate.js: runs the real script against a fake agent()
// and checks scheduler invariants. No tokens spent.  Usage: node tests/mock_workflow.mjs
import { readFileSync } from 'node:fs'
import assert from 'node:assert/strict'

const SRC = readFileSync(new URL('../investigate/kit/bin/investigate.js', import.meta.url), 'utf8')
  .replace(/^export const meta/m, 'const meta')
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor
const sleep = ms => new Promise(r => setTimeout(r, ms))

const BASE_ARGS = {
  inv: '/tmp/inv', board: 'python3 /tmp/inv/bin/board.py', start_round: 1,
  lanes: ['static', 'logs', 'experiments', 'skunkworks'], exclusive: ['port'],
  budget: { max_concurrent: 4, rounds_per_checkpoint: 2, max_rounds: 8, max_agents_per_segment: 60,
            max_tasks_per_lane_round: 3, verify_rounds: 2, max_children: 2, stall_rounds: 2 },
  models: {}, effort: { scope: 'low' }, agent_types: {},
}

// Task catalogue: resources, deps, verify, size, duration (ms), behaviour.
const TASKS = {
  'static-r01-01': { resources: ['repo'], deps: [], verify: 'light', size: 'short', dur: 50 },
  'static-r01-02': { resources: ['repo'], deps: ['static-r01-01'], verify: 'adversarial', size: 'short', dur: 50,
                     verdicts: ['revise', 'accept'] },
  'logs-r01-01': { resources: ['ci_logs'], deps: [], verify: 'none', size: 'short', dur: 30, dies: true },
  'experiments-r01-01': { resources: ['armbox', 'port'], deps: [], verify: 'light', size: 'long', dur: 900 },
  'experiments-r01-02': { resources: ['port'], deps: [], verify: 'none', size: 'short', dur: 40 },
  'experiments-r01-03': { resources: ['armbox'], deps: [], verify: 'none', size: 'short', dur: 40 },
  'static-r02-01': { resources: ['repo'], deps: [], verify: 'none', size: 'short', dur: 700 },
}
const PLANS = {
  1: { static: ['static-r01-01', 'static-r01-02'], logs: ['logs-r01-01'],
       experiments: ['experiments-r01-01', 'experiments-r01-02', 'experiments-r01-03'] },
  2: { static: ['static-r02-01'], experiments: ['experiments-r01-02'] },
}

function harness({ args = BASE_ARGS, tasks = TASKS, plans = PLANS, judge = r => ({ met: r >= 2, progress: true }), refute = () => false, failAll = false } = {}) {
  const logs = [], trace = []
  let active = 0, maxActive = 0
  const holders = new Map()      // exclusive resource -> task id (agent-level check)
  const violations = []
  const reviewCount = {}
  const t0 = Date.now()

  async function agent(prompt, o) {
    const role = /You are the (\w+)/.exec(prompt)[1].toLowerCase()
    const round = +/Round: (\d+)/.exec(prompt)[1]
    const lane = (/Lane: (\w+)/.exec(prompt) || [])[1]
    const tid = (/Task: (\S+)/.exec(prompt) || /Review task (\S+)/.exec(prompt) || /Task (\S+) \(lane/.exec(prompt) || [])[1]
    active++; maxActive = Math.max(maxActive, active)
    trace.push({ ev: 'start', role, tid, lane, round, label: o.label, at: Date.now() - t0 })
    const excl = tid ? (tasks[tid]?.resources || []).filter(r => args.exclusive.includes(r)) : []
    for (const r of excl) {
      if (holders.has(r) && holders.get(r) !== tid) violations.push(`${r} held by ${holders.get(r)} while ${tid} runs`)
      holders.set(r, tid)
    }
    try {
      if (failAll) { await sleep(2); return null } // terminal API error (rate / session limit)
      switch (role) {
        case 'scope': {
          await sleep(10)
          const idle = !(plans[round] && plans[round][lane])
          return { idle, brief_path: `lanes/${lane}/scope/round-0${round}.md`, summary: `scope ${lane}`, resources: [{ name: 'repo', ok: true }] }
        }
        case 'plan': {
          await sleep(10)
          const ids = plans[round][lane]
          return { plan_version: round, summary: `plan ${lane}`,
                   dispatch: ids.map(id => ({ id, title: id, kind: tasks[id].kind || 'other', ...pick(tasks[id], ['resources', 'deps', 'verify', 'size']), ...(tasks[id].items ? { items: tasks[id].items } : {}) })) }
        }
        case 'investigator': {
          const t = tasks[tid]
          if (/SWEEP ITEM/.test(prompt)) { await sleep(t.itemDur || 30); return { status: 'done', summary: `item of ${tid}` } }
          await sleep(t.dur)
          if (t.dies && !prompt.includes('REVISION')) return null
          return { status: t.status || 'done', summary: `${tid} result` }
        }
        case 'salvage': { await sleep(10); return { status: 'done', summary: `salvaged ${tid}` } }
        case 'challenger': {
          await sleep(10)
          const n = (reviewCount[tid] = (reviewCount[tid] || 0) + 1)
          const v = (tasks[tid].verdicts || ['accept'])[n - 1] || 'accept'
          return { verdict: v, summary: `review ${n}: ${v}` }
        }
        case 'synthesizer': { await sleep(10); return { summary: `synth r${round}` } }
        case 'judge': { await sleep(10); const j = judge(round); return { gaps: [], summary: `judge r${round}`, ...j } }
        case 'refuter': { await sleep(10); const r = refute(round); return { upheld: !r, objections: r ? ['criterion 2 unverified'] : [], summary: `refuter r${round}` } }
        case 'checkpoint': { await sleep(5); return { report_path: 'report.md', summary: 'checkpoint', open_questions: 0 } }
      }
      throw new Error('unknown role ' + role)
    } finally {
      for (const r of excl) if (holders.get(r) === tid) holders.delete(r)
      active--
      trace.push({ ev: 'end', role, tid, label: o.label, at: Date.now() - t0 })
    }
  }
  const budget = { total: null, spent: () => 0, remaining: () => Infinity }
  const fn = new AsyncFunction('agent', 'log', 'phase', 'args', 'budget', 'parallel', 'pipeline', SRC)
  return fn(agent, m => logs.push(m), () => {}, args, budget, null, null)
    .then(result => ({ result, logs, trace, maxActive, violations }))
}
const pick = (o, ks) => Object.fromEntries(ks.map(k => [k, o[k]]))
const starts = (trace, pred) => trace.filter(e => e.ev === 'start' && pred(e))
const window = (trace, label) => {
  const s = trace.find(e => e.ev === 'start' && e.label === label), e = trace.find(x => x.ev === 'end' && x.label === label)
  return s && e ? [s.at, e.at] : null
}
const overlap = (a, b) => a && b && a[0] < b[1] && b[0] < a[1]

let failed = 0
async function test(name, fn) {
  try { await fn(); console.log(`  ok: ${name}`) } catch (e) { failed++; console.log(`  FAIL: ${name}\n    ${e.message}`) }
}

console.log('== scenario: full two-round run')
const full = await harness()
await test('stops on met after 2 rounds', () => {
  assert.equal(full.result.reason, 'met'); assert.deepEqual(full.result.rounds_run, [1, 2])
})
await test('global concurrency never exceeds max_concurrent', () => assert.ok(full.maxActive <= 4, `max ${full.maxActive}`))
await test('no exclusive-resource overlap', () => assert.deepEqual(full.violations, []))
await test('dependency order: static-r01-02 starts after static-r01-01 ends', () => {
  const a = window(full.trace, 'static-r01-01'), b = window(full.trace, 'static-r01-02')
  assert.ok(a && b && b[0] >= a[1], `${a} vs ${b}`)
})
await test('long task spans rounds; exclusive-claim twin deferred then run after it', () => {
  const e1 = window(full.trace, 'experiments-r01-01'), e2 = window(full.trace, 'experiments-r01-02')
  assert.ok(full.logs.some(l => l.startsWith('experiments-r01-02: deferred — resource busy: port')), 'expected deferral log')
  assert.ok(e2, 'e2 should eventually run (round 2)')
  assert.ok(!overlap(e1, e2), `e1 ${e1} overlaps e2 ${e2}`)
  const r2scope = starts(full.trace, e => e.role === 'scope' && e.round === 2)[0]
  assert.ok(r2scope.at < e1[1], 'round 2 should start while the long task is still running')
})
await test('dead investigator is salvaged', () => {
  assert.equal(starts(full.trace, e => e.role === 'salvage' && e.tid === 'logs-r01-01').length, 1)
  assert.equal(full.result.rounds[0].tasks.find(t => t.id === 'logs-r01-01').status, 'done')
})
await test('adversarial verify: revise → revision → accept', () => {
  const t = full.result.rounds[0].tasks.find(t => t.id === 'static-r01-02')
  assert.deepEqual(t.verdicts, ['revise', 'accept'])
  assert.equal(starts(full.trace, e => e.label === 'static-r01-02 rev1').length, 1)
})
await test('idle lanes skip planning', () => {
  assert.equal(starts(full.trace, e => e.role === 'plan' && e.lane === 'skunkworks').length, 0)
})
await test('checkpoint runs after draining long tasks', () => {
  const cp = starts(full.trace, e => e.role === 'checkpoint')[0], e1 = window(full.trace, 'experiments-r01-01')
  assert.ok(cp && cp.at >= e1[1])
})

console.log('== scenario: stall')
const stall = await harness({ args: { ...BASE_ARGS, budget: { ...BASE_ARGS.budget, rounds_per_checkpoint: 4 } },
                              judge: () => ({ met: false, progress: false }) })
await test('stops after stall_rounds rounds without progress', () => {
  assert.equal(stall.result.reason, 'stall'); assert.deepEqual(stall.result.rounds_run, [1, 2])
})

console.log('== scenario: agent cap')
const capArgs = { ...BASE_ARGS, budget: { ...BASE_ARGS.budget, max_agents_per_segment: 16 } }
const cap = await harness({ args: capArgs, judge: () => ({ met: false, progress: true }) })
await test('reason agent_cap and never exceeds the cap', () => {
  assert.equal(cap.result.reason, 'agent_cap'); assert.ok(cap.result.agents_used <= 16, `${cap.result.agents_used}`)
})
await test('synthesis, judge and checkpoint still ran', () => {
  for (const r of ['synthesizer', 'judge', 'checkpoint']) assert.ok(starts(cap.trace, e => e.role === r).length >= 1, r)
})
await test('cap-limited work is logged, not silently dropped', () =>
  assert.ok(cap.logs.some(l => /agent cap|verification skipped/.test(l)), cap.logs.join('\n')))

console.log('== scenario: failed dependency')
const failTasks = { ...TASKS, 'static-r01-01': { ...TASKS['static-r01-01'], status: 'failed' } }
const dep = await harness({ tasks: failTasks })
await test('dependent of a failed task is not started', () => {
  assert.equal(starts(dep.trace, e => e.label === 'static-r01-02').length, 0)
  assert.ok(dep.logs.some(l => l.startsWith('static-r01-02: not started')))
})

console.log('== scenario: past max_rounds')
const past = await harness({ args: { ...BASE_ARGS, start_round: 9 } })
await test('no rounds, checkpoint only', () => {
  assert.equal(past.result.reason, 'max_rounds'); assert.deepEqual(past.result.rounds_run, [])
  assert.equal(starts(past.trace, e => e.role !== 'checkpoint').length, 0)
})

console.log('== scenario: every agent fails (API / session limit)')
const dead = await harness({ failAll: true })
await test('stops with reason error instead of reporting a normal checkpoint', () => assert.equal(dead.result.reason, 'error'))
await test('no synthesis or judge after a systemic failure', () => {
  assert.equal(starts(dead.trace, e => e.role === 'synthesizer' || e.role === 'judge').length, 0)
})
await test('failed round is not counted as run', () => {
  assert.deepEqual(dead.result.rounds_run, []); assert.equal(dead.result.next_round, 1)
})
await test('the failure is logged', () => assert.ok(dead.logs.some(l => /consecutive agent failures/.test(l)), dead.logs.join('\n')))

console.log('== scenario: confirm met')
await test('refuter runs only when the judge says met, and an upheld verdict stops', () => {
  assert.equal(starts(full.trace, e => e.role === 'refuter').length, 1)
  assert.equal(starts(full.trace, e => e.role === 'refuter')[0].round, 2)
})
await test('no refuter when the judge never says met', () => assert.equal(starts(stall.trace, e => e.role === 'refuter').length, 0))
const refuted = await harness({ args: { ...BASE_ARGS, budget: { ...BASE_ARGS.budget, rounds_per_checkpoint: 3 } },
                                judge: () => ({ met: true, progress: true }), refute: r => r === 1 })
await test('a refuted met verdict continues the investigation', () => {
  assert.equal(refuted.result.reason, 'met'); assert.deepEqual(refuted.result.rounds_run, [1, 2])
  assert.ok(refuted.logs.some(l => /refuted/.test(l)), refuted.logs.join('\n'))
})

console.log('== scenario: sweeps')
const SWEEP_TASKS = {
  'logs-r01-01': { kind: 'sweep', items: ['f1', 'f2', 'f3'], resources: ['logs'], deps: [], verify: 'light', size: 'short', dur: 20, itemDur: 60 },
  'experiments-r01-01': { kind: 'sweep', items: ['c1', 'c2', 'c3'], resources: ['port'], deps: [], verify: 'none', size: 'short', dur: 20, itemDur: 40 },
  'static-r01-01': { kind: 'sweep', items: ['a', 'b', 'c', 'd', 'e'], resources: ['repo'], deps: [], verify: 'none', size: 'short', dur: 20, itemDur: 10 },
}
const SWEEP_PLANS = { 1: { logs: ['logs-r01-01'], experiments: ['experiments-r01-01'], static: ['static-r01-01'] } }
const sw = await harness({ tasks: SWEEP_TASKS, plans: SWEEP_PLANS, judge: () => ({ met: true, progress: true }),
                           args: { ...BASE_ARGS, budget: { ...BASE_ARGS.budget, max_sweep_items: 4 } } })
const itemWin = (tid) => sw.trace.filter(e => e.ev === 'start' && e.label && e.label.startsWith(`${tid} item`)).map(e => window(sw.trace, e.label))
await test('one agent per item plus a reducer', () => {
  assert.equal(itemWin('logs-r01-01').length, 3)
  assert.equal(starts(sw.trace, e => e.label === 'logs-r01-01 reduce').length, 1)
})
await test('reducer starts after every item finished', () => {
  const red = window(sw.trace, 'logs-r01-01 reduce'); assert.ok(itemWin('logs-r01-01').every(w => w[1] <= red[0]))
})
await test('items run in parallel without exclusive claims', () => {
  const w = itemWin('logs-r01-01'); assert.ok(w.some((a, i) => w.some((b, j) => i !== j && overlap(a, b))), JSON.stringify(w))
})
await test('items run one at a time when the task holds an exclusive resource', () => {
  const w = itemWin('experiments-r01-01'); assert.equal(w.length, 3)
  assert.ok(!w.some((a, i) => w.some((b, j) => i !== j && overlap(a, b))), JSON.stringify(w))
})
await test('items beyond max_sweep_items are dropped and logged', () => {
  assert.equal(itemWin('static-r01-01').length, 4)
  assert.ok(sw.logs.some(l => /static-r01-01: sweep capped at 4 of 5 items/.test(l)), sw.logs.join('\n'))
})
await test('sweeps keep global concurrency and exclusivity invariants', () => {
  assert.ok(sw.maxActive <= 4, `max ${sw.maxActive}`); assert.deepEqual(sw.violations, [])
})

console.log('== scenario: concurrency 1')
const one = await harness({ args: { ...BASE_ARGS, budget: { ...BASE_ARGS.budget, max_concurrent: 1 } } })
await test('max_concurrent=1 is strictly serial and still completes', () => {
  assert.equal(one.maxActive, 1); assert.equal(one.result.reason, 'met')
})

console.log(failed ? `${failed} FAILED` : 'ALL WORKFLOW TESTS PASSED')
process.exit(failed ? 1 : 0)
