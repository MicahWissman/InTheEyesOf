import os
import pandas as pd
import sys

def write_yaml(path, content):
    """Writes a YAML file with the mandatory Kimera header."""
    with open(path, "w") as f:
        f.write("%YAML:1.0\n")
        f.write(content)

def finalize_kimera(base_path):
    """
    Finalizes the EuroC directory structure for Kimera-VIO.
    Generates data.csv for cameras, sensor.yaml for all sensors, 
    and performs a timestamp overlap check.
    """
    mav0_path = os.path.join(base_path, "mav0")
    if not os.path.exists(mav0_path):
        print(f"❌ Error: {mav0_path} does not exist.")
        return

    # 1. Generate Camera CSVs (data.csv)
    cam_timestamps = []
    for cam in ["cam0", "cam1"]:
        cam_path = os.path.join(mav0_path, cam)
        data_dir = os.path.join(cam_path, "data")
        csv_path = os.path.join(cam_path, "data.csv")
        
        if not os.path.exists(data_dir):
            print(f"⚠️ Warning: {data_dir} not found. Skipping {cam}.")
            continue
            
        print(f"📝 Indexing images in {cam}...")
        files = sorted([f for f in os.listdir(data_dir) if f.endswith(".png")])
        with open(csv_path, "w") as f:
            f.write("#timestamp [ns],filename\n")
            for filename in files:
                timestamp = filename.split(".")[0]
                f.write(f"{timestamp},{filename}\n")
                if cam == "cam0":
                    cam_timestamps.append(int(timestamp))
        print(f"   ✅ Created {csv_path}")

    # 2. Check IMU/Camera Overlap
    imu_csv = os.path.join(mav0_path, "imu0", "data.csv")
    if os.path.exists(imu_csv) and cam_timestamps:
        print("\n🔍 Checking IMU/Camera timestamp overlap...")
        # Load IMU data, skipping the header row
        imu_df = pd.read_csv(imu_csv, comment='#')
        imu_min = imu_df.iloc[:, 0].min()
        imu_max = imu_df.iloc[:, 0].max()
        cam_min = min(cam_timestamps)
        cam_max = max(cam_timestamps)
        
        print(f"   IMU Range: {imu_min} to {imu_max}")
        print(f"   Cam Range: {cam_min} to {cam_max}")
        
        if imu_min > cam_min or imu_max < cam_max:
            print("   ❌ ERROR: IMU data does not fully cover camera data range!")
            print("      Kimera-VIO will crash. Ensure IMU starts before and ends after cameras.")
        else:
            print("   ✅ SUCCESS: IMU data covers camera range.")

    # 3. Generate sensor.yaml files
    print("\n⚙️ Generating sensor.yaml templates...")

    # IMU YAML (Aria BMI270 Specs)
    imu_yaml_content = """sensor_type: imu
comment: Aria BMI270
T_BS:
  cols: 4
  rows: 4
  data: [1.0, 0.0, 0.0, 0.0,
         0.0, 1.0, 0.0, 0.0,
         0.0, 0.0, 1.0, 0.0,
         0.0, 0.0, 0.0, 1.0]
rate_hz: 1000
gyroscope_noise_density: 1.22e-04
gyroscope_random_walk: 1.9393e-05
accelerometer_noise_density: 1.57e-03
accelerometer_random_walk: 3.00e-03
"""
    write_yaml(os.path.join(mav0_path, "imu0", "sensor.yaml"), imu_yaml_content)
    print("   ✅ Created imu0/sensor.yaml")

    # Camera YAMLs (Pinhole Placeholders)
    for i, cam in enumerate(["cam0", "cam1"]):
        cam_yaml_content = f"""sensor_type: camera
comment: Aria SLAM {cam} (Pinhole Rectified)
T_BS:
  cols: 4
  rows: 4
  data: [1.0, 0.0, 0.0, {0.0 if i==0 else -0.1},
         0.0, 1.0, 0.0, 0.0,
         0.0, 0.0, 1.0, 0.0,
         0.0, 0.0, 0.0, 1.0]
rate_hz: 30
resolution: [640, 480]
camera_model: pinhole
intrinsics: [300.0, 300.0, 320.0, 240.0]
distortion_model: radial-tangential
distortion_coefficients: [0.0, 0.0, 0.0, 0.0]
"""
        write_yaml(os.path.join(mav0_path, cam, "sensor.yaml"), cam_yaml_content)
        print(f"   ✅ Created {cam}/sensor.yaml")

    print(f"\n🚀 Finalization complete for: {base_path}")

if __name__ == "__main__":
    # Default to the path provided in the request if no argument is given
    target_path = sys.argv[1] if len(sys.argv) > 1 else "/home/micah/EyesOf/imu_data"
    finalize_kimera(target_path)