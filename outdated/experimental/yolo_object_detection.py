import os
import csv
from PIL import Image
from ultralytics import YOLO
from projectaria_tools.core import data_provider

# === CONFIGURATION ===
vrsfile = "/Users/lborunda/Desktop/ARIA/Recordings from glasses/accessible_path_1.vrs"
output_dir = "/Users/lborunda/Desktop/ARIA/_PYTHON/output_frames"
output_csv = "/Users/lborunda/Desktop/ARIA/_PYTHON/hazard_detections.csv"
yolo_model_path = "yolov8n-seg.pt"  # Or your custom model if preferred
frame_index = 0  # Can be updated to test different frames

# Ensure output directory exists
os.makedirs(output_dir, exist_ok=True)

# Load VRS file
provider = data_provider.create_vrs_data_provider(vrsfile)
stream_id = provider.get_stream_id_from_label("camera-rgb")

# Extract single frame
image_data = provider.get_image_data_by_index(stream_id, frame_index)[0]
frame_rgb = image_data.to_numpy_array()

# Save frame as image
frame_path = os.path.join(output_dir, f"frame_{frame_index:04d}.jpg")
Image.fromarray(frame_rgb).save(frame_path)

# Load YOLO segmentation model
model = YOLO(yolo_model_path)

# Run prediction on the saved image
results = model(frame_path)[0]

# Extract and filter detections
detections = []
for box, cls, conf in zip(results.boxes.xyxy, results.boxes.cls, results.boxes.conf):
    if conf >= 0.7:
        x1, y1, x2, y2 = map(float, box)
        detections.append({
            "frame_index": frame_index,
            "class": results.names[int(cls)],
            "confidence": round(float(conf), 3),
            "bbox": f"{x1:.1f},{y1:.1f},{x2:.1f},{y2:.1f}"
        })

# Save to CSV if detections were made
if detections:
    with open(output_csv, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=detections[0].keys())
        writer.writeheader()
        writer.writerows(detections)
    print(f"✅ Detections saved to: {output_csv}")
else:
    print("⚠️ No high-confidence hazards detected in this frame.")