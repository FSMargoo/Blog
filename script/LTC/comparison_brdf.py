#!/usr/bin/env python3
"""
Side-by-side spherical distribution comparison:
  Left  — Clamped cosine distribution  max(0, cos θ) / π
  Right — GGX microfacet target distribution BRDF · max(0, n·ω_i)
          (θ_v = 45°, α = 0.3)

GGX uses Cook–Torrance with Trowbridge–Reitz NDF, Smith GGX geometry,
and Schlick Fresnel (F0 = 1 for the "white furnace" shape).

Each sphere uses its own colour range by default so every lobe is clearly
visible.  Pass --shared-scale to use a single range across both.
"""

import numpy as np
import matplotlib.pyplot as plt
from matplotlib import cm
from matplotlib.colors import Normalize, PowerNorm

# ──────────────────────────────────────────────────────────────────────
#  Clamped cosine
# ──────────────────────────────────────────────────────────────────────

def clamped_cosine(theta: np.ndarray) -> np.ndarray:
    """Normalised clamped-cosine distribution on the sphere."""
    return np.maximum(0.0, np.cos(theta)) / np.pi


# ──────────────────────────────────────────────────────────────────────
#  GGX BRDF
# ──────────────────────────────────────────────────────────────────────

def ggx_ndf(cos_th: np.ndarray, alpha: float) -> np.ndarray:
    """GGX NDF:  D(h) = α² / (π · ((n·h)²·(α²−1) + 1)²)."""
    a2 = alpha * alpha
    denom = cos_th * cos_th * (a2 - 1.0) + 1.0
    return a2 / (np.pi * denom * denom)


def smith_g1(cos_th: np.ndarray, alpha: float) -> np.ndarray:
    """Smith GGX geometry term for a single direction."""
    a2 = alpha * alpha
    tan2 = (1.0 - cos_th * cos_th) / np.maximum(cos_th * cos_th, 1e-10)
    return 2.0 / (1.0 + np.sqrt(1.0 + a2 * tan2))


def schlick_fresnel(cos: np.ndarray, f0: float = 1.0) -> np.ndarray:
    """Schlick Fresnel approximation."""
    return f0 + (1.0 - f0) * np.power(np.maximum(1.0 - cos, 0.0), 5.0)


def ggx_brdf(theta_i: np.ndarray, phi_i: np.ndarray,
             theta_v: float, alpha: float, f0: float = 1.0) -> np.ndarray:
    """
    Cook–Torrance GGX BRDF for every incident direction (θ_i, φ_i),
    with a fixed view direction ω_o.
    """
    sin_ti, cos_ti = np.sin(theta_i), np.cos(theta_i)
    wi_x = sin_ti * np.cos(phi_i)
    wi_y = sin_ti * np.sin(phi_i)
    wi_z = cos_ti

    # View direction — φ_v = 0
    wo = np.array([np.sin(theta_v), 0.0, np.cos(theta_v)])

    # Half-vector  h = norm(wi + wo)
    hx, hy, hz = wi_x + wo[0], wi_y + wo[1], wi_z + wo[2]
    h_len = np.sqrt(hx * hx + hy * hy + hz * hz)
    inv_len = 1.0 / np.maximum(h_len, 1e-10)
    hx *= inv_len;  hy *= inv_len;  hz *= inv_len

    n_dot_wi = cos_ti
    n_dot_wo = wo[2]
    n_dot_h  = np.maximum(hz, 1e-8)
    h_dot_wo = np.maximum(hx * wo[0] + hy * wo[1] + hz * wo[2], 0.0)

    mask = (n_dot_wi > 0.0) & (n_dot_wo > 0.0)

    D   = ggx_ndf(n_dot_h, alpha)
    G1i = smith_g1(np.maximum(n_dot_wi, 1e-8), alpha)
    G1o = smith_g1(n_dot_wo, alpha)
    F   = schlick_fresnel(h_dot_wo, f0)

    brdf = F * (G1i * G1o) * D / (4.0 * np.maximum(n_dot_wi * n_dot_wo, 1e-8))
    brdf[~mask] = 0.0
    return brdf


# ──────────────────────────────────────────────────────────────────────
#  Spherical plotting
# ──────────────────────────────────────────────────────────────────────

def plot_one_sphere(ax, values, theta_grid, phi_grid, cmap, norm):
    """Draw a single coloured unit sphere onto a 3D axis."""
    x = np.sin(theta_grid) * np.cos(phi_grid)
    y = np.sin(theta_grid) * np.sin(phi_grid)
    z = np.cos(theta_grid)

    face_colors = cmap(norm(values))

    ax.plot_surface(
        x, y, z,
        rstride=1, cstride=1,
        facecolors=face_colors,
        antialiased=False,
        shade=False,
        linewidth=0,
        edgecolor='none',
    )

    ax.set_box_aspect([1.0, 1.0, 1.0])
    for pane in (ax.xaxis.pane, ax.yaxis.pane, ax.zaxis.pane):
        pane.fill = False
        pane.set_edgecolor((0.85, 0.85, 0.85))
    ax.grid(True, alpha=0.25)
    ax.set_xticks([-1, 0, 1])
    ax.set_yticks([-1, 0, 1])
    ax.set_zticks([-1, 0, 1])


