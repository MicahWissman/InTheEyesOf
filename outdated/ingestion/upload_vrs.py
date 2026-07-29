import os
import json
import argparse
from google.cloud import storage

"""
may need to run gcloud auth application-default login
"""

# Path to secrets relative to this script's location
SECRETS_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "secrets.json")

def upload_vrs(local_vrs_path, bucket_name=None):
    """Uploads a local .vrs file to the specified GCS bucket."""
    if not os.path.isfile(local_vrs_path):
        print(f"❌ Error: File '{local_vrs_path}' not found or is not a file.")
        return

    # Load bucket name if not provided via argument
    if not bucket_name:
        if os.path.exists(SECRETS_PATH):
            try:
                with open(SECRETS_PATH, "r") as f:
                    secrets = json.load(f)
                    bucket_name = secrets.get("BUCKET_NAME")
            except Exception as e:
                print(f"⚠️ Warning: Could not read secrets.json: {e}")
        
        # Fallback to the known project bucket
        if not bucket_name:
            bucket_name = "vt-research-aria-data"

    file_name = os.path.basename(local_vrs_path)
    # Store in a dedicated folder in the bucket
    destination_blob_name = f"vrs_uploads/{file_name}"

    print(f"☁️ Uploading {file_name} to gs://{bucket_name}/{destination_blob_name}...")

    try:
        # Initialize the GCS client
        # Note: Requires 'gcloud auth application-default login'
        storage_client = storage.Client()
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(destination_blob_name)
        
        # This method handles large files efficiently
        blob.upload_from_filename(local_vrs_path)
        
        print(f"✅ Upload Complete: gs://{bucket_name}/{destination_blob_name}")
    except Exception as e:
        print(f"❌ Upload Failed.")
        print(f"\nTroubleshooting:")
        print(f"1. Run: gcloud auth application-default login")
        print(f"2. Ensure 'google-cloud-storage' is installed in your environment.")
        print(f"Error Details: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Upload a .vrs file to Google Cloud Storage.")
    parser.add_argument("file_path", help="Path to the local .vrs file")
    parser.add_argument("--bucket", help="Target GCS bucket name (optional, overrides secrets.json)")
    
    args = parser.parse_args()
    upload_vrs(args.file_path, args.bucket)
