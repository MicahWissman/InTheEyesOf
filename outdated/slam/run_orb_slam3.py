import argparse
import numpy as np
import os
import sys
from datetime import datetime, timedelta
from scipy.spatial.transform import Rotation

try:
    # Actual imports
    from projectaria_tools.core import vrs, data_provider
    from projectaria_tools.core.sensor_data import SensorData
    from projectaria_tools.core.stream_id import StreamId
    from orbslam3_python import System as ORBSLAM3System, IMU as ORBSLAM3IMU
    print("Successfully imported projectaria_tools and orbslam3_python.")
except ImportError as e:
    print(f"Error: Required libraries not found: {e}")
    print("Please ensure 'projectaria_tools' and 'orbslam3_python' are installed and accessible.")
    sys.exit(1)

class SLAMPipeline:
    System = ORBSLAM3System
    IMU = ORBSLAM3IMU

    def __init__(self, vrs_path, vocab_path, settings_path):
        self.vrs_path = vrs_path
        self.vocab_path = vocab_path
        self.settings_path = settings_path
        self.vrs_data_provider = data_provider.create_vrs_data_provider(vrs_path)
        self.orb_slam = None
        self.aria_to_cpf_transform = None # Placeholder for Aria CPF transformation

        # Stream IDs as requested
        self.left_cam_stream_id = StreamId("1201-1")
        self.right_cam_stream_id = StreamId("1201-2")
        self.imu_stream_id = StreamId("1202-1")

        # Initialize reference for timestamp conversion
        self._aria_start_time_ns = None
        self._unix_start_time_sec = None

    def _initialize_timestamp_reference(self):
        # Get the first frame from the left camera to establish an Aria timestamp reference
        left_data = self.vrs_data_provider.get_image_data_by_index(self.left_cam_stream_id, 0)
        if left_data is None:
            raise RuntimeError("No data found in VRS file for left camera stream (1201-1).")
        
        self._aria_start_time_ns = left_data[1].capture_timestamp_ns
        # Use the system's current time as the Unix reference point.
        # In a real-world deployed system, one might try to synchronize this with recording metadata
        # or a more precise time source. For now, this provides a working conversion.
        self._unix_start_time_sec = datetime.now().timestamp()
        
        print(f"Timestamp reference: Aria start {self._aria_start_time_ns} ns, Unix start {self._unix_start_time_sec} s")

    def _convert_timestamp_aria_to_unix(self, aria_timestamp_ns):
        if self._aria_start_time_ns is None or self._unix_start_time_sec is None:
            self._initialize_timestamp_reference()
        
        offset_ns = aria_timestamp_ns - self._aria_start_time_ns
        unix_time_sec = self._unix_start_time_sec + (offset_ns / 1_000_000_000.0)
        return unix_time_sec

    def _get_imu_data_for_time_range(self, imu_stream_id, start_unix_sec, end_unix_sec):
        imu_samples = []
        
        # Iterate through all IMU data, convert to Unix time, and filter
        num_imu_data = self.vrs_data_provider.get_num_data(imu_stream_id)
        for i in range(num_imu_data):
            sensor_data = self.vrs_data_provider.get_sensor_data_by_index(imu_stream_id, i)
            if sensor_data is None:
                continue
            
            imu_data = sensor_data.imu_data()
            imu_aria_timestamp_ns = sensor_data.get_time_ns(data_provider.TimeDomain.DEVICE_TIME)
            imu_unix_timestamp_sec = self._convert_timestamp_aria_to_unix(imu_aria_timestamp_ns)
            
            if imu_unix_timestamp_sec < start_unix_sec:
                continue
            if imu_unix_timestamp_sec > end_unix_sec:
                break # Assuming IMU data is time-ordered

            # Assuming imu_datum.accel and imu_datum.gyro are objects with x, y, z attributes
            # or directly accessible as a list/tuple. Checking projectaria_tools docs for exact structure.
            # Assuming they are SensorData objects from projectaria_tools.core.sensor_data
            accel = imu_data.accel_msec2
            gyro = imu_data.gyro_radsec

            imu_samples.append(SLAMPipeline.IMU(
                imu_unix_timestamp_sec,
                accel[0], accel[1], accel[2],
                gyro[0], gyro[1], gyro[2]
            ))
        return imu_samples

    def run_slam(self):
        print("Initializing ORB-SLAM3 System...")
        self.orb_slam = self.System(self.vocab_path, self.settings_path, self.System.STEREO_INERTIAL, False)

        num_left_frames = self.vrs_data_provider.get_num_data(self.left_cam_stream_id)
        num_right_frames = self.vrs_data_provider.get_num_data(self.right_cam_stream_id)
        
        num_frames_to_process = min(num_left_frames, num_right_frames)
        if num_frames_to_process == 0:
            print("No image frames found to process. Exiting SLAM.")
            return

        print(f"Processing {num_frames_to_process} stereo frames.")

        prev_frame_unix_sec = None

        for i in range(num_frames_to_process):
            left_data = self.vrs_data_provider.get_image_data_by_index(self.left_cam_stream_id, i)
            right_data = self.vrs_data_provider.get_image_data_by_index(self.right_cam_stream_id, i)

            if left_data is None or right_data is None:
                print(f"Skipping frame {i} due to missing data.")
                continue

            current_aria_timestamp_ns = left_data[1].capture_timestamp_ns
            current_unix_timestamp_sec = self._convert_timestamp_aria_to_unix(current_aria_timestamp_ns)
            
            imu_data_packets = []
            if prev_frame_unix_sec is not None:
                imu_data_packets = self._get_imu_data_for_time_range(
                    self.imu_stream_id, prev_frame_unix_sec, current_unix_timestamp_sec
                )
            # For the very first frame, we might collect IMU data up to its timestamp.
            elif i == 0:
                 imu_data_packets = self._get_imu_data_for_time_range(
                    self.imu_stream_id, self._unix_start_time_sec, current_unix_timestamp_sec
                )

            # Extract image data as numpy arrays
            im_left = left_data[0].to_numpy_array()
            im_right = right_data[0].to_numpy_array()
            
            self.orb_slam.trackStereo(
                im_left,
                im_right,
                current_unix_timestamp_sec,
                imu_data_packets
            )

            prev_frame_unix_sec = current_unix_timestamp_sec

        self.orb_slam.shutdown()
        print("ORB-SLAM3 System shutdown.")

    def _load_aria_to_cpf_transform(self):
        print("Loading Aria to CPF transform using projectaria_tools.")
        device_calib = self.vrs_data_provider.get_device_calibration()

        # Get T_device_cpf transform
        T_device_cpf = device_calib.get_transform_device_cpf().to_matrix()

        # Get T_device_camera transform (extrinsics) for the left camera
        cam_calib = device_calib.get_camera_calib("camera-slam-left")
        T_device_camera = cam_calib.get_transform_device_camera().to_matrix()

        # Compute T_camera_cpf = T_device_camera.inverse() * T_device_cpf
        # (T_camera_device * T_device_cpf)
        # ORB-SLAM3 provides T_world_camera, we want T_world_cpf
        # T_world_cpf = T_world_camera * T_camera_cpf
        # So we need T_camera_cpf
        T_camera_cpf = np.linalg.inv(T_device_camera) @ T_device_cpf
        self.aria_to_cpf_transform = T_camera_cpf
        print("Aria to CPF transform loaded.")

    def transform_trajectory_to_aria_cpf(self):
        if self.orb_slam is None or not hasattr(self.orb_slam, 'trajectory') or not self.orb_slam.trajectory:
            print("No SLAM trajectory to transform.")
            return []

        if self.aria_to_cpf_transform is None:
            self._load_aria_to_cpf_transform()

        transformed_trajectory = []
        for timestamp, slam_pose_matrix_raw in self.orb_slam.trajectory:
            # Assuming slam_pose_matrix_raw is already a 4x4 numpy array (T_world_camera)
            # If not, it needs to be converted from whatever format orbslam3_python returns
            
            # T_world_cpf = T_world_camera * T_camera_cpf
            transformed_pose_matrix = slam_pose_matrix_raw @ self.aria_to_cpf_transform
            
            transformed_trajectory.append((timestamp, transformed_pose_matrix))
        return transformed_trajectory

    def export_results(self, output_dir):
        os.makedirs(output_dir, exist_ok=True)
        
        # Export trajectory.csv
        trajectory_file = os.path.join(output_dir, "trajectory.csv")
        transformed_trajectory = self.transform_trajectory_to_aria_cpf() # Get transformed poses
        
        if transformed_trajectory:
            with open(trajectory_file, "w") as f:
                f.write("#timestamp,x,y,z,qx,qy,qz,qw") # MPS compatible header
                for timestamp, pose_matrix in transformed_trajectory:
                    # Extract translation (x,y,z)
                    x, y, z = pose_matrix[0, 3], pose_matrix[1, 3], pose_matrix[2, 3]
                    
                    # Extract rotation matrix (R) from the 4x4 pose matrix
                    rotation_matrix = pose_matrix[0:3, 0:3]
                    
                    # Convert rotation matrix to quaternion
                    rotation = Rotation.from_matrix(rotation_matrix)
                    quaternion = rotation.as_quat() # Returns [x, y, z, w]
                    qx, qy, qz, qw = quaternion[0], quaternion[1], quaternion[2], quaternion[3]
                    
                    f.write(f"{timestamp:.6f},{x:.6f},{y:.6f},{z:.6f},{qx:.6f},{qy:.6f},{qz:.6f},{qw:.6f}\n")
            print(f"Trajectory (transformed to Aria CPF - placeholder) saved to {trajectory_file}")
        else:
            print("No trajectory data to export.")

        # Export slam_map.ply
        slam_map_file = os.path.join(output_dir, "slam_map.ply")
        if self.orb_slam and self.orb_slam.map_points:
            with open(slam_map_file, "w") as f:
                f.write("ply\n")
                f.write("format ascii 1.0\n")
                f.write(f"element vertex {len(self.orb_slam.map_points)}\n")
                f.write("property float x\n")
                f.write("property float y\n")
                f.write("property float z\n")
                f.write("end_header\n")
                for point in self.orb_slam.map_points:
                    f.write(f"{point[0]:.6f} {point[1]:.6f} {point[2]:.6f}\n")
            print(f"SLAM map saved to {slam_map_file}")
        else:
            print("No map points to export.")


def main():
    parser = argparse.ArgumentParser(description="Run ORB-SLAM3 on Project Aria VRS data.")
    parser.add_argument("--vrs_path", type=str, required=True, help="Path to the VRS file.")
    parser.add_argument("--vocab_path", type=str, required=True, help="Path to ORB-SLAM3 vocabulary file (e.g., ORBvoc.txt).")
    parser.add_argument("--settings_path", type=str, required=True, help="Path to ORB-SLAM3 settings file (e.g., config.yaml).")
    parser.add_argument("--output_dir", type=str, default="slam_output", help="Directory to save SLAM results.")
    args = parser.parse_args()

    pipeline = SLAMPipeline(args.vrs_path, args.vocab_path, args.settings_path)
    pipeline.run_slam()
    pipeline.export_results(args.output_dir)
    print("SLAM pipeline finished.")

if __name__ == "__main__":
    main()
