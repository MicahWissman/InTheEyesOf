# Role
Senior Computer Vision & SLAM Engineer

# Task
Create a standalone Python pipeline to convert Project Aria `.vrs` data into SLAM point clouds and trajectories using **ORB-SLAM3**, bypassing Meta MPS.

# Environment Context
- Path: `~/EyesOf/InTheEyesOf`
- Library: `projectaria_tools` for VRS data extraction
- Algorithm: `ORB-SLAM3` (Stereo-Inertial mode)
- Language: Python 3.10+

# Implementation Requirements
1. **Data Loading:** Use `VrsDataProvider` to access streams 1201-1 (Left), 1201-2 (Right), and 1201-1 (IMU).
2. **Preprocessing:** Convert Aria's Fisheye624 timestamps to Unix/System time for ORB-SLAM3 synchronization.
3. **SLAM Wrapper:**
   - Initialize `ORB_SLAM3.System` in `STEREO_INERTIAL` mode.
   - Pass IMU measurements as a `std::vector` of IMU data packets between image frames.
4. **Coordinate Transformation:** Map the SLAM world coordinates back to the Aria Central Pupil Frame (CPF).
5. **Exports:** - `trajectory.csv` (compatible with MPS format)
   - `slam_map.ply` (Global map points)

# Output Instructions
Please provide the complete `slam_algorithm.py` script and a `README.md` explaining the build steps for the ORB-SLAM3 Python bindings.