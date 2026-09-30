#!/usr/bin/env python3
"""
Meridian Scribe — a meeting voice agent built on AssemblyAI.

One command turns a meeting recording into structured minutes:
  1. Transcribe audio with AssemblyAI (speaker diarization + auto chapters).
  2. Extract summary, action items (task/owner/deadline), and decisions with an LLM.
  3. Render clean Markdown minutes.

Stdlib only. Usage:
  export ASSEMBLYAI_API_KEY=...      # from https://www.assemblyai.com/dashboard
  export OPENROUTER_API_KEY=...      # optional; free models are used
  python meridian_scribe.py                          # AssemblyAI's docs sample audio
  python meridian_scribe.py meeting.mp3              # local file or any URL
  python meridian_scribe.py --demo                   # offline pipeline demo (cached transcript)
"""
import json, os, re, sys, time, urllib.request, urllib.error, datetime

AAI_BASE = "https://api.assemblyai.com/v2"
DEFAULT_AUDIO = "https://assembly.ai/sports_injuries.mp3"  # AssemblyAI's own docs sample
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "sample_transcript.json")

OPENROUTER_MODELS = [  # free-tier models, tried in order
    "nvidia/nemotron-3-super-120b-a12b:free",
    "z-ai/glm-5.2:free",
    "google/gemma-4-31b-it:free",
]

EXTRACT_PROMPT = """You are the analysis engine of a meeting voice agent. Given a diarized meeting
transcript, produce JSON with exactly these keys:
  "summary": 3-5 sentence executive summary,
  "action_items": list of {"task": str, "owner": str or null, "deadline": str or null},
  "decisions": list of strings,
  "key_topics": list of short topic strings.
Be faithful to the transcript; never invent owners or dates. Reply with JSON only.

TRANSCRIPT:
%s"""


def http_json(req, timeout=60):
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def transcribe_assemblyai(audio, api_key):
    """Upload (if local) and transcribe with speaker labels + chapters. Returns AAI transcript dict."""
    headers = {"authorization": api_key, "content-type": "application/json"}
    if re.match(r"^https?://", audio):
        audio_url = audio
    else:
        print(f"[1/3] Uploading {audio} to AssemblyAI...")
        with open(audio, "rb") as f:
            data = f.read()
        req = urllib.request.Request(AAI_BASE + "/upload", data=data,
                                     headers={"authorization": api_key, "content-type": "application/octet-stream"})
        audio_url = http_json(req, timeout=300)["upload_url"]
    print("[2/3] Transcribing with AssemblyAI (speaker diarization + auto chapters)...")
    body = {"audio_url": audio_url, "speaker_labels": True, "auto_chapters": True}
    req = urllib.request.Request(AAI_BASE + "/transcript", data=json.dumps(body).encode(), headers=headers)
    tid = http_json(req)["id"]
    while True:
        req = urllib.request.Request(f"{AAI_BASE}/transcript/{tid}", headers=headers)
        t = http_json(req)
        if t["status"] == "completed":
            return t
        if t["status"] == "error":
            raise RuntimeError("AssemblyAI error: " + t.get("error", "unknown"))
        time.sleep(3)


def diarized_text(t):
    if t.get("utterances"):
        return "\n".join(f"Speaker {u['speaker']}: {u['text']}" for u in t["utterances"])
    return t.get("text", "")


