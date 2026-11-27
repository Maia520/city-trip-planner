# 输入结构化与真实数据源

## 1. 输入参数

把用户的一句话拆成下面这张表。**能问就问，问不到就用默认值，并把默认值说出来。**

| 字段 | 含义 | 默认值 | 说明 |
|------|------|--------|------|
| `destination` | 目的地（城市/片区/地标） | 必填 | 越具体越好，如"成都·宽窄巷子" |
| `party_size` | 总人数 | 由 members 求和 | 用于预算、订座、分线 |
| `members` | 年龄结构 | 按 party 推导 | `[{band, count}]`，band 见下 |
| `trip_type` | 出游类型 | `local_fullday` | local_halfday / local_fullday / day_trip / multiday |
| `activities` | 预期活动标签 | 空 | 见第 4 节枚举 |
| `date` | 出行日期 | 今天 | 影响闭馆日、节假日人流 |
| `days` | 天数 | 1 | 多日游影响缓冲与节奏 |
| `start_time` | 出发时间 | 09:30 | 太早店铺未开，太晚排不满 |
| `end_time` | 结束时间 | 21:00 | 一日游常见窗口 |
| `party` | 兼容用的人群快捷标签 | general | general / solo / couple / friends / family_with_kids / elderly |
| `max_walk_km` | 基准可接受步行量 | 6 | 实际上限 = 基准 × 组合系数 × 档位系数 |
| `mobility` | 行动能力 | normal | normal / stroller / wheelchair / slow_walk |
| `budget_level` | 预算档 | mid | low / mid / high |
| `experience_level` | 照护经验 | novice | novice / experienced；experienced 安全系数 0.92 |
| `transport` | 可用交通方式 | walk + metro + taxi | 决定位移耗时与接驳点 |
| `must_visit` | 必去清单 | 空 | 硬约束，作为路线锚点 |
| `preferences.food` | 口味偏好 | 本地特色 | 小吃、正餐、咖啡、甜品 |
| `preferences.atmosphere` | 氛围偏好 | 烟火气 | 烟火气、文艺、潮流、安静 |
| `preferences.crowd_tolerance` | 人流容忍度 | medium | low 时降级热门点、错峰 |
| `weather` | 天气 | 未提供 | 降雨概率、气温决定室内替代 |
| `health_flags` | 健康限制 | 空 | 高血压、心脏病、孕、术后、慢病 |
| `dietary` | 忌口/过敏 | 空 | 儿童餐、低盐软食、过敏原 |
| `constraints.no_queue_over_min` | 可接受排队 | 20 分钟 | 超过则标记风险 |
| `constraints.need_indoor_backup` | 需要室内备选 | true | 每个半场配一个室内点 |

### members 写法

```json
"members": [
  {"band": "36-50", "count": 2},
  {"band": "7-12", "count": 1},
  {"band": "61-70", "count": 1}
]
```

年龄段：`0-3`、`4-6`、`7-12`、`13-17`、`18-25`、`26-35`、`36-50`、`51-60`、`61-70`、`70+`，也接受 `A1`–`A10`。

### 默认值推导

- 有 6 岁以下儿童 → 叠加 `needs_indoor`、`stroller`、午休刚性。
- 有 65 岁以上长辈 → 叠加 `avoid_stairs`、`rest_frequent`；午间强制休息。
- 只说"一天" → 09:30–21:00；只说"半天" → 4 小时。
- 外地多日游 → `trip_type=multiday`，首末日轻安排，每天点位密度下调。
- 没说预算 → 按"本地小吃 + 中档正餐"规划，不主动推荐高价餐厅。

## 2. 数据源优先级

> 核心能力依赖真实世界事实，**不允许为了让流程跑通而自己造店**。

### 优先级 1：地图开放平台 API（结构化、最可靠）

| 数据源 | 需要的凭证 | 能解决什么 |
|--------|-----------|-----------|
| 高德开放平台 Web 服务 API | 环境变量 `AMAP_KEY` | POI 搜索、地理编码、步行/公交/驾车路径距离与耗时 |
| 百度地图开放平台 | 环境变量 `BAIDU_MAP_AK` | POI 检索、路线规划、地理编码 |

配置方式：凭证只从环境变量读取，**不得写进脚本或提交到仓库**。

常用接口示例（key 一律从环境变量读取）：

```bash
# 高德：关键词搜索（餐饮）
curl -s "https://restapi.amap.com/v3/place/text?keywords=美食&city=成都&types=050000&offset=20&page=1&extensions=all&key=${AMAP_KEY}"

# 高德：周边搜索（以某点为中心 1.5 km，餐饮/购物/休闲）
curl -s "https://restapi.amap.com/v3/place/around?location=104.06,30.67&radius=1500&types=050000|060000|080000&offset=20&page=1&extensions=all&key=${AMAP_KEY}"

# 高德：步行路径（拿距离与耗时）
curl -s "https://restapi.amap.com/v3/direction/walking?origin=104.06,30.67&destination=104.08,30.66&key=${AMAP_KEY}"

# 百度：周边检索
curl -s "https://api.map.baidu.com/place/v2/search?query=美食&location=30.67,104.06&radius=1500&output=json&ak=${BAIDU_MAP_AK}"
```

