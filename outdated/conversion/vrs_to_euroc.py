import os
import csv
import cv2
import numpy as np
import tkinter as tk
from tkinter import filedialog
from tqdm import tqdm
from projectaria_tools.core import data_provider, calibration
from projectaria_tools.core.stream_id import StreamId
from projectaria_tools.core.sensor_data import TimeDomain

def setup_directories(base_path):
    """Creates the EuroC/Kimera folder structure."""
    dirs = [
        os.path.join(base_path, "mav0/cam0/data"),
        os.path.join(base_path, "mav0/cam1/data"),
        os.path.join(base_path, "mav0/imu0"),
    ]
    for d in dirs:
        os.makedirs(d, exist_ok=True)
    return dirs

def compute_rectification_map(src_calib, dst_calib):
    """Generates a rectification map to convert Fisheye to Pinhole."""
    w, h = dst_calib.get_image_size()
    map_x = np.zeros((h, w), dtype=np.float32)
    map_y = np.zeros((h, w), dtype=np.float32)

    # In this SDK version, project/unproject are not vectorized for arrays.
    # We loop once to build the map, which is then used efficiently by cv2.remap.
    for y in range(h):
        for x in range(w):
            # Unproject from pinhole to 3D ray. 
            ray = dst_calib.unproject(np.array([x, y], dtype=np.float64))
            if ray is not None:
                # Project from 3D ray to fisheye pixel
                pixel_src = src_calib.project(ray)
                if pixel_src is not None:
                    map_x[y, x] = pixel_src[0]
                    map_y[y, x] = pixel_src[1]

    return map_x, map_y

def process_vrs_to_kimera(vrs_path, output_path):
    print(f"🚀 Opening VRS file: {vrs_path}")
    provider = data_provider.create_vrs_data_provider(vrs_path)
    if not provider:
        print("❌ Failed to open VRS file.")
        return

    setup_directories(output_path)
    device_calib = provider.get_device_calibration()

    # --- 1. Extract IMU Data (Stream 1202-1) ---
    imu_stream_id = StreamId("1202-1")
    imu_csv_path = os.path.join(output_path, "mav0/imu0/data.csv")
    
    print("🧠 Extracting IMU data...")
    num_imu_samples = provider.get_num_data(imu_stream_id)
    with open(imu_csv_path, 'w', newline='') as f:
        writer = csv.writer(f)
        # EuroC Header
        writer.writerow(["#timestamp [ns]", "w_x [rad s^-1]", "w_y [rad s^-1]", "w_z [rad s^-1]", 
                         "a_x [m s^-2]", "a_y [m s^-2]", "a_z [m s^-2]"])
        
        for i in tqdm(range(num_imu_samples), desc="IMU"):
            sensor_data = provider.get_sensor_data_by_index(imu_stream_id, i)
            imu_data = sensor_data.imu_data()
            ts_ns = sensor_data.get_time_ns(TimeDomain.DEVICE_TIME)
            accel = imu_data.accel_msec2
            gyro = imu_data.gyro_radsec
            writer.writerow([ts_ns, gyro[0], gyro[1], gyro[2], accel[0], accel[1], accel[2]])

    # --- 2. Extract and Rectify Images (1201-1 and 1201-2) ---
    # Stream IDs and their corresponding EuroC camera indices
    cam_streams = {
        "1201-1": {"label": "camera-slam-left", "folder": "mav0/cam0/data"},
        "1201-2": {"label": "camera-slam-right", "folder": "mav0/cam1/data"}
    }

    # Target Pinhole Calibration (Standard 640x480)
    # Focal length of ~300 is a good balance for Aria's wide FOV in a 640px width
    focal_length = 300.0 
    dst_calib = calibration.get_linear_camera_calibration(640, 480, focal_length, "pinhole")

    for stream_str, info in cam_streams.items():
        stream_id = StreamId(stream_str)
        label = info["label"]
        save_dir = os.path.join(output_path, info["folder"])
        
        print(f"📸 Processing {label} ({stream_str})...")
        
        src_calib = device_calib.get_camera_calib(label)
        map_x, map_y = compute_rectification_map(src_calib, dst_calib)
        
        num_frames = provider.get_num_data(stream_id)
        for i in tqdm(range(num_frames), desc=label):
            image_data = provider.get_image_data_by_index(stream_id, i)
            # image_data[0] is the image, image_data[1] is the metadata
            raw_img = image_data[0].to_numpy_array()
            ts_ns = image_data[1].capture_timestamp_ns
            
            # Rectify using the precomputed map
            rectified_img = cv2.remap(raw_img, map_x, map_y, cv2.INTER_LINEAR)
            
            # Save as timestamp.png (standard for EuroC)
            img_name = f"{ts_ns}.png"
            cv2.imwrite(os.path.join(save_dir, img_name), rectified_img)

    print(f"\n✅ Conversion Complete! Data saved to: {output_path}")

if __name__ == "__main__":
    root = tk.Tk()
    root.withdraw()  # Hide the main tkinter window

    print("📂 Select the Project Aria .vrs file...")
    vrs_path = filedialog.askopenfilename(
        title="Select VRS File",
        filetypes=[("VRS Files", "*.vrs"), ("All Files", "*.*")]
    )

    if not vrs_path:
        print("No file selected. Exiting.")
    else:
        print("📂 Select the output directory for Kimera data...")
        output_path = filedialog.askdirectory(title="Select Output Directory")
        
        if not output_path:
            output_path = "./kimera_data"
            print(f"No output directory selected. Using default: {output_path}")

        process_vrs_to_kimera(os.path.abspath(vrs_path), os.path.abspath(output_path))
    
"""
### Key Implementation Details:
1.  **Rectification Strategy**: Since Kimera-VIO expects a pinhole model, I've implemented a custom rectification map generator. It unprojects pixels from a target 640x480 pinhole grid into 3D rays and then projects those rays back into the Aria fisheye model using the factory calibration. This ensures the output images are perfectly linear.
2.  **IMU Formatting**: The IMU data is extracted from stream `1202-1` and saved with nanosecond timestamps. The column order strictly follows the EuroC standard (`timestamp, w, a`).
3.  **Stream IDs**: The script explicitly targets `1201-1` (Left SLAM) and `1201-2` (Right SLAM) as requested.
4.  **Performance**: I've used `cv2.remap` with precomputed maps for the image processing, which is significantly faster than re-calculating the distortion for every frame.
"""