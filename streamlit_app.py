"""China population dashboard entry point."""
from __future__ import annotations

import altair as alt
import streamlit as st

from dashboard.charts import (
    COLOR_THEMES,
    make_donut,
    make_heatmap,
    make_trend,
)
from dashboard.choropleth import make_choropleth
from dashboard.data import (
    MIGRATION_THRESHOLD,
    DataValidationError,
    build_download_dataframe,
    calculate_migration_counts,
    calculate_population_difference,
    dataframe_to_utf8_csv,
    filter_by_provinces,
    get_province_options,
    get_trend_data,
    get_year_list,
    load_dashboard_data,
)
from dashboard.formatting import format_number

st.set_page_config(
    page_title="中国人口仪表盘",
    page_icon="👥",
    layout="wide",
    initial_sidebar_state="expanded",
)

alt.theme.enable("dark")

st.markdown(
    """
<style>
[data-testid="block-container"] {
    padding-left: 2rem;
    padding-right: 2rem;
    padding-top: 1rem;
    padding-bottom: 0rem;
    margin-bottom: -7rem;
}

[data-testid="stVerticalBlock"] {
    padding-left: 0rem;
    padding-right: 0rem;
}

[data-testid="stMetric"] {
    background-color: #393939;
    text-align: center;
    padding: 15px 0;
}

[data-testid="stMetricLabel"] {
    display: flex;
    justify-content: center;
    align-items: center;
}

[data-testid="stMetricDeltaIcon-Up"] {
    position: relative;
    left: 38%;
    transform: translateX(-50%);
}

[data-testid="stMetricDeltaIcon-Down"] {
    position: relative;
    left: 38%;
    transform: translateX(-50%);
}

[data-testid="stDownloadButton"] button {
    width: 100%;
}
</style>
""",
    unsafe_allow_html=True,
)

try:
    dataset, province_mapping, china_geojson = load_dashboard_data()
except DataValidationError as exc:
    st.error(f"数据校验失败：{exc}")
    st.stop()

with st.sidebar:
    st.title("👥 中国人口仪表盘")
    st.caption("2010–2023 · 31 个大陆省级行政区")
    st.divider()

    year_list = get_year_list(dataset)
    selected_year = st.selectbox("选择年份", year_list)

    province_options = get_province_options(province_mapping)
    selected_provinces = st.multiselect(
        "省份（可搜索、多选）",
        options=province_options,
        default=province_options,
    )
    if len(selected_provinces) == 1:
        st.caption("已选择单个省份，主面板下方将显示历年趋势。")

    selected_color_theme = st.selectbox("选择配色主题", COLOR_THEMES)
    st.divider()

if not selected_provinces:
    st.warning("请至少选择一个省份。")
    st.stop()

selected_codes = province_mapping.loc[
    province_mapping["provinces"].isin(selected_provinces), "provinces_code"
].tolist()

year_data = dataset[dataset["year"] == selected_year]
year_data = filter_by_provinces(year_data, selected_codes).sort_values(
    "population", ascending=False
)
yoy_all = calculate_population_difference(dataset, selected_year)
yoy_selected = yoy_all[yoy_all["provinces_code"].isin(selected_codes)].copy()
heatmap_data = filter_by_provinces(dataset, selected_codes)

download_data = build_download_dataframe(year_data, yoy_selected)
with st.sidebar:
    st.download_button(
        "下载当前筛选数据 CSV",
        data=dataframe_to_utf8_csv(download_data),
        file_name=f"china-population-{selected_year}.csv",
        mime="text/csv",
    )
    st.caption("下载内容为当前年份和已选省份。")

col = st.columns((1.5, 4.5, 2), gap="medium")

