---
name: endpoint-probe
summary: Probe HTTP/API endpoints with crafted requests to characterise behaviour, errors and edge cases.
use_when: [a web service or API misbehaves, behaviour depends on request inputs or ordering, contract or status-code questions]
resource_kinds: [service, port]
verify_default: light
task_kinds: [endpoint, experiment]
---
# Lane: {{lane}}

## Mandate
{{mandate}}

## Resources
{{resources}}

## Method
1. List the endpoints in scope and their expected contract (method, inputs, status codes).
2. Probe with scripted requests (`curl -s -w '%{http_code} %{time_total}\n'` or a small
   Python script saved in your task directory); record full request and response excerpts.
3. Cover normal, boundary and malformed inputs, then ordering/concurrency only when your
   task claims the service's exclusive resource.
4. Report counts: statuses by input class, latencies (p50/p99 with n), error bodies.
5. Only targets and credentials the manifest allows; never production unless it says so.

## Evidence standard
{{evidence_standard}}

## Pitfalls
- Load or concurrency tests against a shared service → claim the exclusive resource first.
- Retries hiding failures → disable client retries; count every attempt.
- Caches and state carried between probes → reset state or record it before each probe.
- Credentials in artifacts → redact tokens and cookies.

## Typical tasks
- `endpoint` — Characterise /reserve responses for valid, boundary and invalid inputs.
- `experiment` — Fire N concurrent requests and compare the resulting state with the expected state.
