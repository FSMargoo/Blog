#!/usr/bin/env python3
"""
Spherical function plotter — visualize f(ω) on a 3D sphere.

Usage:
    python spherical_plot.py

Define your f(omega) in the function below. The script maps it onto a unit
sphere, coloring each point by the function value.

ω = (θ, φ) where θ ∈ [0, π] is the polar angle (0 = north pole) and
φ ∈ [0, 2π] is the azimuthal angle.

The sphere is rendered with a 3D perspective projection; warmer colors
indicate larger values, cooler colors indicate smaller values.
"""

import numpy as np
import matplotlib.pyplot as plt
from matplotlib import cm
from matplotlib.colors import Normalize
from mpl_toolkits.mplot3d import Axes3D  # noqa: F401 — registers the 3D projection


# ──────────────────────────────────────────────────────────────────────
# Define your spherical function here.
#
# Input:
#   theta : 2D array of polar angles       (rows: θ, cols: φ)
#   phi   : 2D array of azimuthal angles   (rows: θ, cols: φ)
#
# Output:
#   2D array of function values at each (θ, φ).
#
# The default below is a Phong-like lobe: f(ω) = max(0, cos(θ))^n
# ──────────────────────────────────────────────────────────────────────

def f_spherical(theta: np.ndarray, phi: np.ndarray) -> np.ndarray:
    """
    Example: a clamped-cosine lobe (Lambertian) raised to a power.

    Replace this with your own function of spherical direction ω = (θ, φ).
    """
    n = 3.0  # shininess exponent
    return np.maximum(0.0, np.cos(theta)) ** n


# ──────────────────────────────────────────────────────────────────────
# Alternative examples — uncomment one and comment out f_spherical above.
# ──────────────────────────────────────────────────────────────────────

def _example_ltc_like(theta, phi):
    """
    A rough approximation of a Linearly Transformed Cosine distribution.

    An LTC is cos(θ_o) linearly transformed by a 3×3 matrix M.
    Here we fake it by stretching the lobe anisotropically.
    """
    # Stretch along x and compress along y to simulate a linear transform
    x = np.sin(theta) * np.cos(phi)
    y = np.sin(theta) * np.sin(phi)
    z = np.cos(theta)

    # Rough approximation of an LTC with an anisotropic lobe
    scale_x, scale_y, scale_z = 2.0, 0.6, 1.0
    denom = np.sqrt((x / scale_x) ** 2 + (y / scale_y) ** 2 + (z / scale_z) ** 2)
    dot = z / denom  # effective cosine
    return np.maximum(0.0, dot) ** 3.0


def _example_spherical_gaussian(theta, phi):
    """Spherical Gaussian (von Mises–Fisher-like)."""
    # Center direction in Cartesian
    cx, cy, cz = 0.3, 0.4, np.sqrt(1 - 0.3**2 - 0.4**2)
    dot = (np.sin(theta) * np.cos(phi) * cx
           + np.sin(theta) * np.sin(phi) * cy
           + np.cos(theta) * cz)
    kappa = 8.0  # concentration
    return np.exp(kappa * (dot - 1.0))


# ══════════════════════════════════════════════════════════════════════
# Plotting — you shouldn't need to edit below this line.
# ══════════════════════════════════════════════════════════════════════

