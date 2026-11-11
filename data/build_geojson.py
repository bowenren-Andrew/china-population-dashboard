#!/usr/bin/env python3
"""Trim and validate the DataV China province GeoJSON for dashboard use."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any, Iterator

DATA_DIR = Path(__file__).resolve().parent
REPO_ROOT = DATA_DIR.parent
DEFAULT_SOURCE = DATA_DIR / "raw" / "geojson" / "100000_full.json"
DEFAULT_OUTPUT = DATA_DIR / "china-provinces.geojson"
DEFAULT_MANIFEST = DATA_DIR / "raw" / "geojson_source_manifest.json"
PROVINCE_MAP_PATH = DATA_DIR / "china-provinces.csv"
SOURCE_URL = "https://geo.datav.aliyun.com/areas_v3/bound/100000_full.json"
BOUNDARY_NOTE = "仅用于统计可视化，不作为行政区划或边界依据。"


class GeoJSONError(ValueError):
    """Raised when the source or trimmed GeoJSON is invalid."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise GeoJSONError(message)


def load_expected_codes() -> dict[str, str]:
    with PROVINCE_MAP_PATH.open("r", encoding="utf-8", newline="") as file:
        rows = list(csv.DictReader(file))
    _require(len(rows) == 31, "省份映射必须为31行")
    return {row["provinces_code"]: row["provinces"] for row in rows}


def _iter_points(value: Any) -> Iterator[tuple[float, float]]:
    if (
        isinstance(value, list)
        and len(value) >= 2
        and isinstance(value[0], (int, float))
        and isinstance(value[1], (int, float))
    ):
        yield float(value[0]), float(value[1])
        return
    if isinstance(value, list):
        for child in value:
            yield from _iter_points(child)


def _validate_geometry(geometry: Any, label: str) -> None:
    _require(isinstance(geometry, dict), f"{label} 缺少 geometry")
    _require(geometry.get("type") in {"Polygon", "MultiPolygon"}, f"{label} 不是多边形")
    coordinates = geometry.get("coordinates")
    _require(isinstance(coordinates, list) and coordinates, f"{label} 坐标为空")
    points = list(_iter_points(coordinates))
    _require(points, f"{label} 未找到有效坐标")
    for longitude, latitude in points:
        _require(70 <= longitude <= 140, f"{label} 经度越界: {longitude}")
        _require(0 <= latitude <= 60, f"{label} 纬度越界: {latitude}")


def _normalise_feature(feature: dict[str, Any]) -> dict[str, Any]:
    properties = feature.get("properties")
    _require(isinstance(properties, dict), "feature 缺少 properties")
    properties = dict(properties)
    properties["adcode"] = str(properties.get("adcode", "")).strip()
    output = dict(feature)
    output["properties"] = properties
    _validate_geometry(feature.get("geometry"), str(properties.get("name") or properties["adcode"]))
    return output


def build_geojson(
    source_path: Path,
    output_path: Path,
    manifest_path: Path,
    downloaded_at: str,
) -> dict[str, Any]:
    expected_codes = load_expected_codes()
    try:
        source = json.loads(source_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GeoJSONError(f"无法读取源 GeoJSON: {exc}") from exc

    _require(source.get("type") == "FeatureCollection", "源文件不是 FeatureCollection")
    source_features = source.get("features")
    _require(isinstance(source_features, list), "源文件缺少 features")

    normalised = [_normalise_feature(feature) for feature in source_features]
    by_code: dict[str, dict[str, Any]] = {}
    excluded: list[dict[str, str]] = []
    for feature in normalised:
        code = feature["properties"]["adcode"]
        if code in expected_codes:
            _require(code not in by_code, f"省级 feature 重复: {code}")
            by_code[code] = feature
        else:
            excluded.append(
                {
                    "name": str(feature["properties"].get("name", "")),
                    "adcode": code,
                }
            )

    _require(
        set(by_code) == set(expected_codes),
        f"省级 feature 不完整: 缺少 {sorted(set(expected_codes) - set(by_code))}",
    )

    trimmed_features = [by_code[code] for code in sorted(by_code, key=int)]
    trimmed = {"type": "FeatureCollection", "features": trimmed_features}
    output_path.write_text(
        json.dumps(trimmed, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )

    manifest = {
        "source_name": "阿里云 DataV.GeoAtlas 中国省级行政区划",
        "source_url": SOURCE_URL,
        "downloaded_at": downloaded_at,
        "source_file": source_path.relative_to(REPO_ROOT).as_posix(),
        "source_sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
        "source_feature_count": len(source_features),
        "output_file": output_path.relative_to(REPO_ROOT).as_posix(),
        "output_sha256": hashlib.sha256(output_path.read_bytes()).hexdigest(),
        "output_feature_count": len(trimmed_features),
        "included_adcodes": list(by_code),
        "excluded_features": excluded,
        "boundary_note": BOUNDARY_NOTE,
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--downloaded-at", default=date.today().isoformat())
    args = parser.parse_args()

    try:
        manifest = build_geojson(args.source, args.output, args.manifest, args.downloaded_at)
    except (GeoJSONError, OSError) as exc:
        print(f"GEOJSON BUILD FAILED: {exc}")
        return 1

    print(
        f"GEOJSON BUILD PASSED: {manifest['output_feature_count']} features, "
        f"{manifest['output_sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
