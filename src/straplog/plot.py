"""
House chart style for the H10 skills (plotnine): system-sans typography, a
recessive grid, hairline axes, and a validated categorical palette.
Needs the `plot` extra: `pip install straplog[plot]`.

    from straplog import plot as chart_style
    from plotnine import ggplot, aes, geom_line
    p = (ggplot(df, aes("x", "y"))
         + geom_line(color=chart_style.SERIES["blue"])
         + chart_style.theme_house())
    p.save(path, dpi=chart_style.DPI, width=..., height=..., verbose=False)

plotnine has no global rcParams: every ``ggplot`` needs
``+ chart_style.theme_house()`` and every ``.save()`` an explicit
``dpi=chart_style.DPI``.
"""

from __future__ import annotations

import numpy as np
from plotnine import (
    aes, annotate, element_blank, element_line, element_rect, element_text,
    theme, theme_minimal,
)

# ---------- palette --------------------------------------------------------
# Categorical slots in fixed order. Assign by slot, never cycle: the ordering
# is what keeps adjacent pairs distinguishable under colour-vision deficiency.

SERIES = {
    "blue":    "#2a78d6",
    "green":   "#008300",
    "magenta": "#e87ba4",
    "yellow":  "#eda100",
    "aqua":    "#1baf7a",
    "orange":  "#eb6834",
    "violet":  "#4a3aa7",
    "red":     "#e34948",
}
SERIES_ORDER = list(SERIES.values())

# Chrome and text. Series colours identify marks; text stays in ink.
INK = {
    "surface":   "#fcfcfb",
    "primary":   "#0b0b0b",   # titles
    "secondary": "#52514e",   # axis titles, annotations
    "muted":     "#898781",   # tick labels, de-emphasised marks
    "grid":      "#e1e0d9",
    "baseline":  "#c3c2b7",   # axis spines / reference lines
}

# Reserved for state, never for a series.
STATUS = {
    "good":     "#0ca30c",
    "warning":  "#fab219",
    "serious":  "#ec835a",
    "critical": "#d03b3b",
}

# HR training-zone bands (Z1..Z5), painted as backgrounds behind the trace.
# Cool->warm rather than a single-hue ramp: "hot = hard" is the training
# convention and carries real meaning here. Chroma is held low so the bands
# stay behind the data. Use at full opacity - alpha is baked into these steps.
ZONE_BANDS = ["#eef4fb", "#e9f3ec", "#fbf4e2", "#fbeade", "#fae4e4"]

# Sequential blue ramp, light -> dark, for continuous magnitude.
SEQUENTIAL_BLUE = [
    "#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5",
    "#2a78d6", "#256abf", "#184f95", "#0d366b",
]

FONT_FAMILY = "Helvetica Neue"   # falls back per-system font resolution
DPI = 150                        # pass explicitly to every p.save(...)


def theme_house(base_size: int = 10):
    """The plotnine equivalent of the old apply(): chain onto every ggplot."""
    return theme_minimal(base_size=base_size) + theme(
        text=element_text(family=FONT_FAMILY, color=INK["primary"]),
        plot_title=element_text(size=base_size * 1.3, weight="bold",
                                color=INK["primary"]),
        axis_title=element_text(size=base_size, color=INK["secondary"]),
        axis_text=element_text(size=base_size * 0.9, color=INK["muted"]),
        plot_background=element_rect(fill=INK["surface"], color=INK["surface"]),
        panel_background=element_rect(fill=INK["surface"], color=INK["surface"]),
        panel_grid_major=element_line(color=INK["grid"], linewidth=0.6),
        panel_grid_minor=element_blank(),
        axis_ticks=element_blank(),
        legend_background=element_blank(),
        legend_key=element_blank(),
        legend_title=element_text(size=base_size * 0.9, color=INK["secondary"]),
        legend_text=element_text(size=base_size * 0.9, color=INK["secondary"]),
        strip_background=element_blank(),
    )


# ---------- shared layer helpers -------------------------------------------

def zone_band_layers(zones, hr_max: float, hr_rest: float):
    """zones: list of (name, lo_frac, hi_frac) Karvonen tuples, e.g. the
    ZONES constant each analysis script already defines. Returns a list of
    ``annotate("rect", ...)`` layers, cool->warm, meant to be added first so
    they render behind the data (mirrors the old ax.axhspan loop)."""
    reserve = max(1.0, hr_max - hr_rest)
    layers = []
    for (_name, lo, hi), color in zip(zones, ZONE_BANDS):
        y_lo = hr_rest + lo * reserve
        y_hi = hr_rest + hi * reserve
        layers.append(annotate("rect", xmin=-np.inf, xmax=np.inf,
                                ymin=y_lo, ymax=y_hi, fill=color))
    return layers


def event_marker_layers(ev_df, x_col: str = "t_min", label_col: str = None,
                        y_top: float = None, color: str = None):
    """Vertical dotted lines for each row in ev_df (an events dataframe with
    at least an x_col), mirroring the old per-row ax.axvline + optional rotated
    ax.text. If label_col is given, adds rotated top-anchored text -- y_top must
    be supplied (plotnine has no "top of current axis" primitive; the caller
    computes the y-range from the data first, e.g. ``feat['hr_bpm'].max()``)."""
    from plotnine import geom_text, geom_vline
    color = color or INK["baseline"]
    layers = [geom_vline(data=ev_df, mapping=aes(xintercept=x_col),
                         color=color, linetype="dotted", size=0.9)]
    if label_col and y_top is not None:
        layers.append(geom_text(data=ev_df, mapping=aes(x=x_col, label=label_col),
                                y=y_top, angle=90, ha="left", va="top",
                                size=7, color=color))
    return layers
