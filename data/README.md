# 中国省级人口数据

## 覆盖范围

- 31 个大陆省级行政区：北京、天津、河北、山西、内蒙古、辽宁、吉林、黑龙江、上海、江苏、浙江、安徽、福建、江西、山东、河南、湖北、湖南、广东、广西、海南、重庆、四川、贵州、云南、西藏、陕西、甘肃、青海、宁夏、新疆。
- 年份：2010–2023。
- 最终数据：31 × 14 = 434 行。
- 不包含香港、澳门和台湾；全国总数不进入最终省级长表。

## 官方来源

数据来自国家统计局《中国统计年鉴》的“分地区年末人口数”表。原始表为 JPG 图片，单位为“万人”。

| 使用年份 | 年鉴 | 表号 | 官方原图 |
|---|---|---|---|
| 2010 | 《中国统计年鉴 2020》 | 表 2-6 | [C0206.jpg](https://www.stats.gov.cn/sj/ndsj/2020/html/C0206.jpg) |
| 2011–2020 | 《中国统计年鉴 2021》 | 表 2-5 | [C02-05.jpg](https://www.stats.gov.cn/sj/ndsj/2021/html/C02-05.jpg) |
| 2021–2023 | 《中国统计年鉴 2024》 | 表 2-5 | [C02-05.jpg](https://www.stats.gov.cn/sj/ndsj/2024/html/C02-05.jpg) |

年鉴目录页：

- <https://www.stats.gov.cn/sj/ndsj/2020/indexch.htm>
- <https://www.stats.gov.cn/sj/ndsj/2021/indexch.htm>
- <https://www.stats.gov.cn/sj/ndsj/2024/indexch.htm>

三张原图已保存到 `data/raw/source_images/`。下载日期、链接和 SHA-256 记录在 `data/raw/source_manifest.json`。

## 口径说明

- 2010 年为当年人口普查推算数。
- 2011–2020 年采用 2021 年鉴中的七普后修订序列，避免将 2020 年前后不同修订口径混用。
- 2021–2023 年采用 2024 年鉴数据。
- 2021 与 2024 年鉴重叠覆盖 2014–2020 年；构建和校验脚本会逐省核对重叠年份，要求完全一致。
- 官方表格精度为 1 万人，因此最终 CSV 中的人口值都是 10,000 的整数倍。没有插值、补 0 或模拟数据。
- 分省合计与全国总数存在统计口径差异。当前数据中最大偏差为 2010 年的 0.5265%，其余年份约 0.14%–0.17%。校验上限设置为 0.75%，不通过则停止构建。原始数据不做人为配平。

## 处理链

1. 官方年鉴表图片保存到 `data/raw/source_images/`。
2. 将三张表逐格转录为 `data/raw/` 下的三个原始 CSV，保留官方“万人”单位和“全国”行。
3. `data/build_china_population.py` 读取原始表，执行以下处理：
   - 校验省份代码、年份列、全国行和人口正数。
   - 校验 2021 与 2024 年鉴的 2014–2020 年重叠数据。
   - 按年份选择权威来源，排除全国行。
   - 将“万人”乘以 10,000，统一为“人”。
   - 宽表转长表，并按年份、省份排序。
   - 写入临时文件，完整校验通过后才替换正式 CSV。
4. `data/validate_china_population.py` 独立校验最终 CSV、省级映射、来源图片哈希和全国合计偏差。

运行命令：

```powershell
.\.venv\Scripts\python.exe data\build_china_population.py
.\.venv\Scripts\python.exe data\validate_china_population.py
```

## 文件说明

| 文件 | 说明 |
|---|---|
| `china-population-2010-2023-reshaped.csv` | 最终长表，供 dashboard 读取 |
| `china-provinces.csv` | 省份短名、全名、6 位区划代码和固定 id 映射 |
| `build_china_population.py` | 从原始快照构建最终长表并执行校验 |
| `validate_china_population.py` | 独立数据校验与全国合计报告 |
| `raw/nbs-2020-table2-6.csv` | 2020 年鉴表 2-6 原始转录，使用 2010 年 |
| `raw/nbs-2021-table2-5.csv` | 2021 年鉴表 2-5 原始转录，使用 2011–2020 年 |
| `raw/nbs-2024-table2-5.csv` | 2024 年鉴表 2-5 原始转录，使用 2014–2023 年 |
| `raw/source_images/` | 三张官方年鉴表原图 |
| `raw/source_manifest.json` | 来源 URL、下载日期、年份用途和图片哈希 |

## 最终字段

```text
year, provinces, provinces_code, population, id
```

- `year`：年份，2010–2023。
- `provinces`：不带行政后缀的中文短名。
- `provinces_code`：6 位统计用区划代码，字符串保存。
- `population`：年末常住人口，单位“人”。
- `id`：稳定的省级排序编号，1–31。

`china-provinces.csv` 中的 `provinces_full` 保存带后缀的完整名称，用于地图和展示映射。
