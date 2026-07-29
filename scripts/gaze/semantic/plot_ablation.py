#!/usr/bin/env python3
"""
PLOT ABLATION STUDY RESULTS
Loads ablation_edges.json and generates visualizations to help explore
parameter combinations and find sweet spots for edge counts.

Usage:
    python plot_ablation.py

Outputs to ablation_plots/:
    ablation_overview.png      - 6-panel overview of each parameter
    ablation_heatmap.png       - alpha x threshold (mean, log10, variance)
    ablation_importance.png    - parameter sensitivity at each threshold
    ablation_targets.png       - contour plot showing where to get N edges
    ablation_data.csv          - raw data (alpha,beta,gamma,lam,threshold,edges)
"""

import os
import json
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import seaborn as sns

sns.set_style("whitegrid")
sns.set_context("talk")

INPUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "ablation_edges.json")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "ablation_plots")


def load():
    with open(INPUT) as f:
        return json.load(f)["results"]


def build_df(results):
    rows = []
    for r in results:
        if len(r) == 6:
            rows.append({"alpha": r[0], "beta": r[1], "gamma": r[2], "lam": r[3], "threshold": r[4], "edges": r[5]})
        else:
            rows.append({"alpha": r[0], "beta": r[1], "gamma": r[2], "threshold": r[3], "edges": r[4]})
    return rows


# ---- Plots: one-line sweeps ----
def plot_threshold(results, ax):
    df = build_df(results)
    for alpha in [0.5, 0.7, 0.9]:
        subset = [r for r in df if r["alpha"] == alpha]
        thresholds = sorted(set(r["threshold"] for r in subset))
        means = [np.mean([r["edges"] for r in subset if r["threshold"] == t]) for t in thresholds]
        ax.plot(thresholds, means, marker="o", label=f"alpha={alpha}", linewidth=2.5)

    ax.set_xlabel("Threshold")
    ax.set_ylabel("Edge Count (mean over beta/gamma)")
    ax.set_title("Edge count vs threshold")
    ax.set_yscale("log")
    ax.set_ylim(1, 3000)
    ax.legend()


def plot_alpha(results, ax):
    df = build_df(results)
    for thr in [0.35, 0.45, 0.55, 0.65]:
        subset = [r for r in df if r["threshold"] == thr]
        alphas = sorted(set(r["alpha"] for r in subset))
        means = [np.mean([r["edges"] for r in subset if r["alpha"] == a]) for a in alphas]
        ax.plot(alphas, means, marker="s", label=f"thr={thr}", linewidth=2.5)

    ax.set_xlabel("Alpha")
    ax.set_ylabel("Edge Count (mean over beta/gamma)")
    ax.set_title("Edge count vs alpha")
    ax.set_yscale("log")
    ax.set_ylim(1, 3000)
    ax.legend()


def plot_gamma(results, ax):
    df = build_df(results)
    for alpha in [0.7, 0.9]:
        for thr in [0.45, 0.55]:
            subset = [r for r in df if r["alpha"] == alpha and r["threshold"] == thr]
            gammas = sorted(set(r["gamma"] for r in subset))
            means = [np.mean([r["edges"] for r in subset if r["gamma"] == g]) for g in gammas]
            ax.plot(gammas, means, marker="d", label=f"a={alpha} t={thr}", linewidth=2)

    ax.set_xlabel("Gamma")
    ax.set_ylabel("Edge Count")
    ax.set_title("Edge count vs gamma (minimal effect)")
    ax.set_yscale("log")
    ax.set_ylim(1, 2500)
    ax.legend(fontsize=9)


def plot_beta(results, ax):
    df = build_df(results)
    for alpha in [0.7, 0.9]:
        for thr in [0.45, 0.55]:
            subset = [r for r in df if r["alpha"] == alpha and r["threshold"] == thr]
            betas = sorted(set(r["beta"] for r in subset))
            means = [np.mean([r["edges"] for r in subset if r["beta"] == b]) for b in betas]
            ax.plot(betas, means, marker="^", label=f"a={alpha} t={thr}", linewidth=2)

    ax.set_xlabel("Beta")
    ax.set_ylabel("Edge Count")
    ax.set_title("Edge count vs beta (moderate effect)")


def plot_lam(results, ax):
    """Edge count vs lam (spatial decay rate)."""
    df = build_df(results)
    for alpha in [0.7, 0.9]:
        for thr in [0.45, 0.55]:
            subset = [r for r in df if r["alpha"] == alpha and r["threshold"] == thr]
            lams = sorted(set(r["lam"] for r in subset if r.get("lam") is not None))
            means = [np.mean([r["edges"] for r in subset if r["lam"] == l]) for l in lams]
            ax.plot(lams, means, marker="x", label=f"a={alpha} t={thr}", linewidth=2)

    ax.set_xlabel("lam (decay rate, 1/m)")
    ax.set_ylabel("Edge Count")
    ax.set_title("Edge count vs lam (spatial decay)")
    ax.set_yscale("log")
    ax.set_ylim(1, 2500)
    ax.legend(fontsize=9)
    ax.set_yscale("log")
    ax.set_ylim(1, 2500)
    ax.legend(fontsize=9)


