
import streamlit as st
import pandas as pd
import altair as alt
from datetime import date, timedelta
from supabase import create_client

# =========================
# Page & Supabase Config
# =========================
st.set_page_config(layout="wide")

SUPABASE_URL = "https://vupalstqgfzwxwlvengp.supabase.co"   # TODO: replace if needed
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InZ1cGFsc3RxZ2Z6d3h3bHZlbmdwIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjcwMTI0MjIsImV4cCI6MjA4MjU4ODQyMn0.tQsnAFYleVlRldH_nYW3QGhMvEQaYVH0yXNpkJqtkBY"  # TODO: replace if needed
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# =========================
# Team → Table Mapping
# =========================
TEAM_TABLES = {
    "Merchandising": "merch",
    "Creative": "creative",
    "Ecom": "ecom",
    "Ecom Promo": "ecom_promo",
    "Email Marketing": "email_marketing",
}

# =========================
# Metrics & Styling
# =========================
# Canonical metrics and column synonyms (singular/plural)
METRIC_SYNONYMS = {
    "tickets": ["tickets", "ticket"],
    "banners": ["banners", "banner"],
    "skus": ["skus", "sku"],
    "pages": ["pages", "page"],
    "codes": ["codes", "code"],
}

# Colors per metric
METRIC_COLORS = {
    "tickets": "steelblue",
    "banners": "#9C27B0",  # purple
    "skus": "#FF8C00",     # orange
    "pages": "#2E7D32",    # green
    "codes": "#607D8B",    # blue-grey
}

# =========================
# Calendaring
# =========================
PUBLIC_HOLIDAYS = {
    date(2024, 12, 25),
    date(2025, 1, 1),
}
WORKDAY_HOURS = 8

# =========================
# Helper Functions
# =========================
def end_of_month(y: int, m: int) -> date:
    if m == 12:
        return date(y, 12, 31)
    return (date(y, m + 1, 1) - timedelta(days=1))

def working_days_between(start: date, end: date):
    days = pd.date_range(start, end, freq="D")
    return [d.normalize() for d in days if d.weekday() < 5 and d.date() not in PUBLIC_HOLIDAYS]

