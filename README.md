# Meridian Scribe

**A meeting voice agent that turns audio into action.** Meridian Scribe listens to a meeting or
call recording, transcribes it with **AssemblyAI** (speaker diarization + automatic chapters),
and then thinks about what was said: it extracts an executive summary, **action items with
owners and deadlines**, decisions, and key topics — and renders clean Markdown minutes.

Built for the [AssemblyAI Voice Agent Hackathon](https://lablab.ai/ai-hackathons/assemblyai-voice-agent-hackathon) (lablab.ai, Sep 2026).

## Why

Meetings end and nobody remembers who promised what. Meridian Scribe closes that gap:
drop in a recording, get back accountable minutes — every action item has an owner and a deadline,
every decision is on record, and everything links back to the diarized transcript.

## Architecture

```
 audio file / URL
       │
       ▼
┌─────────────────────────────┐
│ AssemblyAI transcription    │  POST /v2/upload (local files)
│  • speaker diarization      │  POST /v2/transcript {speaker_labels, auto_chapters}
│  • auto chapters            │  poll /v2/transcript/:id → diarized transcript
└─────────────┬───────────────┘
              ▼ diarized text ("Speaker A: …")
┌─────────────────────────────┐
│ LLM extraction              │  OpenRouter free-tier models (fallback chain)
│  • summary                  │  → strict JSON: summary / action_items{task,owner,deadline}
│  • action items             │    / decisions / key_topics
│  • decisions, key topics    │  heuristic regex fallback when no LLM key is set
└─────────────┬───────────────┘
              ▼
      Markdown minutes → stdout + output/minutes_*.md
```

The agent degrades gracefully: no LLM key → deterministic heuristic extraction; no AssemblyAI
key → offline demo mode over a cached fixture transcript so the full pipeline can be evaluated.
With both keys set it is the real thing end-to-end.

## Quickstart

Requirements: Python 3.9+, **zero dependencies** (standard library only).

```bash
git clone https://github.com/ntoledo319/meridian-scribe.git
cd meridian-scribe

export ASSEMBLYAI_API_KEY=...    # free tier: https://www.assemblyai.com/dashboard
export OPENROUTER_API_KEY=...    # optional, free models: https://openrouter.ai/keys

# Transcribe + analyze AssemblyAI's own docs sample audio:
python meridian_scribe.py

# Your own meeting:
python meridian_scribe.py path/to/meeting.mp3     # or any https:// audio URL

# No keys at all? Offline pipeline demo over a cached fixture transcript:
python meridian_scribe.py --demo
```

Minutes are printed and saved to `output/minutes_<timestamp>.md`.

## Sample output

Real output of `python meridian_scribe.py --demo` (fixture transcript → free-tier LLM
`nvidia/nemotron-3-super-120b-a12b:free` via OpenRouter):

```markdown
## Summary
The team held a launch sync for the Meridian release, confirming the WebSocket-first approach
for the realtime API and deciding on usage-based pricing for the beta ... The security review
was identified as a blocker and assigned to Chris (Speaker C).

## Action Items
- [ ] Finish streaming guide docs migration — **Speaker B** (due Friday)
- [ ] Draft pricing page copy — **Speaker B** (due Tuesday)
- [ ] Schedule security review — **Speaker C** (due this week)
- [ ] Prepare demo environment for launch webinar — **Speaker B** (due next week)

## Decisions
- Adopt WebSocket-first approach for the realtime API
- Use usage-based pricing for the beta, revisit seat-based in Q2
- Schedule security review before launch (blocker)
```

## Design notes

- **AssemblyAI-first**: transcription, speaker diarization, and chaptering all come from the
  AssemblyAI API — the voice-understanding layer is entirely theirs.
- **Faithful extraction**: the LLM is instructed to never invent owners or deadlines; fields it
  cannot ground in the transcript come back `null`.
- **Always runs**: every external dependency has a deterministic fallback, so the agent produces
  minutes in any environment.
- **Roadmap**: swap the batch transcription step for AssemblyAI's Streaming STT over WebSocket
  for live meetings, and add a voice interface via the Voice Agent API (same architecture, the
  transcript stream feeds the same extraction engine).

## Honesty / disclosures

- `data/sample_transcript.json` is a **synthetic fixture** we wrote in the AssemblyAI transcript
  JSON shape; it exists so the extraction pipeline can be demoed offline (`--demo`). It is never
  used when `ASSEMBLYAI_API_KEY` is set.
- This project was built with AI assistance (code generation), disclosed per hackathon rules.

## License

MIT — see [LICENSE](LICENSE).