# ---- Heatmap ----
def plot_heatmap(results, ax):
    df = build_df(results)
    alphas = sorted(set(r["alpha"] for r in df))
    thresholds = sorted(set(r["threshold"] for r in df))
    matrix = np.zeros((len(alphas), len(thresholds)))

    for i, alpha in enumerate(alphas):
        for j, thr in enumerate(thresholds):
            vals = [r["edges"] for r in df if r["alpha"] == alpha and r["threshold"] == thr]
            matrix[i, j] = np.mean(vals) if vals else 0

    im = ax.imshow(matrix, cmap="viridis", aspect="auto", origin="lower",
                   extent=[min(thresholds)-0.05, max(thresholds)+0.05,
                           min(alphas)-0.05, max(alphas)+0.05],
                   vmin=0.1)
    ax.set_xlabel("Threshold")
    ax.set_ylabel("Alpha")
    ax.set_title("Edge count (mean over beta/gamma)")

    for i in range(len(alphas)):
        for j in range(len(thresholds)):
            ax.text(j + 0.5, i + 0.5, f"{matrix[i,j]:.0f}", ha="center", va="center",
                    fontsize=10, color="white" if matrix[i,j] > matrix.max()*0.6 else "black")

    plt.colorbar(im, ax=ax, label="edges")


# ---- Parameter importance ----
def plot_importance(results, ax):
    """Higher bar = that parameter has more influence on edge count at this threshold."""
    df = build_df(results)
    thresholds = [0.35, 0.45, 0.55, 0.65]
    params = ["alpha", "beta", "gamma", "lam"]
    colors = {"alpha": "#2196F3", "beta": "#4CAF50", "gamma": "#FF9800", "lam": "#9C27B0"}
    x = np.arange(len(thresholds))
    width = 0.25

    for pi, param in enumerate(params):
        stds = []
        for thr in thresholds:
            subset = [r for r in df if r["threshold"] == thr]
            vals_by_p = {}
            for r in subset:
                vals_by_p.setdefault(r[param], []).append(r["edges"])
            means = [np.mean(v) for v in vals_by_p.values()]
            stds.append(np.std(means))
        ax.bar(x[pi] + pi*width, stds, width, label=f"d(edge)/d({param})", color=colors[param], alpha=0.8)

    ax.set_xticks(x + width)
    ax.set_xticklabels([str(t) for t in thresholds])
    ax.set_xlabel("Fixed threshold")
    ax.set_ylabel("Sensitivity (std of means across param values)")
    ax.set_title("Parameter importance")
    ax.legend(fontsize=9)


# ---- Target contour plot ----
def plot_targets(results, ax):
    """Contour plot: where do I get exactly N edges?"""
    df = build_df(results)

    points = np.array([[r["alpha"], r["threshold"]] for r in df])
    vals = np.array([r["edges"] for r in df])

    xi = np.linspace(points[:, 0].min(), points[:, 0].max(), 100)
    yi = np.linspace(points[:, 1].min(), points[:, 1].max(), 100)
    Xi, Yi = np.meshgrid(xi, yi)

    from scipy.interpolate import Rbf
    try:
        rbf = Rbf(points[:, 0], points[:, 1], vals, function='cubic')
        Zi = rbf(Xi, Yi)
    except Exception:
        from scipy.interpolate import griddata
        Zi = griddata(points, vals, (Xi, Yi), method='cubic')

    im = ax.contourf(Xi, Yi, Zi, levels=20, cmap="viridis")
    targets = [50, 100, 200, 500, 1000, 2000]
    contours = ax.contour(Xi, Yi, Zi, levels=targets, colors="white", linewidths=1.5, alpha=0.7)
    ax.clabel(contours, inline=True, fontsize=8, fmt="=%d")

    ax.set_xlabel("Alpha")
    ax.set_ylabel("Threshold")
    ax.set_title("Find configs: where to get N edges")
    plt.colorbar(im, ax=ax, label="edges")


# ---- Histogram ----
def plot_hist(results, ax):
    df = build_df(results)
    edges = np.array([r["edges"] for r in df])
    ax.hist(edges, bins=40, color="steelblue", edgecolor="white")
    ax.set_xlabel("Edge Count")
    ax.set_ylabel("Parameter combos")
    ax.set_title(f"Edge count distribution ({len(df)} configs)")


