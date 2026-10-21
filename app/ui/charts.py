"""Altair charts on the theme palette.

Subsidiaries are colored by fixed slot (see theme.py) across every chart, with a legend and a
tooltip on every mark; values are never encoded by color alone.
"""

import altair as alt
import pandas as pd
import streamlit as st

from ui import format as fmt
from ui import theme

BAR_SIZE = 16


def _tenant_color(all_tenants: list[str]) -> alt.Color:
    labels = [fmt.tenant_label(t) for t in all_tenants]
    return alt.Color(
        "subsidiary:N",
        scale=alt.Scale(domain=labels, range=theme.series()[: len(labels)]),
        legend=alt.Legend(title=None, orient="top", direction="horizontal", symbolType="square"),
    )


def _value_axis(title: str | None, field: str = "exposure_try", money: bool = True) -> alt.X:
    """Recessive quantitative x axis; compact numbers, with a ₺ prefix for money."""
    prefix = {"labelExpr": "'₺' + datum.label"} if money else {}
    axis = alt.Axis(format="~s", tickCount=5, gridDash=[2, 3], domain=False, ticks=False, **prefix)
    return alt.X(f"{field}:Q", title=title, axis=axis)


def _show(chart: alt.Chart) -> None:
    st.altair_chart(chart.configure_view(stroke=None), width="stretch")


def exposure_by_counterparty(split: pd.DataFrame, all_tenants: list[str]) -> None:
    """Horizontal bars, one per counterparty, stacked by the subsidiary carrying the exposure."""
    df = split.assign(subsidiary=split["tenant_id"].map(fmt.tenant_label),
                      amount=split["exposure_try"].map(fmt.money),
                      total=split["entity_total"].map(fmt.money))  # fmt: skip
    order = list(dict.fromkeys(df["canonical_name"]))
    labels = [fmt.tenant_label(t) for t in all_tenants]
    chart = (
        alt.Chart(df)
        .mark_bar(size=BAR_SIZE, stroke=theme.surface(), strokeWidth=2)
        .encode(
            y=alt.Y(
                "canonical_name:N",
                sort=order,
                title=None,
                axis=alt.Axis(labelLimit=280, domain=False, ticks=False),
            ),  # fmt: skip
            x=_value_axis("Approved exposure"),
            color=_tenant_color(all_tenants),
            order=alt.Order("tenant_rank:Q"),
            tooltip=[
                alt.Tooltip("canonical_name:N", title="Counterparty"),
                alt.Tooltip("subsidiary:N", title="Subsidiary"),
                alt.Tooltip("amount:N", title="Exposure"),
                alt.Tooltip("total:N", title="Counterparty total"),
            ],
        )
        .transform_calculate(tenant_rank=f"indexof({labels}, datum.subsidiary)")
        .properties(height=alt.Step(BAR_SIZE + 12))
    )
    _show(chart)


def exposure_by_tenant(df: pd.DataFrame, all_tenants: list[str]) -> None:
    df = df.assign(subsidiary=df["tenant_id"].map(fmt.tenant_label),
                   amount=df["exposure_try"].map(fmt.money))  # fmt: skip
    # Explicit order: a "-x" sort is dropped when bars and labels are layered.
    order = list(df.sort_values("exposure_try", ascending=False)["subsidiary"])
    y = alt.Y("subsidiary:N", sort=order, title=None, axis=alt.Axis(domain=False, ticks=False))
    base = alt.Chart(df).encode(y=y, x=_value_axis("Approved exposure"))
    bars = base.mark_bar(size=BAR_SIZE + 6, cornerRadiusEnd=4).encode(
        color=_tenant_color(all_tenants).legend(None),
        tooltip=[
            alt.Tooltip("subsidiary:N", title="Subsidiary"),
            alt.Tooltip("amount:N", title="Exposure"),
            alt.Tooltip("document_count:Q", title="Documents"),
        ],
    )
    # Direct value labels in text ink (never the series color); the y axis names each bar.
    labels = base.mark_text(align="left", dx=6, color=theme.text_secondary()).encode(
        text="amount:N"
    )
    _show(alt.layer(bars, labels).properties(height=alt.Step(BAR_SIZE + 18)))


def ranked_bar(df: pd.DataFrame, label: str, value: str, *, money: bool = False) -> None:
    """One series of horizontal bars, largest first, with direct value labels."""
    shown = fmt.money if money else (lambda v: f"{v:,.4g}")
    df = df.assign(
        _label=df[label].map(lambda v: fmt.tenant_label(str(v))), _text=df[value].map(shown)
    )
    order = list(df.sort_values(value, ascending=False)["_label"])
    base = alt.Chart(df).encode(
        y=alt.Y(
            "_label:N",
            sort=order,
            title=None,
            axis=alt.Axis(labelLimit=280, domain=False, ticks=False),
        ),
        x=_value_axis(None, value, money),
    )
    bars = base.mark_bar(size=BAR_SIZE, cornerRadiusEnd=4, color=theme.series()[0]).encode(
        tooltip=[alt.Tooltip("_label:N", title=label), alt.Tooltip("_text:N", title=value)]
    )
    labels = base.mark_text(align="left", dx=6, color=theme.text_secondary()).encode(text="_text:N")
    _show(alt.layer(bars, labels).properties(height=alt.Step(BAR_SIZE + 12)))
