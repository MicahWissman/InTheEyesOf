import tkinter as tk
from tkinter import filedialog
import subprocess
import shutil

def convert_vrs_to_mp4_upright():
    # Initialize Tkinter for file dialogs
    root = tk.Tk()
    root.withdraw()  # Hide the Tkinter root window

    # Prompt for the VRS file
    input_vrs_file = filedialog.askopenfilename(
        title="Select the Project Aria VRS File",
        filetypes=[("VRS Files", "*.vrs")]
    )
    if not input_vrs_file:
        print("No VRS file selected. Exiting...")
        return

    # Prompt for the output MP4 file
    output_mp4_file = filedialog.asksaveasfilename(
        title="Save the Converted MP4 File As",
        defaultextension=".mp4",
        filetypes=[("MP4 Files", "*.mp4")]
    )
    if not output_mp4_file:
        print("No output file specified. Exiting...")
        return

    # Convert VRS to MP4 with corrected arguments
    try:
        print(f"Converting VRS to MP4 with upright correction...")
        
        # Check if the CLI tool is available
        if not shutil.which("vrs_to_mp4"):
            raise FileNotFoundError("The 'vrs_to_mp4' command was not found. Please run 'pip install projectaria-tools'.")

        if not shutil.which("ffmpeg"):
            raise FileNotFoundError("The 'ffmpeg' command was not found. Please install ffmpeg (e.g., 'sudo apt install ffmpeg').")

        # Call the CLI tool using subprocess
        cmd = [
            "vrs_to_mp4",
            "--vrs", input_vrs_file,
            "--output_video", output_mp4_file,
            "--downsample", "1"
        ]
        
        subprocess.run(cmd, check=True)
        
        print(f"✅ Conversion successful: {output_mp4_file}")

    except TypeError as e:
        print(f"❌ Argument Error: {e}")
    except Exception as e:
        print(f"❌ Error during conversion: {e}")

# Run the corrected conversion function
convert_vrs_to_mp4_upright()
