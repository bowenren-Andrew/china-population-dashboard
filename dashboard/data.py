"""Data loading, validation, filtering, and export helpers for the dashboard."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data"
DATASET_PATH = DATA_DIR / "china-population-2010-2023-reshaped.csv"
PROVINCE_MAP_PATH = DATA_DIR / "china-provinces.csv"
GEOJSON_PATH = DATA_DIR / "china-provinces.geojson"

EXPECTED_COLUMNS = ["year", "provinces", "provinces_code", "population", "id"]
EXPECTED_YEARS = tuple(range(2010, 2024))
EXPECTED_PROVINCE_COUNT = 31
EXPECTED_ROW_COUNT = len(EXPECTED_YEARS) * EXPECTED_PROVINCE_COUNT

# 200k is close to the median absolute annual provincial change (180k),
# and is a round threshold for the 2010-2023 resident-population series.
MIGRATION_THRESHOLD = 200_000


class DataValidationError(ValueError):
    """Raised when dashboard input data violates its contract."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DataValidationError(message)


def load_province_mapping() -> pd.DataFrame:
    mapping = pd.read_csv(
        PROVINCE_MAP_PATH,
        dtype={"provinces_code": str, "id": int},
        encoding="utf-8",
    )
    expected_columns = ["provinces", "provinces_full", "provinces_code", "id"]
    _require(list(mapping.columns) == expected_columns, "省份映射字段错误")
    _require(len(mapping) == EXPECTED_PROVINCE_COUNT, "省份映射必须为31行")
    _require(mapping["provinces_code"].nunique() == EXPECTED_PROVINCE_COUNT, "省份代码必须唯一")
    _require(mapping["provinces"].nunique() == EXPECTED_PROVINCE_COUNT, "省份短名必须唯一")
    _require(mapping["provinces_code"].str.fullmatch(r"\d{6}").all(), "区划代码必须为6位数字")
    _require(sorted(mapping["id"].tolist()) == list(range(1, 32)), "省份 id 必须为1-31")
    return mapping.sort_values("id").reset_index(drop=True)


def load_population_data() -> pd.DataFrame:
    dataset = pd.read_csv(
        DATASET_PATH,
        dtype={"provinces_code": str},
        encoding="utf-8",
    )
    validate_population_data(dataset)
    mapping = load_province_mapping()
    enriched = dataset.merge(
        mapping[["provinces_code", "provinces_full"]],
        on="provinces_code",
        how="left",
        validate="many_to_one",
    )
    _require(enriched["provinces_full"].notna().all(), "存在无法映射全名的省份")
    return enriched.sort_values(["year", "id"]).reset_index(drop=True)


def validate_population_data(dataset: pd.DataFrame) -> None:
    _require(list(dataset.columns) == EXPECTED_COLUMNS, "人口数据字段错误")
    _require(len(dataset) == EXPECTED_ROW_COUNT, f"人口数据应为{EXPECTED_ROW_COUNT}行")
    _require(not dataset.isna().any().any(), "人口数据存在空值")

    for column in ("year", "population", "id"):
        _require(pd.api.types.is_integer_dtype(dataset[column]), f"{column} 必须为整数")
    _require(dataset["year"].isin(EXPECTED_YEARS).all(), "年份超出2010-2023")
    _require(dataset["population"].gt(0).all(), "人口必须为正数")
    _require(dataset["population"].mod(10_000).eq(0).all(), "人口必须为1万人的整数倍")
    _require(dataset["provinces_code"].str.fullmatch(r"\d{6}").all(), "区划代码格式错误")
    _require(
        not dataset.duplicated(["year", "provinces_code"]).any(),
        "存在重复的年份-省份记录",
    )
    _require(
        dataset.groupby("year").size().eq(EXPECTED_PROVINCE_COUNT).all(),
        "每年必须恰好31个省份",
    )
    _require(
        dataset.groupby("year")["provinces_code"].nunique().eq(EXPECTED_PROVINCE_COUNT).all(),
        "每年省份代码必须唯一且完整",
    )
    _require(
        dataset.groupby("provinces_code").size().eq(len(EXPECTED_YEARS)).all(),
        "每个省份必须覆盖全部年份",
    )
    _require(dataset["id"].nunique() == EXPECTED_PROVINCE_COUNT, "省份 id 必须唯一")

    mapping = pd.read_csv(
        PROVINCE_MAP_PATH,
        dtype={"provinces_code": str, "id": int},
        encoding="utf-8",
    )
    expected = set(mapping["provinces_code"])
    _require(set(dataset["provinces_code"]) == expected, "人口数据省份集合与映射不一致")
    code_to_name = dict(zip(mapping["provinces_code"], mapping["provinces"]))
    name_matches = [
        name == code_to_name[code]
        for code, name in zip(dataset["provinces_code"], dataset["provinces"])
    ]
    _require(all(name_matches), "省份名与区划代码不匹配")


