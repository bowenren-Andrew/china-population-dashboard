"""Tests for data transformations, GeoJSON mapping, charts, and formatting."""
from __future__ import annotations

import unittest

import altair as alt
import pandas as pd

from dashboard.charts import COLOR_THEMES, make_donut, make_heatmap, make_trend
from dashboard.choropleth import make_choropleth
from dashboard.data import (
    DataValidationError,
    MIGRATION_THRESHOLD,
    build_download_dataframe,
    calculate_migration_counts,
    calculate_population_difference,
    dataframe_to_utf8_csv,
    filter_by_provinces,
    get_trend_data,
    load_dashboard_data,
    validate_population_data,
)
from dashboard.formatting import format_number


class DashboardDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dataset, cls.mapping, cls.geojson = load_dashboard_data()

    def test_dataset_contract(self) -> None:
        self.assertEqual(self.dataset.shape, (434, 6))
        self.assertEqual(
            list(self.dataset.columns),
            ["year", "provinces", "provinces_code", "population", "id", "provinces_full"],
        )
        self.assertEqual(sorted(self.dataset["year"].unique()), list(range(2010, 2024)))
        self.assertTrue(self.dataset.groupby("year").size().eq(31).all())
        self.assertTrue(self.dataset["population"].gt(0).all())
        self.assertTrue(self.dataset["population"].mod(10_000).eq(0).all())

    def test_invalid_dataset_is_rejected(self) -> None:
        broken = self.dataset.drop(index=0).drop(columns=["provinces_full"])
        with self.assertRaises(DataValidationError):
            validate_population_data(broken)

    def test_geojson_has_all_provinces(self) -> None:
        features = self.geojson["features"]
        self.assertEqual(len(features), 31)
        feature_codes = {feature["properties"]["adcode"] for feature in features}
        self.assertEqual(feature_codes, set(self.mapping["provinces_code"]))
        self.assertTrue(all(isinstance(code, str) for code in feature_codes))

    def test_year_over_year_values(self) -> None:
        yoy_2011 = calculate_population_difference(self.dataset, 2011)
        beijing = yoy_2011.loc[yoy_2011["provinces_code"] == "110000"].iloc[0]
        self.assertEqual(int(beijing["population_difference"]), 620_000)

        yoy_2023 = calculate_population_difference(self.dataset, 2023)
        guangdong = yoy_2023.loc[yoy_2023["provinces_code"] == "440000"].iloc[0]
        self.assertEqual(int(guangdong["population_difference"]), 490_000)

    def test_2010_has_no_previous_year(self) -> None:
        yoy_2010 = calculate_population_difference(self.dataset, 2010)
        self.assertTrue(yoy_2010["population_difference"].isna().all())

    def test_migration_threshold_counts(self) -> None:
        self.assertEqual(MIGRATION_THRESHOLD, 200_000)
        yoy_2023 = calculate_population_difference(self.dataset, 2023)
        self.assertEqual(calculate_migration_counts(yoy_2023), (2, 7))
        yoy_2010 = calculate_population_difference(self.dataset, 2010)
        self.assertEqual(calculate_migration_counts(yoy_2010), (0, 0))

    def test_filter_and_trend(self) -> None:
        filtered = filter_by_provinces(self.dataset, ["110000", "440000"])
        self.assertEqual(len(filtered), 28)
        self.assertEqual(filtered["provinces_code"].nunique(), 2)

        trend = get_trend_data(self.dataset, "440000")
        self.assertEqual(trend["year"].tolist(), list(range(2010, 2024)))
        self.assertEqual(len(trend), 14)

    def test_download_dataframe(self) -> None:
        year_data = self.dataset[self.dataset["year"] == 2023]
        yoy_data = calculate_population_difference(self.dataset, 2023)
        download = build_download_dataframe(year_data, yoy_data)
        self.assertEqual(
            list(download.columns),
            ["年份", "省份", "省份全名", "区划代码", "人口", "同比变化"],
        )
        self.assertEqual(len(download), 31)
        self.assertTrue(download["人口"].is_monotonic_decreasing)

        csv_bytes = dataframe_to_utf8_csv(download)
        self.assertTrue(csv_bytes.startswith(b"\xef\xbb\xbf"))
        self.assertIn("广东", csv_bytes.decode("utf-8-sig"))


class ChartTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dataset, cls.mapping, cls.geojson = load_dashboard_data()

    def test_heatmap_uses_filtered_data(self) -> None:
        filtered = filter_by_provinces(self.dataset, ["110000", "440000"])
        chart = make_heatmap(filtered, "year", "provinces", "population", "blues")
        self.assertIsInstance(chart, alt.Chart)
        spec = chart.to_dict()
        values = spec["datasets"][spec["data"]["name"]]
        self.assertEqual(len(values), 28)

    def test_choropleth_uses_local_geojson(self) -> None:
        year_data = self.dataset[self.dataset["year"] == 2023]
        svg = make_choropleth(
            year_data,
            "provinces_code",
            "population",
            "viridis",
            self.geojson,
        )
        self.assertIsInstance(svg, str)
        self.assertIn('aria-label="中国省级人口分布地图"', svg)
        self.assertEqual(svg.count('<path class="province'), 31)
        self.assertEqual(svg.count('province-selected'), 31)
        self.assertIn('data-code="110000"', svg)
        self.assertIn('data-state="已选择"', svg)
        self.assertIn("1.27 亿", svg)

    def test_choropleth_marks_unselected_provinces(self) -> None:
        year_data = self.dataset[self.dataset["year"] == 2023]
        filtered = filter_by_provinces(year_data, ["110000", "440000"])
        svg = make_choropleth(
            filtered,
            "provinces_code",
            "population",
            "blues",
            self.geojson,
        )
        self.assertEqual(svg.count('<path class="province'), 31)
        self.assertEqual(svg.count('province-selected'), 2)
        self.assertEqual(svg.count('data-state="未选择"'), 29)

    def test_choropleth_rejects_empty_input(self) -> None:
        year_data = self.dataset[self.dataset["year"] == 2023].iloc[0:0]
        with self.assertRaises(ValueError):
            make_choropleth(
                year_data,
                "provinces_code",
                "population",
                "blues",
                self.geojson,
            )

    def test_all_color_themes_build(self) -> None:
        year_data = self.dataset[self.dataset["year"] == 2023]
        for theme in COLOR_THEMES:
            with self.subTest(theme=theme):
                svg = make_choropleth(
                    year_data,
                    "provinces_code",
                    "population",
                    theme,
                    self.geojson,
                )
                self.assertEqual(svg.count('<path class="province'), 31)

    def test_donut_and_trend_charts(self) -> None:
        donut = make_donut(23, "净增省份", "green")
        self.assertIsInstance(donut, alt.LayerChart)
        self.assertEqual(len(donut.to_dict()["layer"]), 3)

        trend_data = get_trend_data(self.dataset, "440000")
        trend = make_trend(trend_data, "turbo")
        self.assertIsInstance(trend, alt.Chart)
        self.assertEqual(trend.to_dict()["encoding"]["x"]["field"], "year")
        self.assertEqual(trend.to_dict()["encoding"]["y"]["field"], "population")


class FormattingTests(unittest.TestCase):
    def test_chinese_units(self) -> None:
        self.assertEqual(format_number(19_620_000), "1,962 万")
        self.assertEqual(format_number(141_260_000), "1.41 亿")
        self.assertEqual(format_number(-2_290_000), "-229 万")
        self.assertEqual(format_number(9_000), "9,000 人")


if __name__ == "__main__":
    unittest.main()
