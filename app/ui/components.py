"""Page building blocks. Pages compose these; they hold no queries of their own."""

from dataclasses import dataclass
from datetime import datetime

import pandas as pd
import streamlit as st

from ui import data, theme
from ui import format as fmt

# Standard column definitions: any table showing one of these columns gets the same header and
# formatting. Pages pick columns by name and may override a definition per table.
COLUMNS = {
    "canonical_name": st.column_config.TextColumn("Counterparty", width="medium"),
    "counterparty_name": st.column_config.TextColumn("Counterparty (as written)", width="medium"),
    "matched_entity": st.column_config.TextColumn("Matched to", width="medium"),
    "name_as_written": st.column_config.TextColumn("Written as", width="medium"),
    "vkn": st.column_config.TextColumn("VKN"),
    "counterparty_vkn": st.column_config.TextColumn("VKN"),
    "vkn_as_written": st.column_config.TextColumn("VKN as written"),
    "tenant_id": st.column_config.TextColumn("Subsidiary"),
    "tenants": st.column_config.ListColumn("Subsidiaries", width="medium"),
    "tenant_count": st.column_config.NumberColumn("Subs.", help="Subsidiaries that use it"),
    "document_count": st.column_config.NumberColumn("Docs"),
    "spellings": st.column_config.NumberColumn("Spellings"),
    "exposure_try": st.column_config.NumberColumn("Exposure ₺", format="compact"),
    "amount_try": st.column_config.NumberColumn("Amount ₺", format="compact",
                                                help="Converted at the mock FX rates"),
    "amount": st.column_config.NumberColumn("Amount", format="localized"),
    "currency": st.column_config.TextColumn("Cur."),
    "max_penalty_rate_daily": st.column_config.NumberColumn("Max penalty/day", format="percent"),
    "penalty_rate_daily": st.column_config.NumberColumn("Penalty/day", format="percent"),
    "confidence": st.column_config.ProgressColumn("Confidence", min_value=0.0, max_value=1.0,
                                                  format="%.2f"),
    "issues": st.column_config.ListColumn("Reason"),
    "status": st.column_config.TextColumn("Status"),
    "doc_type": st.column_config.TextColumn("Type"),
    "document_ref": st.column_config.TextColumn("Document"),
    "document_date": st.column_config.DateColumn("Date", format="DD.MM.YYYY"),
    "paid": st.column_config.CheckboxColumn("Paid"),
    "n": st.column_config.NumberColumn("Records"),
    # names used by the Text-to-SQL tables (mock491.genbi.catalog)
    "counterparty": st.column_config.TextColumn("Counterparty", width="medium"),
    "subsidiary_count": st.column_config.NumberColumn("Subs.", help="Subsidiaries that use it"),
    "counterparty_count": st.column_config.NumberColumn("Counterparties"),
    "reasons": st.column_config.TextColumn("Reason"),
}  # fmt: skip

# Raw values -> display labels, applied to any table that shows these columns.
_DISPLAY = {
    "tenant_id": fmt.tenant_label,
    "tenants": lambda ts: [fmt.tenant_label(t) for t in ts],
    "status": fmt.status_label,
    "issues": lambda xs: [fmt.issue_label(x) for x in xs],
    "doc_type": lambda d: fmt.DOC_TYPES.get(d, d),
}


def table(df: pd.DataFrame, columns: list[str], *, key: str | None = None, select: bool = False,
          height: int | str = "auto", overrides: dict | None = None):  # fmt: skip
    """A formatted, read-only table of `columns` (in order). With `select`, rows are clickable
    and the selection event is returned (see `selected_row`)."""
    view = df[columns].copy()
    for col, to_label in _DISPLAY.items():
        if col in view:
            view[col] = view[col].map(to_label, na_action="ignore")
    return st.dataframe(
        view,
        # Only known columns get a config: a None config would hide the column.
        column_config={c: COLUMNS[c] for c in columns if c in COLUMNS} | (overrides or {}),
        hide_index=True,
        width="stretch",
        height=height,
        key=key,
        on_select="rerun" if select else "ignore",
        selection_mode="single-row",
    )


def selected_row(event, df: pd.DataFrame) -> pd.Series | None:
    rows = event.selection.rows if event is not None else []
    return df.iloc[rows[0]] if rows and rows[0] < len(df) else None


def page_header(title: str, subtitle: str) -> None:
    st.title(title)
    st.caption(subtitle)


@dataclass
class Kpi:
    label: str
    value: str
    help: str | None = None


def kpi_row(items: list[Kpi]) -> None:
    for col, k in zip(st.columns(len(items)), items, strict=True):
        col.metric(k.label, k.value, help=k.help, border=True)


def status_badge(status: str, count: int | None = None) -> str:
    """Inline markdown badge (icon + label, optional count) for use inside st.markdown."""
    label, color, icon = fmt.STATUS.get(status, (status, "gray", ""))
    return f":{color}-badge[{icon} {label}{'' if count is None else f': {count}'}]"


def tenant_badges(tenants: list[str]) -> None:
    st.markdown(" ".join(f":gray-badge[{fmt.tenant_label(t)}]" for t in tenants))


def empty_state(title: str, hint: str, icon: str = ":material/inbox:") -> None:
    with st.container(border=True):
        st.markdown(f"#### {icon} {title}")
        st.caption(hint)


def field_grid(fields: dict[str, str], columns: int = 3) -> None:
    """Label/value pairs in a compact grid (e.g. the fields an extractor read)."""
    cols = st.columns(columns)
    for i, (label, value) in enumerate(fields.items()):
        with cols[i % columns]:
            st.caption(label)
            st.markdown(f"**{value}**" if value else "–")


def _cell(value) -> str:
    """Spreadsheet cell as a person would read it: dates as dd.mm.yyyy, empty cells blank."""
    if value is None or value != value:
        return ""
    return f"{value:%d.%m.%Y}" if isinstance(value, datetime) else str(value)


def source_viewer(src: dict, *, show_full_page: bool = False) -> None:
    """Lineage view: open the bronze file exactly where this value was read."""
    page, row = src.get("page_number"), src.get("row_number")
    where = f"page {page}" if page else f"row {row}"
    st.markdown(f":material/description: **{src['original_name']}** · {where}")
    if page:
        bbox = tuple(src["bounding_box"]) if src.get("bounding_box") is not None else None
        if bbox:
            st.image(data.pdf_image(src["uri"], page, bbox, crop_margin=40), width="stretch",
                     caption="The clause the values were read from")  # fmt: skip
        with st.expander("Full page", expanded=show_full_page or not bbox):
            st.image(data.pdf_image(src["uri"], page, bbox), width="stretch")
    else:
        rows = data.sheet(src["uri"])
        window = rows.loc[max(2, row - 3) : row + 3].map(_cell)  # as text: st.dataframe shows None
        highlight = theme.highlight_row()
        styled = window.style.apply(
            lambda r: [f"background-color: {highlight}" if r.name == row else ""] * len(r), axis=1
        )
        st.dataframe(styled, width="stretch")
        st.caption(f"Rows {window.index.min()}–{window.index.max()} of {rows.index.max()} "
                   "in the spreadsheet; the highlighted row is the one read.")  # fmt: skip
