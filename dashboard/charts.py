"""Altair chart builders for the China population dashboard."""
from __future__ import annotations

import altair as alt
import pandas as pd

COLOR_THEMES = [
    "blues",
    "cividis",
    "greens",
    "inferno",
    "magma",
    "plasma",
    "reds",
    "rainbow",
    "turbo",
    "viridis",
]


def make_heatmap(
    input_df: pd.DataFrame,
    input_y: str,
    input_x: str,
    input_color: str,
    input_color_theme: str,
) -> alt.Chart:
    heatmap = (
        alt.Chart(input_df)
        .mark_rect(stroke="#111111", strokeWidth=0.3)
        .encode(
            y=alt.Y(
                f"{input_y}:O",
                axis=alt.Axis(
                    title="年份",
                    titleFontSize=16,
                    titlePadding=12,
                    titleFontWeight="bold",
                    labelAngle=0,
                ),
            ),
            x=alt.X(
                f"{input_x}:O",
                axis=alt.Axis(
                    title="省份",
                    titleFontSize=16,
                    titlePadding=12,
                    titleFontWeight="bold",
                    labelAngle=-45,
                    labelFontSize=10,
                ),
            ),
            color=alt.Color(
                f"max({input_color}):Q",
                legend=None,
                scale=alt.Scale(scheme=input_color_theme),
            ),
            tooltip=[
                alt.Tooltip(f"{input_x}:N", title="省份"),
                alt.Tooltip(f"{input_y}:O", title="年份"),
                alt.Tooltip(f"max({input_color}):Q", title="人口", format=",.0f"),
            ],
        )
        .properties(width=900, height=330)
        .configure_axis(labelFontSize=11, titleFontSize=12)
    )
    return heatmap


def make_donut(input_response: int, input_text: str, input_color: str) -> alt.Chart:
    chart_colors = {
        "blue": ["#29b5e8", "#155F7A"],
        "green": ["#27AE60", "#12783D"],
        "orange": ["#F39C12", "#875A12"],
        "red": ["#E74C3C", "#781F16"],
    }
    colors = chart_colors.get(input_color, chart_colors["blue"])
    source = pd.DataFrame(
        {
            "Topic": ["", input_text],
            "value": [100 - input_response, input_response],
        }
    )
    background = pd.DataFrame(
        {
            "Topic": ["", input_text],
            "value": [100, 0],
        }
    )
    plot = (
        alt.Chart(source)
        .mark_arc(innerRadius=45, cornerRadius=25)
        .encode(
            theta="value:Q",
            color=alt.Color(
                "Topic:N",
                scale=alt.Scale(domain=[input_text, ""], range=colors),
                legend=None,
            ),
        )
        .properties(width=130, height=130)
    )
    text = plot.mark_text(
        align="center",
        color=colors[0],
        font="Lato",
        fontSize=28,
        fontWeight=700,
        fontStyle="italic",
    ).encode(text=alt.value(f"{input_response} %"))
    plot_bg = (
        alt.Chart(background)
        .mark_arc(innerRadius=45, cornerRadius=20)
        .encode(
            theta="value:Q",
            color=alt.Color(
                "Topic:N",
                scale=alt.Scale(domain=[input_text, ""], range=colors),
                legend=None,
            ),
        )
        .properties(width=130, height=130)
    )
    return plot_bg + plot + text


def make_trend(input_df: pd.DataFrame, input_color_theme: str) -> alt.Chart:
    base = alt.Chart(input_df).encode(
        x=alt.X(
            "year:O",
            axis=alt.Axis(
                title="年份",
                titleFontSize=16,
                titlePadding=12,
                labelAngle=0,
            ),
        ),
        y=alt.Y(
            "population:Q",
            axis=alt.Axis(title="人口（人）", titleFontSize=16, format="~s"),
        ),
        tooltip=[
            alt.Tooltip("year:O", title="年份"),
            alt.Tooltip("provinces:N", title="省份"),
            alt.Tooltip("population:Q", title="人口", format=",.0f"),
        ],
    )
    line = base.mark_line(point=alt.OverlayMarkDef(size=55), strokeWidth=3).encode(
        color=alt.Color(
            "provinces:N",
            scale=alt.Scale(scheme=input_color_theme),
            legend=None,
        ),
    )
    return line.properties(width=1100, height=300).interactive()
