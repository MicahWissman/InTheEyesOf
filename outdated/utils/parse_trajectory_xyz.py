import pandas as pd
import tkinter as tk
from tkinter import filedialog

# Initialize Tkinter and hide the root window
root = tk.Tk()
root.withdraw()

# Ask the user to select the input file
input_file = filedialog.askopenfilename(title="Select Closed Loop Trajectory File", filetypes=[("CSV files", "*.csv")])

# Check if a file was selected
if not input_file:
    print("No file selected. Exiting...")
    exit()

# Load the closed loop trajectory file
closed_loop_path = pd.read_csv(input_file)

# Extract x, y, z coordinates and rename columns
closed_loop_xyz = closed_loop_path[['tx_world_device', 'ty_world_device', 'tz_world_device']]
closed_loop_xyz.columns = ['x', 'y', 'z']

# Ask the user where to save the output file
output_file = filedialog.asksaveasfilename(title="Save Processed File As", defaultextension=".csv", filetypes=[("CSV files", "*.csv")])

# Check if a file path was provided
if not output_file:
    print("No save location provided. Exiting...")
    exit()

# Save the processed file
closed_loop_xyz.to_csv(output_file, index=False)

print(f"Closed loop x, y, z coordinates successfully saved to: {output_file}")
