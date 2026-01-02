
# --- FIXED: By Component (Tickets & Pages together) ---
st.subheader("By Component (Tickets & Pages)")

comp_sum = filtered.groupby("component")[["tickets", "pages"]].sum().reset_index()
comp_sum["component"] = comp_sum["component"].fillna("Unspecified")
comp_sum.loc[comp_sum["component"].eq(""), "component"] = "Unspecified"

# Melt for grouped bars
comp_long = comp_sum.melt(
    id_vars=["component"],
    value_vars=["tickets", "pages"],
    var_name="metric",
    value_name="value"
)

# Grouped bar chart (side-by-side bars)
grouped = alt.Chart(comp_long).mark_bar().encode(
    x=alt.X("component:N", title="Component", sort=comp_sum["component"].tolist()),
    y=alt.Y("value:Q", title="Count"),
    color=alt.Color("metric:N", title="Metric",
                    scale=alt.Scale(domain=["tickets", "pages"],
                                    range=["#4C78A8", "#2E8B57"])),
    tooltip=[
        alt.Tooltip("component:N", title="Component"),
        alt.Tooltip("metric:N", title="Metric"),
        alt.Tooltip("value:Q", title="Count")
    ]
).properties(height=400)

# Labels on bars
labels = alt.Chart(comp_long).mark_text(
    align="center", baseline="bottom", dy=-5, color="black"
).encode(
    x="component:N",
    y="value:Q",
    text="value:Q",
    color=alt.Color("metric:N", legend=None)
)

chart_comp = grouped + labels
st.altair_chart(chart_comp, width='stretch')  # Updated for Streamlit new API
