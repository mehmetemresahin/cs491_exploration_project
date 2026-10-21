"""Reusable UI building blocks for the Streamlit app.

- theme       colors per light/dark mode (mirrors .streamlit/config.toml)
- format      labels and number formatting shared by every page
- data        cached access to mock491.queries + writes
- components  page header, KPI row, status badge, tables, source viewer
- charts      Altair charts on the theme palette
- state       cross-page state: the subsidiary scope and the selected counterparty
"""
