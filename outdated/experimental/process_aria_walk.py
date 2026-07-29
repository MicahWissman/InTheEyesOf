import os
import json
import time
import requests
import tkinter as tk
from tkinter import filedialog
from google.cloud import storage
from projectaria_tools.utils.vrs_to_mp4_utils import convert_vrs_to_mp4

# --- CONFIGURATION ---
SECRETS_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "secrets.json")
if not os.path.exists(SECRETS_PATH):

    print(f"❌ Error: secrets.json not found at {SECRETS_PATH}")
    exit()

with open(SECRETS_PATH, "r") as f:
    secrets = json.load(f)
    CLOUD_RUN_URL = secrets.get("SERVICE_URL")
    PASSWORD = secrets.get("RESEARCH_PASSWORD")

BUCKET_NAME = "vt-research-aria-data"  # The bucket you created

# --- STEP 1: CONVERT VRS TO MP4 ---
def convert_local(vrs_path):
    mp4_path = vrs_path.replace(".vrs", ".mp4")
    if os.path.exists(mp4_path):
        print(f"ℹ️ MP4 already exists: {mp4_path}")
        return mp4_path
    
    print("⚙️ Converting VRS to MP4 (This takes time)...")
    try:
        convert_vrs_to_mp4(
            vrs_file=vrs_path,
            output_video=mp4_path,
            log_folder=None,
            down_sample_factor=1
        )
        print("✅ Conversion Successful.")
        return mp4_path
    except Exception as e:
        print(f"❌ Conversion Failed: {e}")
        return None

# --- STEP 2: UPLOAD TO GOOGLE CLOUD STORAGE ---
def upload_to_bucket(local_path):
    file_name = os.path.basename(local_path)
    destination_blob_name = f"uploads/{file_name}"
    
    print(f"☁️ Uploading {file_name} to gs://{BUCKET_NAME}...")
    
    try:
        storage_client = storage.Client()
        bucket = storage_client.bucket(BUCKET_NAME)
        blob = bucket.blob(destination_blob_name)
        
        # This handles large files automatically
        blob.upload_from_filename(local_path)
        
        uri = f"gs://{BUCKET_NAME}/{destination_blob_name}"
        print(f"✅ Upload Complete: {uri}")
        return uri
    except Exception as e:
        print(f"❌ Upload Failed. Did you run 'gcloud auth application-default login'?\nError: {e}")
        return None

# --- STEP 3: VLM ANALYSIS (Gemini 2.5) ---
def analyze_video(gcs_uri):
    print("🧠 Sending to Gemini Research Brain...")
    
    # This prompt replaces YOLO/DINO. It asks for temporal understanding.
    prompt = """
    Analyze this first-person expert video footage.
    I need two specific lists based on visual presence and attention.
    
    LIST 1: GLOBAL SALIENCE (What is on screen?)
    Identify the Top 5 objects/elements that occupy the most screen space over the duration of the video.
    Format: Object Name | Approx Duration Visible
    
    LIST 2: EXPERT ATTENTION (What is being looked at?)
    Assuming the expert's gaze follows the center of the camera frame, identify the Top 5 objects the expert *stops to look at* or tracks intentionally.
    Format: Object Name | Context (Why they looked) | Approx Dwell Time
    
    Provide the output in clean JSON format.
    """

    payload = {
        "prompt": prompt,
        "file_uri": gcs_uri, # Sending the cloud link, not the file!
        "mime_type": "video/mp4"
    }
    
    headers = {
        "Authorization": PASSWORD,
        "Content-Type": "application/json"
    }
    
    start = time.time()
    try:
        response = requests.post(CLOUD_RUN_URL, json=payload, headers=headers, timeout=600)
        print(f"✅ Analysis finished in {time.time() - start:.2f}s")
        
        if response.status_code == 200:
            return response.json().get("response")
        else:
            return f"Error {response.status_code}: {response.text}"
            
    except Exception as e:
        return f"Connection Error: {e}"

# --- MAIN WORKFLOW ---
def main():
    # GUI File Picker
    root = tk.Tk()
    root.withdraw()
    print("📂 Select a Project Aria .vrs file...")
    vrs_path = filedialog.askopenfilename(filetypes=[("VRS Files", "*.vrs")])
    
    if not vrs_path:
        print("No file selected.")
        return

    # 1. Convert
    mp4_path = convert_local(vrs_path)
    if not mp4_path: return

    # 2. Upload
    gcs_uri = upload_to_bucket(mp4_path)
    if not gcs_uri: return

    # 3. Analyze
    result = analyze_video(gcs_uri)
    
    print("\n" + "="*40)
    print("   VLM RESEARCH REPORT   ")
    print("="*40)
    print(result)
    print("="*40)

if __name__ == "__main__":
    main()