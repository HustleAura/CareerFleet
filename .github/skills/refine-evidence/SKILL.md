---
name: refine-evidence
description: "Find spans in a raw speech-to-text walkthrough transcript where the meaning may have been corrupted, and turn them into clarification questions. Used by the Transcript Refiner agents before any scoring happens. Not for scoring."
---

# Refine a Raw Transcript

Speech-to-text mangles technical terms and numbers. Anything scored off a
garbled line is a scoring error, not a candidate error. Your job is to find
every span worth checking, and nothing else.

You are one of two independent refiners. Do not read any other refiner's output.
Do not score anything, and do not judge the design.

## What to flag

- Mangled technical terms — `Kafka`, `CQRS`, `sharding`, `idempotent`, `quorum`,
  `CDN`, `Redis`, `gRPC`, database and product names
- Numbers that did not survive — "ten thousand QPS", "one hundred million rows",
  units dropped, orders of magnitude that contradict a nearby line
- Broken or truncated sentences, `[inaudible]`-style gaps, dead spans
- Logical jumps where a reasoning step seems missing — often a transcription
  artifact rather than a real gap in thinking
- Exact or near-exact repeated phrases — these are decoder artifacts, not
  rambling. Flag them so they are not mistaken for poor communication.

## What not to flag

- A decision you disagree with. That is the evaluator's job, not yours.
- A gap that is clearly a real gap — silence on caching is evidence, not noise.
- Anything you would only ask in order to give the candidate a second attempt.

## How to phrase a question

For each span: quote the exact line with its timestamp, state how you read it,
and probe the decision behind it rather than the misheard word.

> `[04:12] "we'll use Kafla for the right ahead log"`
> Read as: Kafka for the write-ahead log. What was the reasoning for putting a
> log there rather than writing straight to the database?

## Output

Return **only** this JSON object as your final message.

```json
{
  "schema_version": 1,
  "session_id": "<the session id you were given>",
  "items": [
    {
      "timestamp": "[04:12]",
      "quote": "we'll use Kafla for the right ahead log",
      "reading": "Kafka for the write-ahead log",
      "question": "What was the reasoning for putting a log there rather than writing straight to the database?",
      "kind": "term"
    }
  ],
  "repetition_spans": ["[28:10]-[31:45]"],
  "unrecoverable_spans": ["[14:31]-[14:58]"],
  "clean": false
}
```

`kind` is one of `term`, `number`, `truncation`, `logic-jump`.
Set `clean` to `true` and `items` to `[]` if the transcript needs nothing.

`unrecoverable_spans` are spans no question can repair. They become unavailable
evidence at scoring time — neither credited nor penalised.
