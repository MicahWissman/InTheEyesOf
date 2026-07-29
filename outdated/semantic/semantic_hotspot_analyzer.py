import os
import json
import re
import requests
import argparse
from datetime import datetime
from vrs_spatial_indexer import load_data, run_indexing

# --- CONFIGURATION ---
DEFAULT_SECRETS = os.path.join(os.path.dirname(__file__), "..", "..", "..", "secrets.json")

def parse_transcript(transcript_path):
    """Parses the [0000s - 0010s]: Text format into a list of chunks."""
    chunks = []
    pattern = re.compile(r"\[(\d+)s - (\d+)s\]: (.*)")
    
    if not os.path.exists(transcript_path):
        print(f"⚠️ Warning: Transcript not found at {transcript_path}")
        return []

    with open(transcript_path, "r") as f:
        for line in f:
            match = pattern.match(line.strip())
            if match:
                start, end, text = match.groups()
                chunks.append({
                    "start": int(start),
                    "end": int(end),
                    "text": text.strip()
                })
    return chunks

def get_context_for_event(event, transcript_chunks):
    """Finds all transcript chunks that overlap with the hotspot event time."""
    # Convert MPS microseconds to seconds
    event_start = event['start_ts'] / 1e6
    event_end = event['end_ts'] / 1e6
    
    relevant_text = []
    for chunk in transcript_chunks:
        # Check for overlap between [event_start, event_end] and [chunk_start, chunk_end]
        if not (chunk['end'] < event_start or chunk['start'] > event_end):
            if chunk['text'] != "(silence)":
                relevant_text.append(chunk['text'])
    
    return " ".join(relevant_text) if relevant_text else "No speech recorded during this event."

def analyze_with_gemini(hotspot_id, duration, speech_context, url, password):
    """Sends the spatial + speech context to the Gemini 2.5 Flash service."""
    print(f"🧠 Analyzing Hotspot {hotspot_id}...")
    
    prompt = f"""
    Analyze this 'Hotspot' event from a Project Aria egocentric recording.
    
    CONTEXT:
    - Hotspot ID: {hotspot_id} (This is a 3D zone the user focused on repeatedly)
    - Dwell Duration: {duration:.2f} seconds
    - User Speech during this focus: "{speech_context}"
    
    TASK:
    1. Identify the 'Intent': Is the user describing an object, asking a question, or performing a technical task?
    2. Semantic Label: Provide a short (2-3 word) label for what this hotspot likely represents.
    3. Reasoning: Explain why based on the speech context.
    
    Return the result in clean Markdown format.
    """

    headers = {
        "Content-Type": "application/json",
        "Authorization": password
    }
    payload = {"prompt": prompt}

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        if response.status_code == 200:
            return response.json().get("response", "No response from AI.")
        else:
            return f"❌ AI Error ({response.status_code}): {response.text}"
    except Exception as e:
        return f"❌ Connection Failed: {e}"

def get_context_for_intervals(intervals, transcript_chunks):
    """Finds transcript chunks that overlap with any of the provided intervals."""
    relevant_text = []
    for start_ts, end_ts in intervals:
        event_start = start_ts / 1e6
        event_end = end_ts / 1e6
        for chunk in transcript_chunks:
            if not (chunk['end'] < event_start or chunk['start'] > event_end):
                if chunk['text'] != "(silence)":
                    relevant_text.append(chunk['text'])
    
    unique_text = list(set(relevant_text))
    return " ".join(unique_text) if unique_text else "No speech recorded."

def main():
    parser = argparse.ArgumentParser(description="Semantic Hotspot Analyzer")
    parser.add_argument("--mps_root", required=True, help="Path to MPS data")
    parser.add_argument("--transcript", required=True, help="Path to transcript .txt")
    parser.add_argument("--rois_json", help="Path to gold-standard ROIs JSON (optional)")
    parser.add_argument("--secrets", default=DEFAULT_SECRETS, help="Path to secrets.json")
    args = parser.parse_args()

    # 1. Load Secrets
    if not os.path.exists(args.secrets):
        print(f"❌ Error: Secrets file not found at {args.secrets}")
        return

    with open(args.secrets, "r") as f:
        secrets = json.load(f)
        url = secrets.get("SERVICE_URL")
        password = secrets.get("RESEARCH_PASSWORD")

    # 2. Load Transcript
    print("📝 Loading transcript...")
    transcript_chunks = parse_transcript(args.transcript)

    # 3. Get Events (either from JSON or by running Indexer)
    if args.rois_json and os.path.exists(args.rois_json):
        print(f"🏆 Using Gold Standard ROIs from {args.rois_json}")
        with open(args.rois_json, "r") as f:
            gold_rois = json.load(f)
        
        # Convert Gold ROIs to a format compatible with our loop
        events_to_analyze = []
        for roi in gold_rois:
            events_to_analyze.append({
                'id': f"Gold_{roi['rank']}",
                'duration': roi['dwell_time'],
                'pos': roi['centroid_world'],
                'speech': get_context_for_intervals(roi['intervals'], transcript_chunks)
            })
    else:
        print("📍 Running standard spatial indexing...")
        data = load_data(args.mps_root)
        raw_events = run_indexing(data)
        
        events_to_analyze = []
        clusters = sorted(list(set([e['cluster_id'] for e in raw_events if e['cluster_id'] != -1])))
        for cid in clusters:
            c_events = [e for e in raw_events if e['cluster_id'] == cid]
            duration = sum([(e['end_ts'] - e['start_ts'])/1e6 for e in c_events])
            all_speech = []
            for e in c_events:
                s = get_context_for_event(e, transcript_chunks)
                if s and s != "No speech recorded during this event.":
                    all_speech.append(s)
            
            events_to_analyze.append({
                'id': f"Cluster_{cid:02d}",
                'duration': duration,
                'pos': "Unknown (Point Cloud)",
                'speech': " | ".join(list(set(all_speech))) if all_speech else "No speech context."
            })

    # 4. Generate Semantic Report
    report_lines = [
        "# Semantic Hotspot Analysis Report",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"MPS Source: {args.mps_root}",
        f"Method: {'Gold Standard (Voxel)' if args.rois_json else 'Standard (DBSCAN)'}",
        "\n---\n"
    ]

    for event in events_to_analyze:
        # Call LLM
        ai_analysis = analyze_with_gemini(event['id'], event['duration'], event['speech'], url, password)
        
        report_lines.append(f"## 📍 Hotspot: {event['id']}")
        report_lines.append(f"**Total Attention Time:** {event['duration']:.2f}s")
        report_lines.append(f"**3D Position:** {event['pos']}")
        report_lines.append(f"**Speech Context:** {event['speech']}")
        report_lines.append("\n### 🤖 AI Interpretation")
        report_lines.append(ai_analysis)
        report_lines.append("\n---\n")

    # Save Report
    output_path = os.path.join(os.getcwd(), "semantic_hotspot_report.md")
    with open(output_path, "w") as f:
        f.write("\n".join(report_lines))
    
    print(f"\n🎉 Success! Semantic report generated: {output_path}")

if __name__ == "__main__":
    main()
