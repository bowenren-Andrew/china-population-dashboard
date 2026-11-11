#!/usr/bin/env python3
"""Validate the reshaped Chinese provincial population dataset."""
from __future__ import annotations

import csv
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parent
REPO_ROOT = DATA_DIR.parent
DATASET_PATH = DATA_DIR / "china-population-2010-2023-reshaped.csv"
PROVINCE_MAP_PATH = DATA_DIR / "china-provinces.csv"
RAW_DIR = DATA_DIR / "raw"
SOURCE_MANIFEST_PATH = RAW_DIR / "source_manifest.json"

REQUIRED_COLUMNS = ["year", "provinces", "provinces_code", "population", "id"]
EXPECTED_YEARS = tuple(range(2010, 2024))
EXPECTED_ROW_COUNT = len(EXPECTED_YEARS) * 31
MAX_TOTAL_DIFF_RATIO = 0.0075

SOURCE_BY_YEAR = {
    2010: "nbs-2020-table2-6.csv",
    **{year: "nbs-2021-table2-5.csv" for year in range(2011, 2021)},
    **{year: "nbs-2024-table2-5.csv" for year in range(2021, 2024)},
}


class ValidationError(ValueError):
    """Raised when the dataset does not meet its documented contract."""


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as file:
            reader = csv.DictReader(file)
            fieldnames = reader.fieldnames or []
            return fieldnames, list(reader)
    except OSError as exc:
        raise ValidationError(f"无法读取文件 {path}: {exc}") from exc


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationError(message)


def load_province_mapping() -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    fieldnames, rows = _read_csv(PROVINCE_MAP_PATH)
    expected = ["provinces", "provinces_full", "provinces_code", "id"]
    _require(fieldnames == expected, f"省份映射字段错误: {fieldnames}")
    _require(len(rows) == 31, f"省份映射应为31行，实际为{len(rows)}行")

    by_code: dict[str, dict[str, Any]] = {}
    by_name: dict[str, dict[str, Any]] = {}
    for row in rows:
        code = row["provinces_code"].strip()
        name = row["provinces"].strip()
        full_name = row["provinces_full"].strip()
        item = {
            "provinces": name,
            "provinces_full": full_name,
            "provinces_code": code,
            "id": int(row["id"]),
        }
        _require(len(code) == 6 and code.isdigit(), f"非法区划代码: {code!r}")
        _require(code not in by_code, f"区划代码重复: {code}")
        _require(name not in by_name, f"省份短名重复: {name}")
        by_code[code] = item
        by_name[name] = item

    _require(
        sorted(item["id"] for item in by_code.values()) == list(range(1, 32)),
        "省份 id 必须为连续的 1-31",
    )
    return by_code, by_name


def _load_raw_tables(province_codes: set[str]) -> dict[str, dict[str, Any]]:
    tables: dict[str, dict[str, Any]] = {}
    for filename in sorted(set(SOURCE_BY_YEAR.values())):
        fieldnames, rows = _read_csv(RAW_DIR / filename)
        year_columns = [column for column in fieldnames if column.isdigit()]
        _require(year_columns, f"{filename} 缺少年份列")
        _require(len(rows) == 32, f"{filename} 应为全国行加31个省份，实际为{len(rows)}行")

        national_rows = [row for row in rows if row["provinces_code"] == "100000"]
        province_rows = [row for row in rows if row["provinces_code"] != "100000"]
        _require(len(national_rows) == 1, f"{filename} 全国行必须恰好一条")
        _require(len(province_rows) == 31, f"{filename} 省级行必须为31条")
        _require(
            {row["provinces_code"] for row in province_rows} == province_codes,
            f"{filename} 省份代码与映射不一致",
        )

        for row in province_rows + national_rows:
            for year in year_columns:
                raw_value = row[year].strip()
                _require(raw_value.isdigit(), f"{filename} {row['provinces']} {year} 非整数")
                _require(int(raw_value) > 0, f"{filename} {row['provinces']} {year} 非正数")

        tables[filename] = {
            "fieldnames": fieldnames,
            "years": tuple(int(year) for year in year_columns),
            "national": {int(year): int(national_rows[0][year]) for year in year_columns},
            "provinces": {
                row["provinces_code"]: {int(year): int(row[year]) for year in year_columns}
                for row in province_rows
            },
        }
    return tables


def _validate_source_provenance() -> None:
    _require(SOURCE_MANIFEST_PATH.exists(), "缺少来源清单 source_manifest.json")
    try:
        manifest = json.loads(SOURCE_MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"来源清单无法解析: {exc}") from exc

    sources = manifest.get("sources", [])
    _require(len(sources) == 3, "来源清单必须包含三份年鉴表")
    for source in sources:
        image_path = REPO_ROOT / source["local_file"]
        _require(image_path.exists(), f"缺少原始年鉴图: {image_path}")
        actual_hash = hashlib.sha256(image_path.read_bytes()).hexdigest()
        _require(
            actual_hash == source["sha256"],
            f"原始年鉴图校验失败: {image_path}",
        )


