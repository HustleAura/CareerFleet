# Rubric

The stable keys for the whole progress system. Session cards, the weakness
ledger, and `STATE.md` all reference the names defined here verbatim.

Do not rename a dimension or a concept tag once it has been used in a session
card — the history stops lining up.

## Scored dimensions

Six dimensions, each `0-10`, plus a separate `Overall` `0-10`.

`Overall` is a holistic judgement at the ~2 YOE (SDE-2) bar, not the mean of the
six. A design can score decently across dimensions and still be a weak overall
answer if the pieces don't cohere.

| # | Dimension | What it measures |
|---|---|---|
| 1 | Requirements & scoping | Drove clarifying questions, separated functional from non-functional, bounded the problem before designing |
| 2 | Capacity & back-of-envelope math | Estimated QPS, storage, bandwidth; closed the numbers; let the math drive decisions |
| 3 | API & data model | Sensible endpoints/contracts, entities, keys, indexes, access patterns |
| 4 | Core architecture & component choice | Coherent component breakdown, justified technology picks, correct data flow |
| 5 | Scale, reliability & bottlenecks | Found the real bottleneck, addressed SPOFs, handled failure and growth |
| 6 | Tradeoff reasoning & communication | Named alternatives and picked between them out loud; structured, followable delivery |

### Null vs zero

This is a hard invariant, not a convention.

- `null` — **not demonstrated.** The walkthrough never touched this. Not the
  candidate's fault and not evidence of anything. Excluded from every average.
- `0` — **attempted and failed.** It was in scope, they engaged with it, it was
  wrong or absent where it clearly belonged.

Never write `0` to mean "didn't come up". Never drop a row to mean `null`.

## Concept tags

Closed set. Every weakness on a session card carries exactly one tag from this
list, and the weakness ledger dedupes on it.

To add a tag, append it here first — then use it. Never reuse a retired name.

| Tag | Covers |
|---|---|
| `requirements-clarification` | Assumed instead of asked; missed a scoping constraint |
| `capacity-estimation` | No math, abandoned math, or numbers that don't reconcile |
| `api-design` | Non-RESTful or incoherent contracts, missing pagination/idempotency |
| `data-modeling` | Wrong entities, missing indexes, model that fights the access pattern |
| `db-selection` | Unjustified SQL/NoSQL pick, wrong store for the workload |
| `sharding-partitioning` | No partition key, hot partitions, unaddressed rebalancing |
| `replication-consistency` | Hand-waved consistency, ignored CAP tradeoff, no replication story |
| `caching` | No cache where one is needed, no eviction/invalidation/TTL story |
| `cdn-static-delivery` | Static or media assets served straight from origin |
| `async-messaging` | Sync where async belongs, no queue, no retry/DLQ/backpressure |
| `load-balancing` | No LB, no routing story, unconsidered stickiness or health checks |
| `single-point-of-failure` | A component whose loss takes the system down, unaddressed |
| `scaling-bottlenecks` | Missed the actual bottleneck, or scaled the wrong tier |
| `observability` | No metrics, logging, tracing, or alerting story |
| `security-authz` | No authn/authz, exposed internals, unhandled abuse or rate limiting |
| `tradeoff-articulation` | Made a choice without naming what was given up |
| `communication-structure` | Rambling, no order to the walkthrough, buried the design |

## Difficulty rungs

Closed set, matching what the interviewer offers: `basic`, `easy`, `medium`,
`hard`, `architect`.

Scores are **never normalized across rungs.** A 7 at `easy` and a 7 at `hard`
are different achievements and stay in separate rows forever.