# ──────────────────────────────────────────────────────────────────────
#  Main
# ──────────────────────────────────────────────────────────────────────

def main(resolution=200, alpha=0.3, theta_v_deg=45.0, cmap_name='inferno',
         save=None, shared_scale=False, elev=25.0, azim=180.0, gamma=0.35):
    theta_v = np.radians(theta_v_deg)

    # Sample the sphere
    theta = np.linspace(0, np.pi, resolution)
    phi   = np.linspace(0, 2 * np.pi, 2 * resolution)
    theta_grid, phi_grid = np.meshgrid(theta, phi, indexing='ij')

    # Evaluate
    vals_cos = clamped_cosine(theta_grid)
    # LTC approximates the integrand's directional part, not the bare BRDF.
    # Multiplying by n·wi also removes the GGX BRDF's grazing-angle rise.
    vals_ggx = ggx_brdf(theta_grid, phi_grid, theta_v, alpha)
    vals_ggx *= np.maximum(np.cos(theta_grid), 0.0)

    cmap = plt.get_cmap(cmap_name)

    # ---- Colour normalisation -----------------------------------------
    # Clamped cosine uses linear norm (gentle fall-off).
    norm_cos = Normalize(vmin=0, vmax=vals_cos.max())

    # GGX uses power-law norm to reveal structure across the wide
    # dynamic range (most values << peak).  gamma < 1 boosts lows.
    if shared_scale:
        norm_ggx = Normalize(vmin=0, vmax=max(vals_cos.max(), vals_ggx.max()))
    else:
        norm_ggx = PowerNorm(gamma=gamma, vmin=0, vmax=vals_ggx.max())

    # ---- Figure -------------------------------------------------------
    fig, (ax_l, ax_r) = plt.subplots(
        1, 2, figsize=(14, 7),
        subplot_kw={'projection': '3d'},
    )

    plot_one_sphere(ax_l, vals_cos, theta_grid, phi_grid, cmap, norm_cos)
    plot_one_sphere(ax_r, vals_ggx, theta_grid, phi_grid, cmap, norm_ggx)

    # Per-sphere colour bars
    for ax, vals, norm, label in [
        (ax_l, vals_cos, norm_cos,
         r'$\max(0,\cos\theta)/\pi$'),
        (ax_r, vals_ggx, norm_ggx,
         rf'GGX BRDF $\cdot\max(0,n\!\cdot\!\omega_i)$'
         rf'  $\theta_v={theta_v_deg:.0f}^\circ,\;\alpha={alpha}$'),
    ]:
        mappable = cm.ScalarMappable(norm=norm, cmap=cmap)
        mappable.set_array(vals)
        cbar = fig.colorbar(mappable, ax=ax, shrink=0.65, aspect=22, pad=0.06)
        cbar.set_label(label, fontsize=10)

    for ax in (ax_l, ax_r):
        ax.view_init(elev=elev, azim=azim)

    fig.subplots_adjust(left=0.01, right=0.93, top=0.95, bottom=0.03,
                        wspace=0.12)

    if save:
        fig.savefig(save, dpi=200, bbox_inches='tight',
                    facecolor='white', edgecolor='none')
        print(f'Saved to {save}')
    else:
        plt.show()


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(
        description='Side-by-side: clamped cosine vs GGX target distribution.'
    )
    parser.add_argument('--resolution', type=int, default=200)
    parser.add_argument('--alpha', type=float, default=0.3,
                        help='GGX roughness (default: 0.3).')
    parser.add_argument('--theta-v', type=float, default=45.0,
                        help='View polar angle in degrees (default: 45).')
    parser.add_argument('--cmap', default='inferno',
                        help='Matplotlib colormap (default: inferno).')
    parser.add_argument('--save', type=str, default=None,
                        help='Save to file instead of showing.')
    parser.add_argument('--shared-scale', action='store_true',
                        help='Use a single colour range for both spheres.')
    parser.add_argument('--elev', type=float, default=25.0,
                        help='Camera elevation (default: 25).')
    parser.add_argument('--azim', type=float, default=180.0,
                        help='Camera azimuth (default: 180, facing the GGX lobe).')
    parser.add_argument('--gamma', type=float, default=0.35,
                        help='Power-law gamma for GGX colour map (default: 0.35). '
                             '<1 boosts low values; 1 = linear.')
    args = parser.parse_args()

    main(resolution=args.resolution, alpha=args.alpha,
         theta_v_deg=args.theta_v, cmap_name=args.cmap,
         save=args.save, shared_scale=args.shared_scale,
         elev=args.elev, azim=args.azim, gamma=args.gamma)
