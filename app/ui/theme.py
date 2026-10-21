"""Colors per light/dark mode. Surfaces and the categorical order mirror .streamlit/config.toml.

Categorical slots are assigned in fixed order to subsidiaries (sorted id), so a subsidiary keeps
its color on every chart and under every filter. The first four slots pass the palette validator
(colorblind-safe adjacent pairs) in both modes; light-mode aqua/yellow sit below 3:1 contrast, so
charts always carry a legend, tooltips and a table view.
"""

import streamlit as st

SERIES = {
    "light": [
        "#2a78d6",
        "#eb6834",
        "#1baf7a",
        "#eda100",
        "#e87ba4",
        "#008300",
        "#6250d6",
        "#e34948",
    ],
    "dark": [
        "#3987e5",
        "#d95926",
        "#199e70",
        "#c98500",
        "#d55181",
        "#008300",
        "#9085e9",
        "#e66767",
    ],
}
SURFACE = {"light": "#fcfcfb", "dark": "#1a1a19"}
TEXT_SECONDARY = {"light": "#52514e", "dark": "#c3c2b7"}
HIGHLIGHT_ROW = {"light": "#fff1c2", "dark": "#4a3d12"}  # matches the PDF clause highlight


def mode() -> str:
    theme = getattr(st.context, "theme", None)
    return "dark" if theme is not None and theme.type == "dark" else "light"


def series() -> list[str]:
    return SERIES[mode()]


def surface() -> str:
    return SURFACE[mode()]


def text_secondary() -> str:
    return TEXT_SECONDARY[mode()]


def highlight_row() -> str:
    return HIGHLIGHT_ROW[mode()]