def plot_spherical_function(
    f,
    resolution: int = 200,
    colormap=cm.viridis,
    alpha: float = 1.0,
    title: str = r"$f(\omega)$ on the sphere",
    figsize: tuple = (10, 9),
    elev: float = 25.0,
    azim: float = -60.0,
    colorbar_label: str = r"$f(\omega)$",
    antialias: bool = True,
    show_edges: bool = False,
):
    """
    Plot a scalar function defined on the unit sphere.

    Parameters
    ----------
    f : callable
        Function f(theta, phi) → ndarray, where theta and phi are 2D
        arrays of the same shape covering the sphere.
    resolution : int
        Number of samples along θ (rows) and φ (cols).
    colormap : matplotlib colormap
    alpha : float
        Surface opacity.
    title : str
    figsize : tuple
    elev, azim : float
        Initial camera elevation and azimuth (degrees).
    colorbar_label : str
    antialias : bool
        Use antialiased rendering.
    show_edges : bool
        Overlay the wireframe edges.
    """
    # ---- Sample the sphere -------------------------------------------
    theta = np.linspace(0, np.pi, resolution)       # polar angle
    phi = np.linspace(0, 2 * np.pi, 2 * resolution)  # azimuth
    theta_grid, phi_grid = np.meshgrid(theta, phi, indexing='ij')

    # ---- Evaluate the function ---------------------------------------
    values = f(theta_grid, phi_grid)

    # ---- Spherical → Cartesian ---------------------------------------
    r = 1.0  # unit sphere
    x = r * np.sin(theta_grid) * np.cos(phi_grid)
    y = r * np.sin(theta_grid) * np.sin(phi_grid)
    z = r * np.cos(theta_grid)

    # ---- Colormap & normalization ------------------------------------
    vmin, vmax = values.min(), values.max()
    if np.isclose(vmin, vmax):
        vmin, vmax = vmin - 0.01, vmax + 0.01  # avoid degenerate norm

    norm = Normalize(vmin=vmin, vmax=vmax)
    face_colors = colormap(norm(values))
    # face_colors has shape (resolution, 2*resolution, 4)

    # ---- Set up the figure -------------------------------------------
    fig = plt.figure(figsize=figsize, dpi=100)
    ax = fig.add_subplot(111, projection='3d')

    # ---- Draw the sphere surface -------------------------------------
    surf = ax.plot_surface(
        x, y, z,
        rstride=1,
        cstride=1,
        facecolors=face_colors,
        alpha=alpha,
        antialiased=antialias,
        shade=True,         # 3D lighting for depth perception
        linewidth=0,
    )

    # Optional wireframe overlay for shape clarity
    if show_edges:
        stride = max(1, resolution // 20)
        ax.plot_wireframe(x, y, z, rstride=stride, cstride=stride,
                          color='black', linewidth=0.15, alpha=0.25)

    # ---- Colour bar --------------------------------------------------
    mappable = cm.ScalarMappable(norm=norm, cmap=colormap)
    mappable.set_array(values)
    cbar = fig.colorbar(mappable, ax=ax, shrink=0.6, aspect=18, pad=0.08)
    cbar.set_label(colorbar_label, fontsize=11)

    # ---- Styling -----------------------------------------------------
    ax.set_xlabel('X')
    ax.set_ylabel('Y')
    ax.set_zlabel('Z')

    # Equal aspect ratio so the sphere looks spherical
    ax.set_box_aspect([1.0, 1.0, 1.0])

    # Remove panes and grid for a cleaner look
    ax.xaxis.pane.fill = False
    ax.yaxis.pane.fill = False
    ax.zaxis.pane.fill = False
    ax.xaxis.pane.set_edgecolor('white')
    ax.yaxis.pane.set_edgecolor('white')
    ax.zaxis.pane.set_edgecolor('white')
    ax.grid(True, alpha=0.3)

    # Ticks
    ax.set_xticks([-1, 0, 1])
    ax.set_yticks([-1, 0, 1])
    ax.set_zticks([-1, 0, 1])

    # Viewpoint
    ax.view_init(elev=elev, azim=azim)

    fig.tight_layout()
    return fig, ax


# ══════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(
        description='Visualize a spherical function f(ω) on a 3D sphere.'
    )
    parser.add_argument(
        '--resolution', type=int, default=200,
        help='Sampling resolution (default: 200).'
    )
    parser.add_argument(
        '--example', choices=['default', 'ltc', 'gaussian'], default='default',
        help='Which example function to plot.'
    )
    parser.add_argument(
        '--cmap', default='viridis',
        help='Matplotlib colormap name (default: viridis).'
    )
    parser.add_argument(
        '--alpha', type=float, default=1.0,
        help='Surface opacity (default: 1.0).'
    )
    parser.add_argument(
        '--elev', type=float, default=25.0,
        help='Camera elevation angle (default: 25).'
    )
    parser.add_argument(
        '--azim', type=float, default=-60.0,
        help='Camera azimuth angle (default: -60).'
    )
    parser.add_argument(
        '--edges', action='store_true',
        help='Show wireframe edges.'
    )
    parser.add_argument(
        '--save', type=str, default=None,
        help='Save figure to file instead of displaying. e.g. --save sphere.png'
    )
    parser.add_argument(
        '--no-shade', action='store_true',
        help='Disable 3D lighting shade.'
    )

    args = parser.parse_args()

    # Select example
    examples = {
        'default': ('Default — clamped-cosine lobe (n=5)', f_spherical),
        'ltc':     ('LTC-like — anisotropic lobe',       _example_ltc_like),
        'gaussian':('Spherical Gaussian',                _example_spherical_gaussian),
    }
    label, func = examples[args.example]

    fig, ax = plot_spherical_function(
        f=func,
        resolution=args.resolution,
        colormap=plt.get_cmap(args.cmap),
        alpha=args.alpha,
        title=label,
        elev=args.elev,
        azim=args.azim,
        show_edges=args.edges,
    )

    # Override shade if requested
    if args.no_shade:
        # Re-render without shade — quick hack
        ax.clear()
        # (rebuilding is easier than patching — just close and redo)
        plt.close(fig)
        fig, ax = plot_spherical_function(
            f=func,
            resolution=args.resolution,
            colormap=plt.get_cmap(args.cmap),
            alpha=args.alpha,
            title=label,
            elev=args.elev,
            azim=args.azim,
            show_edges=args.edges,
        )
        # Remove shading by iterating polys
        for collection in ax.collections:
            collection.set_shade(False)

    if args.save:
        fig.savefig(args.save, dpi=200, bbox_inches='tight',
                    facecolor='white', edgecolor='none')
        print(f'Saved to {args.save}')
    else:
        plt.show()