def load_geojson() -> dict[str, Any]:
    mapping = load_province_mapping()
    expected_codes = set(mapping["provinces_code"])
    try:
        geojson = json.loads(GEOJSON_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DataValidationError(f"无法读取省级 GeoJSON: {exc}") from exc

    _require(geojson.get("type") == "FeatureCollection", "GeoJSON 类型错误")
    features = geojson.get("features")
    _require(isinstance(features, list), "GeoJSON 缺少 features")
    _require(len(features) == EXPECTED_PROVINCE_COUNT, "GeoJSON 必须包含31个省级 feature")

    seen: set[str] = set()
    for feature in features:
        properties = feature.get("properties") if isinstance(feature, dict) else None
        _require(isinstance(properties, dict), "GeoJSON feature 缺少 properties")
        code = str(properties.get("adcode", "")).strip()
        properties["adcode"] = code
        _require(code in expected_codes, f"GeoJSON 包含未知区划代码: {code}")
        _require(code not in seen, f"GeoJSON 区划代码重复: {code}")
        _require(feature.get("geometry", {}).get("type") in {"Polygon", "MultiPolygon"}, "非多边形边界")
        seen.add(code)

    _require(seen == expected_codes, "GeoJSON 省级代码不完整")
    return geojson


def load_dashboard_data() -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    mapping = load_province_mapping()
    dataset = load_population_data()
    geojson = load_geojson()
    return dataset, mapping, geojson


def get_year_list(dataset: pd.DataFrame) -> list[int]:
    return sorted(dataset["year"].unique().tolist(), reverse=True)


def get_province_options(mapping: pd.DataFrame) -> list[str]:
    return mapping.sort_values("id")["provinces"].tolist()


def filter_by_provinces(dataset: pd.DataFrame, province_codes: Iterable[str]) -> pd.DataFrame:
    codes = list(province_codes)
    if not codes:
        return dataset.iloc[0:0].copy()
    missing = set(codes) - set(dataset["provinces_code"])
    _require(not missing, f"省份筛选包含未知代码: {sorted(missing)}")
    return dataset[dataset["provinces_code"].isin(codes)].copy()


def calculate_migration_counts(
    yoy_data: pd.DataFrame,
    threshold: int = MIGRATION_THRESHOLD,
) -> tuple[int, int]:
    """Return counts above and below the migration threshold.

    The threshold is an absolute year-over-year resident-population change,
    not a registered migration count.
    """
    differences = yoy_data["population_difference"].dropna()
    return (
        int((differences > threshold).sum()),
        int((differences < -threshold).sum()),
    )


def calculate_population_difference(dataset: pd.DataFrame, year: int) -> pd.DataFrame:
    selected = dataset[dataset["year"] == year].copy()
    _require(not selected.empty, f"未找到{year}年数据")
    previous = dataset[dataset["year"] == year - 1][["provinces_code", "population"]]
    previous = previous.rename(columns={"population": "previous_population"})
    result = selected.merge(
        previous,
        on="provinces_code",
        how="left",
        validate="one_to_one",
    )
    result["population_difference"] = result["population"] - result["previous_population"]
    return result.sort_values(
        "population_difference",
        ascending=False,
        na_position="last",
    ).reset_index(drop=True)


def build_download_dataframe(year_data: pd.DataFrame, yoy_data: pd.DataFrame) -> pd.DataFrame:
    merged = year_data[
        ["year", "provinces", "provinces_full", "provinces_code", "population"]
    ].merge(
        yoy_data[["provinces_code", "population_difference"]],
        on="provinces_code",
        how="left",
        validate="one_to_one",
    )
    merged = merged.sort_values("population", ascending=False).reset_index(drop=True)
    merged["同比变化"] = merged["population_difference"].map(
        lambda value: "" if pd.isna(value) else int(value)
    )
    download = merged.rename(
        columns={
            "year": "年份",
            "provinces": "省份",
            "provinces_full": "省份全名",
            "provinces_code": "区划代码",
            "population": "人口",
        }
    )
    return download[["年份", "省份", "省份全名", "区划代码", "人口", "同比变化"]]


def dataframe_to_utf8_csv(dataset: pd.DataFrame) -> bytes:
    return dataset.to_csv(index=False).encode("utf-8-sig")


def get_trend_data(dataset: pd.DataFrame, province_code: str) -> pd.DataFrame:
    trend = dataset[dataset["provinces_code"] == province_code].copy()
    _require(not trend.empty, f"未找到省份代码 {province_code} 的数据")
    return trend.sort_values("year").reset_index(drop=True)
