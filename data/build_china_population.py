#!/usr/bin/env python3
"""Build and validate the reshaped Chinese provincial population dataset."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

from validate_china_population import ValidationError, validate_dataset

DATA_DIR = Path(__file__).resolve().parent
REPO_ROOT = DATA_DIR.parent
RAW_DIR = DATA_DIR / "raw"
PROVINCE_MAP_PATH = DATA_DIR / "china-provinces.csv"
OUTPUT_PATH = DATA_DIR / "china-population-2010-2023-reshaped.csv"

EXPECTED_YEARS = tuple(range(2010, 2024))
OUTPUT_COLUMNS = ["year", "provinces", "provinces_code", "population", "id"]

SOURCE_BY_YEAR = {
    2010: "nbs-2020-table2-6.csv",
    **{year: "nbs-2021-table2-5.csv" for year in range(2011, 2021)},
    **{year: "nbs-2024-table2-5.csv" for year in range(2021, 2024)},
}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationError(message)


def _year_columns(columns: list[str]) -> list[str]:
    return [column for column in columns if column.isdigit()]


def _load_mapping() -> pd.DataFrame:
    mapping = pd.read_csv(
        PROVINCE_MAP_PATH,
        dtype={"provinces_code": str, "id": int},
        encoding="utf-8",
    )
    expected_columns = ["provinces", "provinces_full", "provinces_code", "id"]
    _require(list(mapping.columns) == expected_columns, "省份映射字段错误")
    _require(len(mapping) == 31, f"省份映射应为31行，实际为{len(mapping)}行")
    _require(mapping["provinces_code"].nunique() == 31, "省份区划代码必须唯一")
    _require(mapping["provinces"].nunique() == 31, "省份短名必须唯一")
    _require(sorted(mapping["id"].tolist()) == list(range(1, 32)), "省份 id 必须为1-31")
    _require(mapping["provinces_code"].str.fullmatch(r"\d{6}").all(), "区划代码必须为6位数字")
    return mapping


def _load_raw_tables(mapping: pd.DataFrame) -> dict[str, pd.DataFrame]:
    expected_codes = set(mapping["provinces_code"])
    tables: dict[str, pd.DataFrame] = {}
    for filename in sorted(set(SOURCE_BY_YEAR.values())):
        table = pd.read_csv(
            RAW_DIR / filename,
            dtype={"provinces_code": str},
            encoding="utf-8",
        )
        year_columns = _year_columns(list(table.columns))
        _require(year_columns, f"{filename} 缺少年份列")
        _require(len(table) == 32, f"{filename} 应为全国行加31省，实际为{len(table)}行")
        _require(not table[year_columns].isna().any().any(), f"{filename} 存在空值")

        national = table[table["provinces_code"] == "100000"]
        provinces = table[table["provinces_code"] != "100000"]
        _require(len(national) == 1, f"{filename} 全国行必须恰好一条")
        _require(len(provinces) == 31, f"{filename} 省级行必须为31条")
        _require(set(provinces["provinces_code"]) == expected_codes, f"{filename} 省份代码不完整")

        for year in year_columns:
            table[year] = pd.to_numeric(table[year], errors="raise").astype("int64")
            _require((table[year] > 0).all(), f"{filename} {year} 年存在非正数")

        code_to_name = dict(zip(mapping["provinces_code"], mapping["provinces"]))
        for row in provinces.itertuples(index=False):
            _require(
                row.provinces == code_to_name[row.provinces_code],
                f"{filename} {row.provinces_code} 省份名不匹配",
            )
        tables[filename] = table
    return tables


def _validate_overlap(raw_tables: dict[str, pd.DataFrame]) -> None:
    table_2021 = raw_tables["nbs-2021-table2-5.csv"].set_index("provinces_code")
    table_2024 = raw_tables["nbs-2024-table2-5.csv"].set_index("provinces_code")
    for year in range(2014, 2021):
        column = str(year)
        _require(column in table_2021.columns, f"2021年鉴缺少{year}年")
        _require(column in table_2024.columns, f"2024年鉴缺少{year}年")
        _require(
            table_2021[column].equals(table_2024[column]),
            f"2021与2024年鉴在{year}年存在不一致",
        )


def build_dataset() -> pd.DataFrame:
    mapping = _load_mapping()
    raw_tables = _load_raw_tables(mapping)
    _validate_overlap(raw_tables)

    parts: list[pd.DataFrame] = []
    for year in EXPECTED_YEARS:
        table = raw_tables[SOURCE_BY_YEAR[year]]
        column = str(year)
        _require(column in table.columns, f"{SOURCE_BY_YEAR[year]} 缺少{year}年")
        province_data = table[table["provinces_code"] != "100000"].copy()
        province_data = province_data[["provinces", "provinces_code", column]]
        province_data = province_data.rename(columns={column: "population_wan"})
        province_data["year"] = year
        parts.append(province_data)

    dataset = pd.concat(parts, ignore_index=True)
    mapped = mapping[["provinces_code", "provinces", "id"]].rename(
        columns={"provinces": "mapped_provinces"}
    )
    dataset = dataset.merge(
        mapped,
        on="provinces_code",
        how="left",
        validate="many_to_one",
    )
    _require(dataset["mapped_provinces"].notna().all(), "存在无法映射的省份")
    _require(
        (dataset["provinces"] == dataset["mapped_provinces"]).all(),
        "原始表省份名与映射表不一致",
    )
    _require(
        dataset["population_wan"].between(1, 100_000).all(),
        "原始人口值超出合理范围",
    )

    dataset["population"] = dataset["population_wan"].astype("int64") * 10_000
    dataset = dataset[OUTPUT_COLUMNS].sort_values(["year", "id"]).reset_index(drop=True)
    _require(len(dataset) == 434, f"输出应为434行，实际为{len(dataset)}行")
    return dataset


def main() -> int:
    temporary_path = OUTPUT_PATH.with_name(OUTPUT_PATH.name + ".tmp")
    try:
        dataset = build_dataset()
        dataset.to_csv(temporary_path, index=False, encoding="utf-8")
        summaries = validate_dataset(temporary_path)
        temporary_path.replace(OUTPUT_PATH)
    except (ValidationError, ValueError, OSError) as exc:
        if temporary_path.exists():
            temporary_path.unlink()
        print(f"BUILD FAILED: {exc}", file=sys.stderr)
        return 1

    print("年份  省份数  分省合计(人)  全国总数(人)  差值(人)  偏差")
    for item in summaries:
        print(
            f"{item['year']}  {item['province_count']:>5}  "
            f"{item['province_sum']:>14,}  {item['national_total']:>12,}  "
            f"{item['difference']:>+9,}  {item['difference_ratio']:>+8.4%}"
        )
    print(f"BUILD PASSED: {OUTPUT_PATH.relative_to(REPO_ROOT)} ({len(dataset)} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