字段映射要点：

- `location` 在高德是 `经度,纬度`，在百度是 `纬度,经度`，调用前先确认。
- 高德 `types`：050000 餐饮、060000 购物、080000 休闲娱乐；细分以官方文档为准。
- 返回结果必须落成 `pois[]`，含 `name`、`lat`、`lng`、`category`、`source`、`verified_at`。

能力边界（务必如实告知用户）：

- 地图 API 的多途经点是"按输入顺序规划"，不做顺序优化；顺序优化由 `plan_route.py` 完成。
- POI 营业时间可能缺失或过期，需用点评/官方信息交叉核实。
- 实时排队、实时人流通常拿不到，只能给风险等级。

### 零配置 fallback：Photon / OpenStreetMap

没有 `AMAP_KEY` / `BAIDU_MAP_AK` 时，可用 `scripts/fetch_pois.py` 通过 Photon（OSM）检索真实地标坐标：

```bash
python "$SKILL_ROOT/scripts/fetch_pois.py" --provider photon --city 成都 \
  --query "人民公园:attraction" --query "宽窄巷子:street" --output pois.json
```

- 优点：无需凭证，返回真实 WGS84 坐标；适合地标、街区、商场。
- 限制：缺少营业时间与餐饮小店细节，`confidence` 一律标 `pending`。
- 坐标系：Photon=WGS84、高德=GCJ02、百度=BD09，**禁止混用**，否则会有几百米偏移。
- 有 key 时同一个脚本可切换：`--provider amap` 或 `--provider baidu`。

### 优先级 2：Web Search / Browser（无凭证时的主路径）

- 优先采信**缺点描述充分**的攻略，而不是清一色赞美的笔记。
- 记录来源链接与抓取日期；同一事实至少两个独立来源互证。
- 坐标缺失时标注"坐标未核验"，不得估算后当真。

### 优先级 3：用户提供

用户粘贴的清单、截图、收藏夹、链接，属于可信输入，标 `source=user_provided`。

### 三源都不可用

明确告知：

> 当前环境没有可用的地图/搜索数据源，我可以先给出检索框架、点位类型清单和路线算法，但无法提供真实店铺与坐标。你可以提供清单或启用地图 API。

**禁止**用编造的店铺把流程"跑通"。

## 3. 每个 POI 必须携带的字段

| 字段 | 是否必填 | 说明 |
|------|----------|------|
| `id` | 是 | 稳定唯一标识 |
| `name` | 是 | 真实名称，禁止杜撰 |
| `lat` / `lng` | 路线规划必填 | 缺失则无法算距离，降级为"顺序建议" |
| `category` | 是 | food / street / mall / attraction |
| `tier` | 建议 | core / normal / optional，决定各档是否保留 |
| `dwell_min` | 是 | 建议停留分钟数 |
| `open_time` / `close_time` | 建议 | 缺失标"未核验" |
| `closed_days` | 建议 | 0=周一 … 6=周日 |
| `must_visit` | 否 | 用户必去（自动视为 core） |
| `indoor` | 否 | 雨天/高温替代判断 |
| `has_stairs` / `step_count` | 否 | 台阶与爬升硬约束 |
| `queue_min` | 否 | 预计排队，用于排队容忍度校验 |
| `source` | 是 | 来源 URL / API / user_provided |
| `verified_at` | 是 | 最后核实日期 |
| `confidence` | 是 | verified / pending / suspicious |
| `note` | 否 | 招牌菜、最佳时段、玩法建议 |

## 4. 活动标签

`food` 美食、`street` 市井街区、`mall` 商场、`attraction` 景点、`nature` 自然风光、`hiking` 徒步登山、`theme_park` 主题乐园、`museum` 博物馆展馆、`shopping` 逛街购物、`nightlife` 夜游夜市、`show` 演出赛事、`camping` 露营、`beach` 海滨玩水、`hotspring` 康养温泉、`photo` 摄影打卡、`study` 研学、`family_park` 亲子乐园。

活动与年龄的适配见 `references/age-profiles.md`。

## 5. 时效与置信度

| 置信度 | 判定 | 使用方式 |
|--------|------|----------|
| `verified` | ≥2 个独立来源一致，且 3 个月内有更新 | 可进主路线核心 |
| `pending` | 单一来源，或信息超过 6 个月 | 进备选区，或标注"待核验"后进路线 |
| `suspicious` | 评价分布异常、疑似刷评、地址对不上 | 不进主路线，只作提示 |

- 营业时间、闭店、改造、搬迁属于高时效信息，出行前必须二次确认。
- 不把"平台评分"当作唯一排序依据；优先看业态、距离、时段适配和差评细节。

## 6. 合规

- 优先官方 API；遵守平台条款与 robots 规则。
- 评价内容只做聚合统计与要点提炼，不逐条复制。
- 不采集、不存储用户个人敏感信息。
- 不承诺实时数据；所有动态信息标注获取时间。