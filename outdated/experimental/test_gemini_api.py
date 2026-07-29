import requests
import json
import time
import os

# --- CONFIGURATION ---
SECRETS_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "secrets.json")
if not os.path.exists(SECRETS_PATH):
    print(f"❌ Error: secrets.json not found at {SECRETS_PATH}")
    exit()

with open(SECRETS_PATH, "r") as f:
    secrets = json.load(f)
    SERVICE_URL = secrets.get("SERVICE_URL")
    PASSWORD = secrets.get("RESEARCH_PASSWORD")

def test_service():
    print(f"🚀 Connecting to: {SERVICE_URL}")
    print(f"🤖 Target Model: Gemini 2.5 Flash (Stable)\n")  # <--- UPDATED LABEL

    # The prompt remains the same (Gemini 2.5 is great at reasoning too)
    prompt = """
    I have a video of a geologist looking at a rock formation.
    The geologist looks at the rock for 5 seconds, looks at the map, 
    then points at the rock and says 'Notice the folding here.'
    
    Analyze the intent: Is this a safety check or a semantic interpretation?
    Explain your reasoning step-by-step.
    """

    headers = {
        "Content-Type": "application/json",
        "Authorization": PASSWORD
    }

    payload = {
        "prompt": prompt
    }

    try:
        start_time = time.time()
        
        # Send Request
        response = requests.post(SERVICE_URL, headers=headers, json=payload)
        
        end_time = time.time()
        duration = end_time - start_time

        # Print Result
        if response.status_code == 200:
            data = response.json()
            print(f"✅ Success! (Time: {duration:.2f}s)")
            
            # This will now print 'gemini-2.5-flash' based on your server update
            print(f"Server Used Model: {data.get('model', 'Unknown')}")
            
            print("\n--- GEMINI RESPONSE ---")
            print(data["response"])
            print("-------------------------")
        else:
            print(f"❌ Error {response.status_code}:")
            print(response.text)

    except Exception as e:
        print(f"❌ Connection Failed: {e}")

if __name__ == "__main__":
    test_service()