def fetch_team_df(team_display_name: str) -> pd.DataFrame:
    """Fetch data for the selected team and normalize columns."""
    table = TEAM_TABLES.get(team_display_name)
    if not table:
        return pd.DataFrame()

    try:
        response = supabase.table(table).select("*").execute()
        df = pd.DataFrame(response.data)
    except Exception as e:
        st.error(f"Error fetching data from '{table}': {e}")
        return pd.DataFrame()

    if df.empty:
        return df

    # Ensure/normalize core columns
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
    else:
        df["date"] = pd.NaT

    # Ensure 'week' exists
    if "week" not in df.columns or df["week"].isna().any():
        try:
            df["week"] = df["date"].dt.isocalendar().week
        except Exception:
            df["week"] = 0

    # Normalize member/component/duration/comments
    for col, default in [
        ("member", "Unspecified"),
        ("component", "Unspecified"),
        ("duration", 0),   # minutes
        ("comments", ""),  # FIX: use empty string instead of None
    ]:
        if col not in df.columns:
            df[col] = default
        # Avoid fillna(None) crash by ensuring default is not None
        df[col] = df[col].fillna(default)

    # Standardize blanks
    df["member"] = df["member"].replace("", "Unspecified")
    df["component"] = df["component"].replace("", "Unspecified")

    # Normalize metric columns to canonical names (create if missing as 0)
    for canonical, synonyms in METRIC_SYNONYMS.items():
        actual_col = None
        for syn in synonyms:
            if syn in df.columns:
                actual_col = syn
                break
        if actual_col is None:
            # Not present -> create as 0
            df[canonical] = 0
        else:
            df[canonical] = pd.to_numeric(df[actual_col], errors="coerce").fillna(0)

    # Ensure numeric types
    for col in ["tickets", "banners", "skus", "pages", "codes", "duration"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    df["team"] = team_display_name
    return df

def build_month_multi_options(df_dates: pd.Series):
    """
    Returns:
        options: list of month labels for multiselect including 'Current Month' and 'Previous Month'
        label_to_period: dict mapping label -> pd.Period('YYYY-MM')
        default_selection: sensible default list for the multiselect
    """
    today = date.today()
    current_period = pd.Period(f"{today.year}-{today.month:02d}")
    prev_month = today.month - 1 if today.month > 1 else 12
    prev_year = today.year if today.month > 1 else today.year - 1
    previous_period = pd.Period(f"{prev_year}-{prev_month:02d}")

    # Months present in data
    year_month = pd.to_datetime(df_dates, errors="coerce").dt.to_period("M")
    data_months = sorted([m for m in year_month.dropna().unique()])

    label_to_period = {}
    options = ["Current Month", "Previous Month"]
    label_to_period["Current Month"] = current_period
    label_to_period["Previous Month"] = previous_period

    for m in data_months:
        if (m != current_period) and (m != previous_period):
            label = m.strftime("%B %Y")
            options.append(label)
            label_to_period[label] = m

    default_selection = ["Current Month"]
    return options, label_to_period, default_selection

def filter_df_by_month_labels(df: pd.DataFrame, selected_labels, label_to_period):
    """Filter the dataframe by months selected in the multiselect."""
    if not selected_labels:
        return df.iloc[0:0]  # empty selection -> empty df
    df = df.copy()
    df["period"] = df["date"].dt.to_period("M")
    selected_periods = [label_to_period[lbl] for lbl in selected_labels if lbl in label_to_period]
    return df[df["period"].isin(selected_periods)].copy()

def get_workdays_for_selected_months(selected_labels, label_to_period):
    """Union of working days across selected months."""
    workdays = []
    for lbl in selected_labels:
        p = label_to_period.get(lbl)
        if not p:
            continue
        start = date(p.year, p.month, 1)
        end = end_of_month(p.year, p.month)
        workdays.extend(working_days_between(start, end))
    return sorted(list(set(workdays)))

def bar_with_labels(df, x_field, y_field, color,
                    x_type="O", y_type="Q", x_title="", y_title="", height=300):
    base = alt.Chart(df).mark_bar(color=color).encode(
        x=alt.X(f"{x_field}:{x_type}", title=x_title),
        y=alt.Y(f"{y_field}:{y_type}", title=y_title)
    ).properties(height=height)
    text = alt.Chart(df).mark_text(align="center", baseline="bottom", dy=-5, color="black").encode(
        x=f"{x_field}:{x_type}",
        y=f"{y_field}:{y_type}",
        text=f"{y_field}:{y_type}"
    )
    return base + text

# =========================
# UI: Tabs
# =========================
tab_visuals, tab_util = st.tabs([
    "📊 Visuals",
    "📈 Utilization & Occupancy"
])

# =========================
# TAB: Visuals
# =========================
with tab_visuals:
    st.title("Consolidated Manager View — Visuals")

    # --- Controls
    team_display = st.selectbox("Team", list(TEAM_TABLES.keys()), index=0, key="visuals_team")
    df = fetch_team_df(team_display)

    if df.empty:
        st.info("No data available for the selected team.")
    else:
        # Member dropdown
        members = sorted([m for m in df["member"].dropna().unique()])
        member_choice = st.selectbox("Member", ["All Members"] + members, index=0, key="visuals_member")

        # Month multi-select
        options, label_to_period, default_selection = build_month_multi_options(df["date"])
        selected_labels = st.multiselect("Months", options, default=default_selection, key="visuals_months")

        # --- Filter by months
        filtered = filter_df_by_month_labels(df, selected_labels, label_to_period)

        # Member filter
        if member_choice != "All Members":
            filtered = filtered[filtered["member"] == member_choice]

        if filtered.empty:
            st.info("No visuals for the selected filters.")
        else:
            # Identify which metric columns exist (non-empty across filtered set)
            present_metrics = []
            for canonical in METRIC_SYNONYMS.keys():
                if canonical in filtered.columns and pd.to_numeric(filtered[canonical], errors="coerce").fillna(0).sum() > 0:
                    present_metrics.append(canonical)
            # If all zeros but columns exist, still show charts (use the columns that exist)
            if not present_metrics:
                present_metrics = [m for m in METRIC_SYNONYMS.keys() if m in filtered.columns]

            # --- Week-wise charts for each present metric
            st.subheader("By Week")
            cols = st.columns(2)
            for idx, metric in enumerate(present_metrics):
                wk = filtered.groupby("week", dropna=False)[[metric]].sum().reset_index().sort_values("week")
                with cols[idx % 2]:
                    pretty = metric.capitalize()
                    chart = bar_with_labels(
                        wk, "week", metric, METRIC_COLORS.get(metric, "steelblue"),
                        x_type="O", y_type="Q", x_title="Week", y_title=pretty
                    )
                    st.altair_chart(chart, use_container_width=True)

            # --- By Component: sum of present metrics, with per-metric tooltips
            st.subheader("By Component (Total of present metrics)")
            agg_map = {metric: (metric, "sum") for metric in present_metrics}
            if not agg_map:
                st.info("No measurable metrics found for this team.")
            else:
                comp_grouped = filtered.groupby("component", dropna=False).agg(**agg_map).reset_index()
                comp_grouped["component"] = comp_grouped["component"].fillna("Unspecified")
                comp_grouped.loc[comp_grouped["component"].eq(""), "component"] = "Unspecified"

                # Numeric safety
                for metric in present_metrics:
                    comp_grouped[metric] = pd.to_numeric(comp_grouped[metric], errors="coerce").fillna(0)

                comp_grouped["total"] = comp_grouped[present_metrics].sum(axis=1)
                comp_grouped = comp_grouped.sort_values("total", ascending=False)

                bar = alt.Chart(comp_grouped).mark_bar(color="#4C78A8").encode(
                    x=alt.X("component:N", title="Component",
                            sort=alt.SortField(field="total", order="descending")),
                    y=alt.Y("total:Q", title="Total")
                ).properties(height=400)

                text = alt.Chart(comp_grouped).mark_text(align="center", baseline="bottom", dy=-5, color="black").encode(
                    x=alt.X("component:N", sort=alt.SortField(field="total", order="descending")),
                    y=alt.Y("total:Q"),
                    text=alt.Text("total:Q")
                )

                # Dynamic tooltips include each present metric
                tooltip_fields = [alt.Tooltip("component:N", title="Component")]
                for metric in present_metrics:
                    pretty = metric.capitalize()
                    tooltip_fields.append(alt.Tooltip(f"{metric}:Q", title=pretty))
                tooltip_fields.append(alt.Tooltip("total:Q", title="Total"))

                chart = (bar + text).encode(tooltip=tooltip_fields)
                st.altair_chart(chart, use_container_width=True)

# =========================
# TAB: Utilization & Occupancy
# =========================
with tab_util:
    st.title("Consolidated Manager View — Utilization & Occupancy")

    # --- Controls
    team_display_u = st.selectbox("Team", list(TEAM_TABLES.keys()), index=0, key="util_team")
    df_u = fetch_team_df(team_display_u)

    if df_u.empty:
        st.info("No data available for the selected team.")
    else:
        members_u = sorted([m for m in df_u["member"].dropna().unique()])
        member_choice_u = st.selectbox("Member", ["All Members"] + members_u, index=0, key="util_member")

        options_u, label_to_period_u, default_selection_u = build_month_multi_options(df_u["date"])
        selected_labels_u = st.multiselect("Months", options_u, default=default_selection_u, key="util_months")

        # --- Baseline working days & filtered data
        weekdays_u = get_workdays_for_selected_months(selected_labels_u, label_to_period_u)
        if not weekdays_u:
            st.info("No working days found for the selected months.")
        else:
            df_u["date_norm"] = df_u["date"].dt.normalize()
            period_df = df_u[df_u["date_norm"].isin(weekdays_u)].copy()

            # Member filter
            if member_choice_u != "All Members":
                period_df = period_df[period_df["member"] == member_choice_u]

            if period_df.empty:
                st.info("No data for the selected filters.")
            else:
                # Derived hour views
                period_df["hours"] = pd.to_numeric(period_df["duration"], errors="coerce").fillna(0) / 60.0
                period_df["utilization_hours"] = period_df.apply(
                    lambda r: 0 if r["component"] in ["Break", "Leave"] else r["hours"], axis=1
                )
                period_df["occupancy_hours"] = period_df.apply(
                    lambda r: 0 if r["component"] in ["Break", "Leave", "Meeting"] else r["hours"], axis=1
                )
                period_df["leave_hours"] = period_df.apply(
                    lambda r: r["hours"] if r["component"] == "Leave" else 0, axis=1
                )

                baseline_hours_period = len(weekdays_u) * WORKDAY_HOURS

                # Member-level aggregation
                agg = period_df.groupby("member").agg(
                    utilized_hours=("utilization_hours", "sum"),
                    occupied_hours=("occupancy_hours", "sum"),
                    leave_hours=("leave_hours", "sum")
                ).reset_index()

                agg["total_hours"] = baseline_hours_period - agg["leave_hours"]

                # Percentages
                agg["utilization_%"] = (
                    (agg["utilized_hours"] / agg["total_hours"]).where(agg["total_hours"] > 0, 0) * 100
                ).round(1)
                agg["occupancy_%"] = (
                    (agg["occupied_hours"] / agg["total_hours"]).where(agg["total_hours"] > 0, 0) * 100
                ).round(1)

                # Rounding & labeling
                agg["utilized_hours"] = agg["utilized_hours"].round(1)
                agg["occupied_hours"] = agg["occupied_hours"].round(1)
                agg["leave_hours"] = agg["leave_hours"].round(1)
                agg["total_hours"] = agg["total_hours"].round(1)

                merged_stats = agg.rename(columns={
                    "member": "Name",
                    "total_hours": "Total Hours",
                    "leave_hours": "Leave Hours",
                    "utilized_hours": "Utilized Hours",
                    "occupied_hours": "Occupied Hours",
                    "utilization_%": "Utilization %",
                    "occupancy_%": "Occupancy %"
                })

                # Show only selected member if not All
                if member_choice_u != "All Members":
                    merged_stats = merged_stats[merged_stats["Name"] == member_choice_u]

                st.subheader("Member Utilization & Occupancy")
                st.dataframe(
                    merged_stats[["Name", "Total Hours", "Leave Hours", "Utilized Hours", "Occupied Hours", "Utilization %", "Occupancy %"]],
                    use_container_width=True
                )

                # Team totals (across filtered set)
                team_total = float(merged_stats["Total Hours"].sum())
                team_leave = float(merged_stats["Leave Hours"].sum())
                team_utilized = float(merged_stats["Utilized Hours"].sum())
                team_occupied = float(merged_stats["Occupied Hours"].sum())

                team_util_pct = (team_utilized / team_total * 100) if team_total > 0 else 0.0
                team_occ_pct = (team_occupied / team_total * 100) if team_total > 0 else 0.0

                team_df = pd.DataFrame({
                    "Team": [team_display_u],
                    "Total Hours": [round(team_total, 1)],
                    "Leave Hours": [round(team_leave, 1)],
                    "Utilized Hours": [round(team_utilized, 1)],
                    "Occupied Hours": [round(team_occupied, 1)],
                    "Utilization %": [round(team_util_pct, 1)],
                    "Occupancy %": [round(team_occ_pct, 1)]
                })

                st.subheader("Team Utilization & Occupancy")
                st.dataframe(team_df, use_container_width=True)

                # Utilization by Component × Member
                st.subheader("Utilization by Component × Member")
                util_df = period_df[~period_df["component"].isin(["Break", "Leave"])].copy()

                comp_member_minutes = util_df.groupby(["component", "member"])["duration"].sum().reset_index()
                comp_member_minutes["hours"] = comp_member_minutes["duration"] / 60.0

                comp_member_minutes["component"] = comp_member_minutes["component"].fillna("Unspecified")
                comp_member_minutes.loc[comp_member_minutes["component"].eq(""), "component"] = "Unspecified"

                member_totals_minutes = period_df.groupby("member")["duration"].sum()
                member_totals_hours = (member_totals_minutes / 60.0).to_dict()

                comp_member_minutes["pct_of_member"] = comp_member_minutes.apply(
                    lambda r: ((r["hours"] / member_totals_hours.get(r["member"], 0)) * 100)
                    if member_totals_hours.get(r["member"], 0) > 0 else 0.0,
                    axis=1
                )

                comp_member_minutes["cell"] = comp_member_minutes.apply(
                    lambda r: f"{r['hours']:.1f}h ({r['pct_of_member']:.1f}%)",
                    axis=1
                )

                pivot = comp_member_minutes.pivot(index="component", columns="member", values="cell").fillna("0.0h (0.0%)")

                comp_order = (
                    comp_member_minutes.groupby("component")["hours"]
                    .sum()
                    .sort_values(ascending=False)
                    .index
                )
                pivot = pivot.loc[comp_order]

                # If a single member is selected, show only that column
                if member_choice_u != "All Members":
                    cols_to_show = [member_choice_u] if member_choice_u in pivot.columns else []
                else:
                    cols_to_show = list(pivot.columns)

                if not cols_to_show:
                    st.info("No utilization entries for the selected filters.")
                else:
                    st.dataframe(pivot[cols_to_show], use_container_width=True)
