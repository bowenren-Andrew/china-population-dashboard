"""Self-contained SVG choropleth rendering for China province data."""
from __future__ import annotations

import html
import math
from typing import Any

import pandas as pd

from dashboard.formatting import format_number

SVG_COLOR_SCALES = {
    "blues": ("#f7fbff", "#08306b"),
    "cividis": ("#00204d", "#ffea46"),
    "greens": ("#f7fcf5", "#00441b"),
    "inferno": ("#000004", "#fcffa4"),
    "magma": ("#000004", "#fcfdbf"),
    "plasma": ("#0d0887", "#f0f921"),
    "reds": ("#fff5f0", "#67000d"),
    "rainbow": ("#6e40aa", "#1b9e77", "#f0c808", "#e8663d"),
    "turbo": ("#30123b", "#28bbec", "#a2fc3c", "#fb8022", "#7a0403"),
    "viridis": ("#440154", "#21918c", "#fde725"),
}

MAP_WIDTH = 900
MAP_HEIGHT = 430
MAP_PADDING = 10
LEGEND_X = 820
LEGEND_Y = 156
LEGEND_WIDTH = 12
LEGEND_HEIGHT = 120


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[index : index + 2], 16) for index in (0, 2, 4))


def _rgb_to_hex(value: tuple[int, int, int]) -> str:
    return "#" + "".join(f"{channel:02x}" for channel in value)


def _interpolate_color(value: float, maximum: float, theme: str) -> str:
    stops = SVG_COLOR_SCALES.get(theme, SVG_COLOR_SCALES["blues"])
    if maximum <= 0:
        return stops[0]
    ratio = max(0.0, min(1.0, value / maximum))
    position = ratio * (len(stops) - 1)
    lower_index = min(int(position), len(stops) - 2)
    fraction = position - lower_index
    lower = _hex_to_rgb(stops[lower_index])
    upper = _hex_to_rgb(stops[lower_index + 1])
    mixed = tuple(
        round(lower[channel] + (upper[channel] - lower[channel]) * fraction)
        for channel in range(3)
    )
    return _rgb_to_hex(mixed)


def _mercator_y(latitude: float) -> float:
    radians = math.radians(latitude)
    return math.log(math.tan(math.pi / 4 + radians / 2))


def _geojson_bounds(geojson: dict[str, Any]) -> tuple[float, float, float, float]:
    longitudes: list[float] = []
    latitudes: list[float] = []

    def collect(coordinates: Any) -> None:
        if (
            isinstance(coordinates, (list, tuple))
            and len(coordinates) >= 2
            and isinstance(coordinates[0], (int, float))
            and isinstance(coordinates[1], (int, float))
        ):
            longitudes.append(float(coordinates[0]))
            latitudes.append(float(coordinates[1]))
            return
        if isinstance(coordinates, (list, tuple)):
            for item in coordinates:
                collect(item)

    for feature in geojson.get("features", []):
        geometry = feature.get("geometry") if isinstance(feature, dict) else None
        if isinstance(geometry, dict):
            collect(geometry.get("coordinates"))

    if not longitudes or not latitudes:
        raise ValueError("GeoJSON 不包含可用于绘图的坐标")
    return min(longitudes), max(longitudes), min(latitudes), max(latitudes)


def _ring_path(
    ring: list[Any],
    lon_min: float,
    lon_max: float,
    mercator_min: float,
    mercator_max: float,
) -> str:
    points: list[str] = []
    longitude_span = lon_max - lon_min
    mercator_span = mercator_max - mercator_min
    if longitude_span <= 0 or mercator_span <= 0:
        return ""

    for point in ring:
        if (
            not isinstance(point, (list, tuple))
            or len(point) < 2
            or not isinstance(point[0], (int, float))
            or not isinstance(point[1], (int, float))
        ):
            continue
        longitude = float(point[0])
        latitude = float(point[1])
        x = MAP_PADDING + (longitude - lon_min) / longitude_span * (
            MAP_WIDTH - 2 * MAP_PADDING - 80
        )
        y = MAP_PADDING + (mercator_max - _mercator_y(latitude)) / mercator_span * (
            MAP_HEIGHT - 2 * MAP_PADDING
        )
        points.append(f"{x:.2f},{y:.2f}")

    if len(points) < 3:
        return ""
    return "M" + " L".join(points) + " Z"