def _validate_overlap(raw_tables: dict[str, dict[str, Any]]) -> None:
    table_2021 = raw_tables["nbs-2021-table2-5.csv"]
    table_2024 = raw_tables["nbs-2024-table2-5.csv"]
    for year in range(2014, 2021):
        for code in table_2021["provinces"]:
            _require(
                table_2021["provinces"][code][year] == table_2024["provinces"][code][year],
                f"年鉴重叠年份不一致: {year} {code}",
            )
        _require(
            table_2021["national"][year] == table_2024["national"][year],
            f"年鉴全国数重叠年份不一致: {year}",
        )


def _load_national_totals(raw_tables: dict[str, dict[str, Any]]) -> dict[int, int]:
    totals: dict[int, int] = {}
    for year, filename in SOURCE_BY_YEAR.items():
        table = raw_tables[filename]
        _require(year in table["years"], f"{filename} 不包含 {year} 年")
        totals[year] = table["national"][year]
    return totals


def validate_dataset(dataset_path: Path = DATASET_PATH) -> list[dict[str, Any]]:
    by_code, by_name = load_province_mapping()
    _validate_source_provenance()
    raw_tables = _load_raw_tables(set(by_code))
    _validate_overlap(raw_tables)
    national_totals_wan = _load_national_totals(raw_tables)

    fieldnames, rows = _read_csv(dataset_path)
    _require(fieldnames == REQUIRED_COLUMNS, f"输出字段错误: {fieldnames}")
    _require(len(rows) == EXPECTED_ROW_COUNT, f"输出行数应为{EXPECTED_ROW_COUNT}，实际为{len(rows)}")

    seen: set[tuple[int, str]] = set()
    per_year: dict[int, list[dict[str, Any]]] = {year: [] for year in EXPECTED_YEARS}
    for line_number, row in enumerate(rows, start=2):
        try:
            year = int(row["year"])
            population = int(row["population"])
            province_id = int(row["id"])
        except (TypeError, ValueError) as exc:
            raise ValidationError(f"第{line_number}行数值无法解析: {row}") from exc

        code = row["provinces_code"].strip()
        name = row["provinces"].strip()
        _require(year in per_year, f"第{line_number}行年份越界: {year}")
        _require(code in by_code, f"第{line_number}行未知区划代码: {code}")
        _require(name == by_code[code]["provinces"], f"第{line_number}行省份名与代码不匹配")
        _require(province_id == by_code[code]["id"], f"第{line_number}行 id 与映射不匹配")
        _require(population > 0, f"第{line_number}行人口必须为正数")
        _require(population % 10_000 == 0, f"第{line_number}行人口不是1万人的整数倍")
        _require((year, code) not in seen, f"重复记录: {year} {code}")
        seen.add((year, code))

        per_year[year].append(
            {
                "provinces": name,
                "provinces_code": code,
                "population": population,
            }
        )

    summaries: list[dict[str, Any]] = []
    for year in EXPECTED_YEARS:
        year_rows = per_year[year]
        _require(len(year_rows) == 31, f"{year} 年应为31个省份，实际为{len(year_rows)}个")
        _require(
            {row["provinces_code"] for row in year_rows} == set(by_code),
            f"{year} 年省份集合不完整",
        )
        _require(
            {row["provinces"] for row in year_rows} == set(by_name),
            f"{year} 年省份名称与映射不一致",
        )

        province_sum = sum(row["population"] for row in year_rows)
        national_total = national_totals_wan[year] * 10_000
        difference = province_sum - national_total
        ratio = abs(difference) / national_total
        _require(
            ratio <= MAX_TOTAL_DIFF_RATIO,
            f"{year} 年分省合计偏差超限: {difference:+d} ({ratio:.4%})",
        )
        summaries.append(
            {
                "year": year,
                "province_count": len(year_rows),
                "province_sum": province_sum,
                "national_total": national_total,
                "difference": difference,
                "difference_ratio": ratio,
            }
        )

    _require(len(seen) == EXPECTED_ROW_COUNT, "总记录数校验失败")
    id_counts = Counter(int(row["id"]) for row in rows)
    _require(all(count == len(EXPECTED_YEARS) for count in id_counts.values()), "省份 id 年数不完整")
    return summaries


def main() -> int:
    try:
        summaries = validate_dataset()
    except ValidationError as exc:
        print(f"VALIDATION FAILED: {exc}", file=sys.stderr)
        return 1

    print("年份  省份数  分省合计(人)  全国总数(人)  差值(人)  偏差")
    for item in summaries:
        print(
            f"{item['year']}  {item['province_count']:>5}  "
            f"{item['province_sum']:>14,}  {item['national_total']:>12,}  "
            f"{item['difference']:>+9,}  {item['difference_ratio']:>+8.4%}"
        )
    print(
        f"VALIDATION PASSED: {EXPECTED_ROW_COUNT} rows, "
        f"{len(EXPECTED_YEARS)} years, 31 provinces per year"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
