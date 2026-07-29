1. The Goal: Bridging the Gap
Project Aria records data in a proprietary .vrs container with raw fisheye lenses and custom IMU coordinate frames. Kimera-VIO, developed by MIT, expects a very specific directory structure (mav0/) and, crucially, rectified pinhole images. This script automates the complex math required to make these two systems compatible.

2. Functional Breakdown
A. Graphical Interface & Environment Setup
The script uses tkinter to provide a user-friendly way to select the input .vrs file and the output destination. Once selected, setup_directories builds the EuroC-compliant hierarchy:

mav0/cam0/data (Left SLAM)
mav0/cam1/data (Right SLAM)
mav0/imu0/ (IMU CSV)
B. IMU Data Extraction (Stream 1202-1)
The script accesses the Aria IMU stream to extract linear acceleration and angular velocity.

Handling SDK Nuances: It uses the MotionData structure (specifically accel_m_s2 and gyro_rad_s) to ensure compatibility with the specific version of projectaria_tools installed in your environment.
Formatting: It writes a data.csv file where every row is timestamped in nanoseconds, matching the precision required for tight IMU-Camera fusion in SLAM.
C. The Rectification Engine (Fisheye to Pinhole)
This is the most mathematically intensive part of the script. Aria's SLAM cameras (1201-1 and 1201-2) use ultra-wide fisheye lenses which contain significant distortion.

Calibration Retrieval: It pulls the "Factory Calibration" directly from the VRS file.
Map Generation: The compute_rectification_map function creates a lookup table. It takes a virtual 640x480 pinhole grid, "unprojects" those pixels into 3D rays, and then "projects" them back into the Aria fisheye model.
Vectorization Workaround: Because the SDK's unproject function in your version isn't vectorized (it processes one pixel at a time), the script loops through the grid once to build a map, then uses cv2.remap for lightning-fast processing of the actual video frames.
D. Image Processing & Synchronization
For every frame in the SLAM streams:

It extracts the raw image and the capture_timestamp_ns.
It applies the precomputed rectification map to remove lens distortion.
It saves the result as a .png named after its nanosecond timestamp. This naming convention is how Kimera-VIO synchronizes images with IMU readings.
3. Role in the Overall Pipeline
Looking at your other scripts like gaze_heatmap.py and extract_hotspot_frames.py, this script provides the spatial foundation.

While your other tools analyze what the user is looking at (Gaze/VLM), vrs_to_kimera.py allows you to run Kimera-VIO to determine where the user was in the world with high precision. By converting the VRS to EuroC format, you can generate the trajectory and point clouds that the rest of your "In The Eyes Of" research pipeline relies on for situated visualization