def _geometry_path(
    geometry: dict[str, Any],
    lon_min: float,
    lon_max: float,
    mercator_min: float,
    mercator_max: float,
) -> str:
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates")
    if not isinstance(coordinates, list):
        return ""

    if geometry_type == "Polygon":
        polygons = [coordinates]
    elif geometry_type == "MultiPolygon":
        polygons = coordinates
    else:
        return ""

    paths: list[str] = []
    for polygon in polygons:
        if not isinstance(polygon, list):
            continue
        for ring in polygon:
            if isinstance(ring, list):
                path = _ring_path(ring, lon_min, lon_max, mercator_min, mercator_max)
                if path:
                    paths.append(path)
    return " ".join(paths)


def make_choropleth(
    input_df: pd.DataFrame,
    input_id: str,
    input_column: str,
    input_color_theme: str,
    geojson: dict[str, Any],
    hover_name: str = "provinces_full",
) -> str:
    """Render a local GeoJSON choropleth as self-contained SVG markup.

    Plotly's geo map fetches its base TopoJSON from a CDN even when a custom
    GeoJSON is supplied.  This renderer keeps the map available offline and in
    deployments without CDN access.
    """
    if input_df.empty:
        raise ValueError("地图数据不能为空")
    if input_column not in input_df.columns:
        raise ValueError(f"地图数据缺少字段: {input_column}")

    selected: dict[str, pd.Series] = {
        str(code): row for code, row in input_df.set_index(input_id).iterrows()
    }
    maximum = float(input_df[input_column].max())
    lon_min, lon_max, lat_min, lat_max = _geojson_bounds(geojson)
    mercator_min = _mercator_y(lat_min)
    mercator_max = _mercator_y(lat_max)

    paths: list[str] = []
    for feature in geojson.get("features", []):
        if not isinstance(feature, dict):
            continue
        properties = feature.get("properties")
        geometry = feature.get("geometry")
        if not isinstance(properties, dict) or not isinstance(geometry, dict):
            continue
        code = str(properties.get("adcode", "")).strip()
        if not code:
            continue
        path_data = _geometry_path(
            geometry,
            lon_min,
            lon_max,
            mercator_min,
            mercator_max,
        )
        if not path_data:
            continue

        selected_row = selected.get(code)
        if selected_row is None:
            fill = "#252525"
            state = "未选择"
            title = f"{properties.get('name', code)}（未选择）"
            css_class = "province"
        else:
            value = float(selected_row[input_column])
            fill = _interpolate_color(value, maximum, input_color_theme)
            name = str(selected_row.get(hover_name, properties.get("name", code)))
            title = f"{name}: {format_number(value)}"
            state = "已选择"
            css_class = "province province-selected"

        paths.append(
            f'<path class="{css_class}" data-code="{html.escape(code)}" '
            f'data-state="{html.escape(state)}" d="{path_data}" fill="{fill}" '
            'fill-rule="evenodd" stroke="#555555" stroke-width="0.6" '
            'vector-effect="non-scaling-stroke">'
            f"<title>{html.escape(title)}</title></path>"
        )

    if not paths:
        raise ValueError("GeoJSON 没有可绘制的省级多边形")

    stops = SVG_COLOR_SCALES.get(input_color_theme, SVG_COLOR_SCALES["blues"])
    gradient_stops = "".join(
        f'<stop offset="{index / (len(stops) - 1) * 100:.1f}%" '
        f'stop-color="{color}"></stop>'
        for index, color in enumerate(stops)
    )
    legend_max = format_number(maximum)
    return (
        '<div style="width:100%;max-width:900px;margin:0 auto;">'
        f'<svg viewBox="0 0 {MAP_WIDTH} {MAP_HEIGHT}" role="img" '
        'aria-label="中国省级人口分布地图" style="display:block;width:100%;height:auto;">'
        '<defs><linearGradient id="china-map-legend" x1="0" y1="1" x2="0" y2="0">'
        f"{gradient_stops}</linearGradient></defs>"
        + "".join(paths)
        + f'<rect x="{LEGEND_X}" y="{LEGEND_Y}" width="{LEGEND_WIDTH}" '
        f'height="{LEGEND_HEIGHT}" fill="url(#china-map-legend)" '
        'stroke="#666666" stroke-width="0.5"></rect>'
        f'<text x="{LEGEND_X + LEGEND_WIDTH + 8}" y="{LEGEND_Y + 10}" '
        'fill="#fafafa" font-size="12">人口</text>'
        f'<text x="{LEGEND_X - 8}" y="{LEGEND_Y + LEGEND_HEIGHT}" '
        'fill="#fafafa" font-size="11" text-anchor="end">0</text>'
        f'<text x="{LEGEND_X - 8}" y="{LEGEND_Y + 12}" '
        'fill="#fafafa" font-size="11" text-anchor="end">'
        + html.escape(legend_max)
        + "</text></svg></div>"
    )
