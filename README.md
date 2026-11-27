# 出行游玩规划 Skill（city-trip-planner）

> 输入目的地、人数、年龄结构与预期活动，基于真实数据源检索美食、市井街区与商场，生成 A/B/C 三档可比较的游玩路线。

## 亮点

- **年龄结构驱动**：把年龄拆成体力、注意力、硬约束、决策权重；组合人群取"最弱成员 × 经验系数（0.85/0.92）"。
- **多代同游专项**：点位 A4/B3/C2、缓冲 ≥30%、12:00–14:30 强制 90 分钟午休、超过 1.2 km 打车。
- **真实数据源**：高德 / 百度 / Photon(OSM)；无凭证时回退 Photon；禁止编造店铺与坐标。
- **ABC 三档**：A 尽兴、B 舒适（默认推荐）、C 省心；三档给同一组硬指标对比。
- **本地与外地**：`local_halfday` / `local_fullday` / `day_trip` / `multiday` 四类节奏。

## 目录

```
city-trip-planner/        # Skill 本体
  SKILL.md                # 入口与工作流
  references/             # 年龄画像、ABC 分档、POI、路线、输出规范
  scripts/                # fetch_pois.py / plan_route.py
  assets/                 # 输出模板
  evals/                  # 42 项单元测试 + 测试夹具（TEST DATA ONLY）
chengdu_e2e/              # 成都真实端到端示例（Photon/OSM 坐标）
xhs_images/               # 小红书配图（4 张 1080x1440）
xhs_notes_package.md      # 小红书笔记素材包
research_report_*.md      # 产品调研报告
research_plan_*.md        # 调研计划
scripts/                  # 调研检索脚本
```

## 快速开始

```bash
# 1) 取真实 POI（无 key 时用 Photon/OSM）
python city-trip-planner/scripts/fetch_pois.py --provider photon --city 成都 \
  --query "人民公园:attraction" --query "宽窄巷子:street" --output pois.json

# 2) 生成 ABC 三档路线
python city-trip-planner/scripts/plan_route.py --input itinerary.json --output route.json
```

## 环境变量（可选）

- `AMAP_KEY`：高德开放平台 Web 服务 key
- `BAIDU_MAP_AK`：百度地图开放平台 ak
- 两者都没有时，`fetch_pois.py` 回退 Photon（OpenStreetMap，WGS84）

## 测试

```bash
cd city-trip-planner
python -m unittest discover -s evals -p "test_*.py"
```

当前：42 项测试全部通过。

## 发布状态

- 华为云 Skill 市场：`city-trip-planner`（通用场景 / 生活方式）
- 小红书 Skill 市场：`出行游玩规划`（已提交审核）

## 免责声明

方案基于公开数据与通用体力估算生成，营业时间、票价、预约规则、无障碍设施可能变化，出行前请二次核实。方案不替代监护人责任，也不构成医疗建议。

## License

未指定。使用或转载前请与作者确认。