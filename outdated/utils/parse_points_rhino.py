import csv
from tkinter import Tk
from tkinter.filedialog import askopenfilename, asksaveasfilename

# Function to request file from user
def get_file_path(prompt):
    Tk().withdraw()  # Hide the root window
    file_path = askopenfilename(title=prompt, filetypes=[("CSV Files", "*.csv")])
    return file_path

def save_file_path(prompt):
    Tk().withdraw()  # Hide the root window
    file_path = asksaveasfilename(title=prompt, defaultextension=".csv", filetypes=[("CSV Files", "*.csv")])
    return file_path

# Ask the user for the input file
input_file = get_file_path("Select the CSV file to process")

if not input_file:
    print("No file selected. Exiting.")
    exit()

# Ask the user where to save the output file
output_file = save_file_path("Save the processed file as")

if not output_file:
    print("No output file selected. Exiting.")
    exit()

# Process the data and write a new CSV
try:
    with open(input_file, 'r') as infile, open(output_file, 'w', newline='') as outfile:
        reader = csv.DictReader(infile)
        writer = csv.writer(outfile)
        
        # Write the header for the output CSV
        writer.writerow(['x', 'y', 'z'])
        
        for row in reader:
            # Extract only the x, y, z coordinates
            x = row['px_world']
            y = row['py_world']
            z = row['pz_world']
            
            # Write to the new CSV
            writer.writerow([x, y, z])
    
    print(f"Processed CSV saved to: {output_file}")

except Exception as e:
    print(f"An error occurred: {e}")