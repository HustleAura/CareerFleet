---
name: refine-evidence
description: "Use before scoring a design transcript to find speech-to-text corruption, ask what was actually spoken, and prepare the final clarified transcript. Performed by the interviewer, not a subagent."
---

# Refine the Transcript

Read the entire raw transcript yourself. Do not score yet. Keep findings in the
conversation, not a machine protocol or persisted stage object.

## Find Corruption

- Mangled technical terms, names, numbers, units, or orders of magnitude.
- Broken or truncated sentences and gaps where ASR may have lost reasoning.
- Exact or near-exact repeated phrases produced by the decoder.
- Unrecoverable spans that cannot reliably establish what was said.

Do not flag a design choice merely because it is wrong. Do not turn a genuine
omission into an opportunity to improve the answer. Group duplicate findings
and use nearby repetitions to explain a likely reading, without silently fixing
ambiguous words or numbers.

For each question, give the exact timestamp and quote from that segment, your
tentative reading, and ask what was actually said. Prefer one manageable batch;
follow up on unanswered items without restarting the whole process.

Example:

> [04:12] "we'll use Kafla for the right ahead log"
> Read as: Kafka for the write-ahead log. Did you say that in the recording?
> If not, what did you say?

## Clarify and Prepare Final Text

1. Wait for actual user answers to ambiguous findings. Do not treat your likely
   reading as confirmation. The user may identify an unclear span as unavailable
   instead of recovering it; record that decision and do not score that span.
2. Keep raw text unchanged. Apply only confirmed transcription corrections to
   a separate `SystemDesignInterviewerAgent/transcripts/<id>.final.txt` file,
   retaining timestamps. Do not incorporate improved design reasoning supplied
   after recording. Keep excluded additions in notes, separate from evidence.
3. Retain concise notes of questions, answers, excluded additions, repetition,
   and unavailable spans for the final accepted evaluation. No worker results,
   ballots, hash bindings, or round histories are required.
4. If there are no corrections, designate the raw transcript as final. Otherwise
   show the corrected file and summarize the applied clarifications. Do not
   score until required questions have answers or the user has explicitly marked
   the affected evidence unavailable.
5. Continue with `.github/skills/score-design/SKILL.md` using only the designated
   final transcript as design evidence. Machine repetition is not a communication
   defect; unrecoverable content earns neither credit nor penalty.
