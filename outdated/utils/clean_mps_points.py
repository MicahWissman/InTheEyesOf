import csv
import math
import numpy as np
from tkinter import Tk
from tkinter.filedialog import askopenfilename, asksaveasfilename
from tqdm import tqdm

def get_file_path(prompt):
    Tk().withdraw()
    file_path = askopenfilename(title=prompt, filetypes=[("CSV Files", "*.csv")])
    return file_path

def save_file_path(prompt):
    Tk().withdraw()
    file_path = asksaveasfilename(title=prompt, defaultextension=".csv", filetypes=[("CSV Files", "*.csv")])
    return file_path

def statistical_outlier_removal(points, k=20, std_multiplier=1.0):
    """
    Filters points based on the average distance to their k-nearest neighbors.
    Points with an average distance greater than (mean + std_multiplier * std) 
    are removed.
    """
    from scipy.spatial import KDTree
    
    print(f"🔍 Building KDTree for {len(points)} points...")
    tree = KDTree(points)
    
    print(f"📊 Calculating distances to {k} nearest neighbors...")
    # Query k+1 because the point itself is included in the search
    distances, _ = tree.query(points, k=k+1)
    
    # Exclude the first distance (distance to self, which is 0)
    avg_distances = np.mean(distances[:, 1:], axis=1)
    
    mean_dist = np.mean(avg_distances)
    std_dist = np.std(avg_distances)
    
    threshold = mean_dist + std_multiplier * std_dist
    
    print(f"📈 Global Mean Distance: {mean_dist:.4f}")
    print(f"📈 Global Std Deviation: {std_dist:.4f}")
    print(f"🎯 Distance Threshold: {threshold:.4f}")
    
    mask = avg_distances < threshold
    return mask

def clean_mps_points():
    input_file = get_file_path("Select the MPS Global Points CSV file")
    if not input_file:
        print("No file selected. Exiting.")
        return

    output_file = save_file_path("Save the cleaned CSV as")
    if not output_file:
        print("No output file selected. Exiting.")
        return

    points = []
    header = []
    full_data = []

    print("📖 Reading data...")
    try:
        with open(input_file, 'r') as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            for row in reader:
                full_data.append(row)
                points.append([float(row['px_world']), float(row['py_world']), float(row['pz_world'])])
    except Exception as e:
        print(f"❌ Error reading CSV: {e}")
        return

    points_np = np.array(points)
    
    try:
        mask = statistical_outlier_removal(points_np, k=30, std_multiplier=1.2)
    except ImportError:
        print("❌ Scipy not found. Please install it using: pip install scipy numpy")
        return

    cleaned_data = [full_data[i] for i in range(len(full_data)) if mask[i]]
    
    print(f"✅ Cleaned {len(full_data) - len(cleaned_data)} outlier points.")
    print(f"💾 Saving {len(cleaned_data)} points to {output_file}...")

    try:
        with open(output_file, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=header)
            writer.writeheader()
            writer.writerows(cleaned_data)
        print("🎉 Processing complete!")
    except Exception as e:
        print(f"❌ Error saving CSV: {e}")

if __name__ == "__main__":
    clean_mps_points()