with col[0]:
    st.markdown("#### 增长 / 减少")
    has_previous_year = selected_year > min(year_list)
    valid_differences = yoy_selected.dropna(subset=["population_difference"])

    if has_previous_year and not valid_differences.empty:
        sorted_differences = valid_differences.sort_values(
            "population_difference", ascending=False
        )
        largest = sorted_differences.iloc[0]
        smallest = sorted_differences.iloc[-1]
        st.metric(
            label=largest["provinces"],
            value=format_number(largest["population"]),
            delta=format_number(largest["population_difference"]),
        )
        st.metric(
            label=smallest["provinces"],
            value=format_number(smallest["population"]),
            delta=format_number(smallest["population_difference"]),
        )
    else:
        st.metric(label="-", value="-")
        st.metric(label="-", value="-")
        st.caption("2010 年没有上年数据，无法计算同比。")

    st.markdown("#### 省份迁移")

    if has_previous_year and not valid_differences.empty:
        inbound_count, outbound_count = calculate_migration_counts(valid_differences)
        denominator = len(selected_codes)
        inbound_percent = round(inbound_count / denominator * 100)
        outbound_percent = round(outbound_count / denominator * 100)
    else:
        inbound_percent = 0
        outbound_percent = 0

    donut_inbound = make_donut(inbound_percent, "净增省份", "green")
    donut_outbound = make_donut(outbound_percent, "净减省份", "red")
    migration_col = st.columns((0.2, 1, 0.2))
    with migration_col[1]:
        st.write("净增省份占比")
        st.altair_chart(donut_inbound)
        st.write("净减省份占比")
        st.altair_chart(donut_outbound)
    st.caption(
        f"阈值为同比变化 {format_number(MIGRATION_THRESHOLD)}；常住人口变化不等同于户籍迁移统计。"
    )

with col[1]:
    st.markdown("#### 总人口")
    choropleth = make_choropleth(
        year_data,
        "provinces_code",
        "population",
        selected_color_theme,
        china_geojson,
    )
    st.markdown(choropleth, unsafe_allow_html=True)
    st.caption("地图覆盖 31 个大陆省级行政区，不含港澳台；GeoJSON 本地渲染，仅用于统计可视化。")

    st.markdown("##### 年份 × 省份人口")
    heatmap = make_heatmap(
        heatmap_data,
        "year",
        "provinces",
        "population",
        selected_color_theme,
    )
    st.altair_chart(heatmap, use_container_width=True)

with col[2]:
    st.markdown("#### 省份人口排名")
    st.dataframe(
        year_data,
        column_order=("provinces", "population"),
        hide_index=True,
        column_config={
            "provinces": st.column_config.TextColumn("省份"),
            "population": st.column_config.ProgressColumn(
                "人口",
                format="%d",
                min_value=0,
                max_value=int(year_data["population"].max()),
            ),
        },
    )

    with st.expander("关于项目", expanded=True):
        st.markdown(
            """
- 数据：国家统计局《中国统计年鉴》分地区年末人口数，2010–2023 年，单位“人”。
- 范围：31 个大陆省级行政区，不含港澳台。
- 2010 年数据来自《中国统计年鉴 2020》，2011–2020 年使用《中国统计年鉴 2021》七普后修订序列，2021–2023 年来自《中国统计年鉴 2024》。
- :orange[**增长 / 减少**]：所选省份中同比人口变化最大和最小的两个省份。
- :orange[**省份迁移**]：同比人口变化超过 ±20 万人的省份占比，仅作为人口净变化的近似观察。
- 地图底图：阿里云 DataV.GeoAtlas 省级 GeoJSON（随仓库打包，离线渲染），仅用于数据可视化，不作为行政区划或边界依据。
- 原项目：[dataprofessor/population-dashboard][upstream]
- 本项目基于原项目 fork 改造；原作者为 Chanin Nantasenamat（dataprofessor）。

[upstream]: https://github.com/dataprofessor/population-dashboard
"""
        )

if len(selected_provinces) == 1:
    selected_code = selected_codes[0]
    selected_name = selected_provinces[0]
    st.markdown(f"#### {selected_name}历年人口趋势")
    trend_data = get_trend_data(dataset, selected_code)
    trend = make_trend(trend_data, selected_color_theme)
    st.altair_chart(trend, use_container_width=True)
    st.caption("数据为年末常住人口，2010–2023 年。")
