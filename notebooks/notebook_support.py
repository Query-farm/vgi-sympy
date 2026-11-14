"""Small presentation and parameter helpers for the symbolic walkthrough."""

from __future__ import annotations

import math

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns
from IPython.display import Markdown, display

GREEN, BLUE, ORANGE = "#246B50", "#426DB3", "#C17B36"
SOURCE = "Synthetic pulse model · symbolic derivation and evaluation: SymPy via Haybarn / VGI · Query.Farm"


def validate_parameters(duration: float, coefficient: float, drain: float, initial: float, points: int) -> None:
    """Reject unsupported model parameters before starting the worker."""
    values = [duration, coefficient, drain, initial]
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in values):
        raise ValueError("Model parameters must be finite numbers.")
    if not (1 <= duration <= 60 and 0.01 <= coefficient <= 2 and 1 <= initial <= 10000):
        raise ValueError("Use duration 1–60 min, coefficient 0.01–2 L/min³ and initial volume 1–10000 L.")
    if not 0 < drain < coefficient * duration**2 / 4:
        raise ValueError("Drain must be positive and below the pulse's maximum inflow a·duration²/4.")
    if isinstance(points, bool) or not isinstance(points, int) or not 51 <= points <= 501:
        raise ValueError("GRID_POINTS must be an integer from 51 to 501.")


def prose(text: str) -> None:
    """Display result-derived Markdown without exposing presentation source."""
    display(Markdown(text))


def set_theme() -> None:
    """Apply consistent, readable chart and table defaults."""
    sns.set_theme(
        style="whitegrid",
        context="notebook",
        palette=[GREEN, BLUE, ORANGE],
        rc={
            "figure.dpi": 140,
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "axes.edgecolor": "#CCD5CF",
            "axes.labelcolor": "#405047",
            "text.color": "#243B2F",
            "grid.color": "#E8EDE9",
            "grid.linewidth": 0.7,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.titlelocation": "left",
            "axes.titleweight": "semibold",
            "legend.frameon": False,
            "lines.linewidth": 2.2,
            "text.parse_math": False,
        },
    )
    pd.set_option("display.max_columns", 12)
    pd.set_option("display.precision", 4)


def finish_chart(fig: object, title: str, subtitle: str) -> None:
    """Add shared chart context and show the embedded output."""
    fig.text(0.08, 0.98, title, ha="left", va="top", fontsize=17, fontweight="semibold")
    fig.text(0.08, 0.905, subtitle, ha="left", va="top", fontsize=10.5, color="#58685F")
    fig.tight_layout(rect=(0, 0.085, 1, 0.84), w_pad=2.5)
    fig.text(0.08, 0.018, SOURCE, ha="left", va="bottom", fontsize=8, color="#78857D")
    plt.show()