def main():
    os.makedirs(OUT, exist_ok=True)
    results = load()
    df = build_df(results)

    # 6-panel overview (lam replaces histogram)
    fig, axes = plt.subplots(2, 3, figsize=(21, 13))
    plot_threshold(results, axes[0, 0])
    plot_alpha(results, axes[0, 1])
    plot_heatmap(results, axes[0, 2])
    plot_gamma(results, axes[1, 0])
    plot_beta(results, axes[1, 1])
    plot_lam(results, axes[1, 2])
    fig.subplots_adjust(hspace=0.35, wspace=0.3)
    plt.savefig(os.path.join(OUT, "ablation_overview.png"), dpi=150, bbox_inches="tight")
    plt.close()

    # Alpha x threshold detail
    fig2, axes2 = plt.subplots(1, 3, figsize=(18, 5))
    for sub_idx, (title, matrix_key) in enumerate([
        ("Mean edge count", "edges"),
        ("Mean edge count (log10)", "log"),
        ("Variance (beta/gamma effect)", "var"),
    ]):
        alphas = sorted(set(r["alpha"] for r in df))
        thresholds = sorted(set(r["threshold"] for r in df))
        matrix = np.zeros((len(alphas), len(thresholds)))
        for i, alpha in enumerate(alphas):
            for j, thr in enumerate(thresholds):
                vals = [r["edges"] for r in df if r["alpha"] == alpha and r["threshold"] == thr]
                if matrix_key == "log":
                    matrix[i, j] = np.log10(np.mean(vals)) if vals else 0
                elif matrix_key == "var":
                    matrix[i, j] = np.var(vals) if len(vals) > 1 else 0
                else:
                    matrix[i, j] = np.mean(vals) if vals else 0

        im = axes2[sub_idx].imshow(matrix, cmap="viridis", aspect="auto", origin="lower",
                                   vmin=0.1 if matrix_key == "log" else None)
        cbar_label = {"edges": "edges", "log": "log10(edges)", "var": "variance"}[matrix_key]
        plt.colorbar(im, ax=axes2[sub_idx], label=cbar_label)
        axes2[sub_idx].set_xlabel("Threshold")
        axes2[sub_idx].set_ylabel("Alpha")
        axes2[sub_idx].set_title(title)
        axes2[sub_idx].set_yticks(np.arange(len(alphas)) + 0.5)
        axes2[sub_idx].set_yticklabels([str(a) for a in alphas], rotation=0)

    fig2.subplots_adjust(wspace=0.3)
    plt.savefig(os.path.join(OUT, "ablation_heatmap.png"), dpi=150, bbox_inches="tight")
    plt.close()

    # Parameter importance
    fig3, ax3 = plt.subplots(1, 1, figsize=(10, 6))
    plot_importance(results, ax3)
    fig3.subplots_adjust(hspace=0.35)
    plt.savefig(os.path.join(OUT, "ablation_importance.png"), dpi=150, bbox_inches="tight")
    plt.close()

    # Target contours
    fig4, ax4 = plt.subplots(1, 1, figsize=(10, 7))
    plot_targets(results, ax4)
    fig4.subplots_adjust(hspace=0.35)
    plt.savefig(os.path.join(OUT, "ablation_targets.png"), dpi=150, bbox_inches="tight")
    plt.close()

    # CSV + top configs
    csv_path = os.path.join(OUT, "ablation_data.csv")
    with open(csv_path, "w") as f:
        f.write("alpha,beta,gamma,lam,threshold,edges\n")
        for r in df:
            lam_val = r.get("lam", "NA")
            f.write(f"{r['alpha']},{r['beta']},{r['gamma']},{lam_val},{r['threshold']},{r['edges']}\n")

    print("\nTop configs per edge count range:")
    for lo, hi in [(0, 50), (50, 100), (100, 300), (300, 500), (500, 1000), (1000, 2000), (2000, 10000)]:
        subset = [r for r in df if lo <= r["edges"] < hi]
        if not subset:
            continue
        mid = (lo + hi) / 2
        subset.sort(key=lambda r: abs(r["edges"] - mid))
        top3 = subset[:3]
        print(f"\n  {lo}-{hi} edges (mid={mid:.0f}):")
        for r in top3:
            lam_val = r.get("lam", "NA")
            print(f"    alpha={r['alpha']}, beta={r['beta']}, gamma={r['gamma']}, lam={lam_val}, threshold={r['threshold']} => {r['edges']}")

    print(f"\nCSV: {csv_path}")
    print(f"\nPlots in {OUT}/:")
    for name in ["ablation_overview.png", "ablation_heatmap.png",
                  "ablation_importance.png", "ablation_targets.png"]:
        path = os.path.join(OUT, name)
        sz = os.path.getsize(path) / 1024
        print(f"  {name} ({sz:.0f} KB)")


if __name__ == "__main__":
    main()