def llm_extract(transcript_text):
    """Action items + summary via OpenRouter free models. None if no key / all fail."""
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        print("[3/3] OPENROUTER_API_KEY not set -> heuristic extraction")
        return None
    payload = {"messages": [{"role": "user", "content": EXTRACT_PROMPT % transcript_text[:15000]}],
               "temperature": 0.2}
    for model in OPENROUTER_MODELS:
        try:
            payload["model"] = model
            req = urllib.request.Request(
                "https://openrouter.ai/api/v1/chat/completions",
                data=json.dumps(payload).encode(),
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
            r = http_json(req, timeout=90)
            raw = r["choices"][0]["message"]["content"]
            m = re.search(r"\{.*\}", raw, re.S)
            out = json.loads(m.group(0))
            out["_model"] = model
            print(f"[3/3] LLM extraction done ({model})")
            return out
        except Exception as e:
            print(f"      {model} failed ({type(e).__name__}); trying next free model")
    print("[3/3] all LLM models failed -> heuristic extraction")
    return None


def heuristic_extract(transcript_text):
    """Deterministic fallback: always produces structured minutes without any LLM."""
    items, decisions, topics = [], [], []
    for sent in re.split(r"(?<=[.!?])\s+", transcript_text):
        s = sent.strip()
        sl = s.lower()
        speaker = s.split(":", 1)[0].replace("Speaker ", "").strip() if s.startswith("Speaker") else None
        if re.search(r"\b(i'll|i will|we should|we need to|let's|action item|follow up|send|schedule|draft|prepare)\b", sl):
            dl = re.search(r"\b(by|before|on)\s((?:mon|tue|wed|thu|fri|sat|sun)\w*|next week|friday|eod|tomorrow|\w+ \d{1,2})\b", sl)
            items.append({"task": s[:200], "owner": speaker, "deadline": dl.group(2) if dl else None})
        if re.search(r"\b(agreed|decided|we'll go with|final|approved)\b", sl):
            decisions.append(s[:200])
    words = re.findall(r"\b[A-Za-z][a-z]{5,}\b", transcript_text.lower())
    stop = {"should", "would", "could", "about", "there", "which", "their", "really", "think"}
    freq = {}
    for w in words:
        if w not in stop:
            freq[w] = freq.get(w, 0) + 1
    topics = [w for w, _ in sorted(freq.items(), key=lambda kv: -kv[1])[:5]]
    return {"summary": transcript_text[:600].split(".")[0] + ". (heuristic summary — set OPENROUTER_API_KEY for LLM summaries)",
            "action_items": items[:10], "decisions": decisions[:8], "key_topics": topics, "_model": "heuristic-fallback"}


def render_markdown(audio, t, analysis):
    chapters = "\n".join(f"- **{c['headline']}** ({c['start']//1000}s – {c['end']//1000}s)"
                         for c in (t.get("chapters") or [])) or "- (none)"
    items = "\n".join(f"- [ ] {i['task']}" +
                      (f" — **{i['owner']}**" if i.get("owner") else "") +
                      (f" (due {i['deadline']})" if i.get("deadline") else "")
                      for i in analysis["action_items"]) or "- (none detected)"
    decisions = "\n".join(f"- {d}" for d in analysis["decisions"]) or "- (none detected)"
    topics = ", ".join(analysis["key_topics"]) or "(none)"
    return f"""# Meridian Scribe — Meeting Minutes

**Source audio:** `{audio}`
**Generated:** {datetime.datetime.now().isoformat(timespec="seconds")}
**Analysis engine:** {analysis.get("_model", "?")}

## Summary
{analysis["summary"]}

## Action Items
{items}

## Decisions
{decisions}

## Key Topics
{topics}

## Chapters
{chapters}

## Transcript
{diarized_text(t)}
"""


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    demo = "--demo" in sys.argv
    audio = args[0] if args else DEFAULT_AUDIO
    aai_key = os.environ.get("ASSEMBLYAI_API_KEY")
    if demo or not aai_key:
        if not aai_key and not demo:
            print("ASSEMBLYAI_API_KEY not set -> running offline demo on cached transcript")
            print("(set the key to transcribe real audio with AssemblyAI)")
        t = json.load(open(CACHE))
        audio = audio if args else "data/sample_transcript.json (cached demo)"
    else:
        t = transcribe_assemblyai(audio, aai_key)
    text = diarized_text(t)
    if not text.strip():
        print("empty transcript; nothing to analyze"); sys.exit(1)
    analysis = llm_extract(text) or heuristic_extract(text)
    md = render_markdown(audio, t, analysis)
    os.makedirs("output", exist_ok=True)
    path = os.path.join("output", "minutes_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S") + ".md")
    open(path, "w").write(md)
    print("\n" + md)
    print(f"Minutes saved to {path}")


if __name__ == "__main__":
    main()
