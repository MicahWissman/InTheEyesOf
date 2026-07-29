# Google Cloud Storage Integration

This document outlines the procedures for authenticating, managing, and automating data transfers between local environments and the project's Google Cloud Storage (GCS) buckets.

---

## Authentication

To interact with the cloud buckets via Python scripts or the command line, you must authenticate your local environment.

```bash
gcloud auth application-default login
```

This command generates the Application Default Credentials (ADC) required by the `google-cloud-storage` library and the Google Cloud SDK.

---

## Environment Setup

The Python scripts in this repository require the Google Cloud Storage client library. Ensure it is installed within your active environment.

```bash
conda activate aria_tools
pip install google-cloud-storage
```

---

## Command Line Operations

The `gcloud storage` command is the primary interface for managing cloud assets. It is optimized for performance and replaces the legacy `gsutil` tool.

### 1. Listing Bucket Contents
```bash
gcloud storage ls gs://vt-research-aria-data/
```

### 2. Uploading Files
To upload a local file (e.g., a .vrs recording or processed output) to the bucket:
```bash
gcloud storage cp path/to/local_file.vrs gs://vt-research-aria-data/
```

### 3. Downloading Files
```bash
gcloud storage cp gs://vt-research-aria-data/remote_file.vrs ./local_directory/
```

### 4. Synchronizing Directories
To sync an entire results directory to the cloud:
```bash
gcloud storage rsync -r ./pipeline_results gs://vt-research-aria-data/results/
```

---

## Data Management Strategy

### VRS File Storage
The Google Cloud Storage bucket is the primary repository for raw Project Aria .vrs files. While the ingestion pipeline may convert these to .mp4 for specific AI analysis tasks, the original .vrs files should always be archived in the bucket to preserve the full spatial and sensor metadata.

### Automation
For automated uploads within Python scripts, utilize the `upload_to_bucket(local_path)` pattern. Ensure the function is configured to handle .vrs paths directly to maintain a complete record of the raw data before any lossy conversion occurs.

### Bucket URI
The primary research bucket is: `gs://vt-research-aria-data/`
