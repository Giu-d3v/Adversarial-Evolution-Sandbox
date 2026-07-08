# 《对抗演化 · 涌现》游戏说明

> 基于《对抗演化与合作跃升》一书做的演化沙盒。  
> 跑：`python game/adversarial_evolution.py`  
> 源码：`game/adversarial_evolution.py`（单文件，约 850 行）

---

## ① 这是什么 / 怎么玩

一片 **960×720** 的黑暗世界，**80 个个体**开局，每个有 **8 个随机性状**。他们吃食物、互相攻击、合作分享、繁殖、死亡。**没有任何预设的策略标签** —— 各种演化策略（夺利、互助合作、修身、好善疾恶、伪善）从性状的组合中自然涌现。颜色就是策略的可视化：色相由 (攻击性, 合作性) 二维性状空间的角度决定，红≈夺利、绿≈互助合作、紫≈修身、黄≈未分化。

按 `R` 换种子，剧本就重写一次。

| 按键 | 作用 |
|---|---|
| `SPACE` | 暂停 / 继续 |
| `R` | 用新种子重置 |
| `N` | 鼠标点击 = 注入全随机新个体 |
| `F` | 鼠标点击 = 投放一团食物 |
| `+` / `-` | 仿真速度 ±0.5x（上限 8x） |
| `ESC` | 退出 + 自动保存本局 JSON |

---

## ② 屏幕上你看什么

### 世界里

- **小圆点 = 个体**。色相 hue = 个体在 (aggression, cooperation) 性状空间的角度（公式见下文）。**策略从颜色直接读出**：
  - 🔴 **红**（hue ≈ 0°）≈ 高攻击 / 低合作 → **夺利**
  - 🔵 **青**（hue ≈ 180°）≈ 高合作 / 低攻击 → **互助合作**（冷色调，区别于夺利）
  - 🟣 **蓝紫**（hue ≈ 270°）≈ 两者都低 → **修身**
  - 🟡 **黄绿**（hue ≈ 90°）≈ 两者都高 → **GVBE 好善疾恶**
  - 🟡 **黄**（hue ≈ 60°）≈ 两者都中等 → **未分化**（中心点）
- **大小** = 当前能量（`r = 3 + 6 × energy/MAX_ENERGY`，3..9 px）
- **亮度 (HSL-L)** = 当前能量（`L = 0.45 + 0.25 × energy/MAX_ENERGY`，0.45..0.70）
- **饱和度 (HSL-S)** = `0.55 + 0.35 × (1 − \|agg − coop\|)` —— **agg 和 coop 越接近越饱和**（纯策略色更鲜，杂色更灰）
- **绿色小点 = 食物**（半径越大 = 能量越多）

### 顶部 HUD（左到右）

| 元素 | 内容 |
|---|---|
| 标题 | "对抗演化 · 涌现" |
| 状态行 | `tick` `gen` `pop` `food` `births` `deaths` `running x1.0 mode=agent` |
| 策略占比 | 当前种群的 `夺利 / 互助合作 / 修身 / 好善疾恶 / 未分化 / 中间态` 前 3 名计数 |
| 阶段标签 | 自动判定当前剧情阶段（见下表），按状态变色（红=失败 / 绿=黄金 / 橙=丛林 / 白=中性）|
| 善者存活率 | 当前 `cooperation > 0.5` 的个体占比（百分比 + 文字）|

### 顶部 HUD（右侧）

- **aggression** / **cooperation** 直方图（10 bin 各 100px 宽，并排显示）
- **善者存活率 sparkline**：最近 220 tick 的折线，0.5 处一条参考线
- `frame N  step-err N`：每秒涨 ~60，不动 = 卡死

### 阶段分类（HUD 自动判定，11 档按优先级匹配）

| 顺序 | 阶段 | 触发 |
|---|---|---|
| 1 | 空 | 无活体 |
| 2 | 起始混乱 | tick < 60 |
| 3 | 濒临灭绝 | pop < 25 |
| 4 | 霍布斯丛林 | avgAgg > 0.72 且 avgCoop < 0.40 |
| 5 | 伊甸园期 | avgCoop > 0.55 且 avgAgg < 0.50 且近 60 tick pop Δ < ±20 |
| 6 | 合作繁荣中 | avgCoop > 0.50 且 avgAgg < 0.55 且近 60 tick pop Δ > +25 |
| 7 | 维度坍缩中 | 近 60 tick pop Δ < -40 |
| 8 | 夺利丛林 | avgAgg > 0.62 |
| 9 | 朴素合作 | avgCoop > 0.48 且 善者率 > 0.35 |
| 10 | 修身主导 | avgAgg < 0.40 且 avgCoop < 0.40 |
| 11 | 未分化 | 其余 |

> **色相公式说明**：因 trait 空间四个角间隔 90°，而目标 hue（红=0°, 青=180°, 蓝紫=270°, 黄绿=90°, 黄=60°）间隔不均，单一线性旋转无法同时命中所有角。当前公式 `hue = atan2(agg+coop-1, agg-coop)` + 中心特判（r<0.04 给黄）优先保证 **夺利=红、修身=蓝紫、未分化=黄**（最直观的三个），互助合作落到 **青**（冷色家族）作为妥协。GVBE 落在 **黄绿**（接近黄）。

---

## ③ 机制 —— 严格三档分类

### A. 直接实现（代码写死）

| 概念 | 实现 |
|---|---|
| **8 个 trait** 全随机初始化 | `aggression / cooperation / metabolism / speed / sense / defense / repro_thr / mut_rate` ∈ [0,1] 独立 uniform |
| **色相 = 策略可视化** | `hue = atan2(aggression-0.5, cooperation-0.5)` |
| **8 个 tick 动作** | 见下表 |
| **阶段分类**（11 档规则表）| `World.current_stage()` |
| **善者判定** | `cooperation > 0.5` |
| **善者存活率 sparkline** | `World.good_hist[]` 220 tick 环形缓冲 |
| **本局自动落盘** | ESC / R / 关窗 / 崩溃时存 `game/runs/{timestamp}.json` |

#### 8 个 tick 动作（每 tick 每 agent 按顺序执行）

| # | 动作 | 公式 / 行为 |
|---|---|---|
| 1 | 代谢 | `energy -= 0.004 + 0.015 × metabolism` |
| 2 | 感知 | `sense_radius = 18 + 80 × sense` 像素（toroidal） |
| 3 | 攻击 | `if energy<0.45 AND 邻居 AND random()<aggression AND 目标能量 < 自身×1.4: taken = 0.35 × (1 - 0.6 × target.defense); self.energy += taken - 0.06; target.energy -= taken` |
| 4 | 分享 | `if 邻居 AND random()<cooperation×0.6: 同色(hue距<35°)最近邻居; if self.energy>0.5 AND partner.energy<0.7: self.energy -= 0.06; partner.energy += 0.06` |
| 5 | 移动 | `speed = 1 + 6 × speed; 方向 = 0.6×随机 + 0.4×bias(bias = 朝最近食物当 energy < 1.3 时)` |
| 6 | 吃 | 距食物 < 8 像素、每 tick 最多 1 团、获得 `food.amount` |
| 7 | 繁殖 | `if energy > 1.1 + 0.5 × repro_thr AND random()<0.05: child = clone + traits += Gaussian(0, max(0.02, mut_rate×0.25)); 父与子能量 50/50 切` |
| 8 | 死亡 | `energy <= 0` 即死（唯一死因） |

**食物 spawn**：每 tick 检查 `if len(food) < 140 (FOOD_TARGET): spawn 3 团 (FOOD_SPAWN_PER_TICK)，能量 0.25..0.55 随机，位置全随机`。**初始食物 240 团，能量 0.25..0.50**。

**注意**：分享是 `1+1=2`（1:1 转移），不是字面 `1+1>2`。后者通过聚簇红利间接涌现。

### B. 涌现现象（代码不直接实现，但参数选择 + 机制组合自然产生）

| 现象 | 涌现条件 | 典型轨迹（实测，当前代码） |
|---|---|---|
| **夺利接管**（avgAgg 上升） | 无 punish 时，攻击者靠偷能量 + 税 0.06 比分享 0.06 划算 | seed=99：avgAgg 0.50 → **0.84**（t=1600）|
| **合作稳定**（avgAgg 下降） | 同色分享形成聚簇，聚簇红利高于偷窃 | seed=42：avgAgg 0.53 → **0.39**（t=1600）|
| **合作繁荣 → 维度坍缩** | 聚簇爆人口 → 食物总量不变（密度依赖）→ 大崩盘 | 偶发，触发需特定种子 |
| **善者存活率波动** | sparkline 直接画出 | seed=99：46% → 40%（稳定下降）；seed=42：50% → 49%（震荡）|
| **阶段漂移** | 11 档自动分类器驱动 | 见下表 |

**实测两枚种子（1600 tick 末态对比）**：

| | seed=42 | seed=99 |
|---|---|---|
| 末态阶段 | 未分化 | 夺利丛林 |
| pop | 222 | 216 |
| avgAgg | 0.39（下降）| 0.84（上升）|
| avgCoop | 0.44 | 0.42 |
| 善者率 | 49% | 40% |
| 剧情 | 合作友好（朴素合作稳了一段后回未分化）| 夺利接管（无挽回）|

### C. 未实现（明确缺失，影响剧情走向）

| 缺失 | 后果 | 影响等级 |
|---|---|---|
| **善选择 / punish 动作**（攻击夺利者 + 维护成本）| 没有 GVBE / 大跃进期稳态 | 🔴 最高 |
| **针锋相对 / TFT**（邻居记忆表）| 没有「你帮我我帮你，你抢我我抢你」| 🟠 高 |
| **搭便车检测**（接收分享但不分享）| 没有显式伪善策略 | 🟠 高 |
| **群体选择**（空间群落结构）| 没有群际竞争 | 🟡 中 |
| **超个体 / caste 分化** | 没有真社会性演化 | 🟡 中 |
| **性择逆向**（配偶偏好驱动）| 没有「渣」基因扩散 | 🟡 中 |
| **信息素 / 路径标记** | 没有集群外的信息流 | 🟢 低 |
| **内共生事件** | 没有显式融合剧情 | 🟢 低 |

**当前阶段分类器能识别所有"涌现"出的状态**（伊甸园期、霍布斯丛林等），但因为缺 C 类的几个机制，**伊甸园期很难稳住**（出现了会很快掉回未分化）。

---

## ④ 调参与落盘

### 调参入口

集中在 `game/adversarial_evolution.py` 顶部常量区：

| 区块 | 常量 |
|---|---|
| 生态 | `INIT_POP` `INIT_FOOD` `FOOD_TARGET` `FOOD_SPAWN_PER_TICK` |
| 个体能量 | `MAX_ENERGY` `START_ENERGY` `METAB_BASE` `METAB_SCALE` |
| 繁殖 | `REPRO_BASE` `REPRO_SCALE` + `_agent_act` 末尾的 `0.05` 概率 |
| 攻击 / 分享 | `ATTACK_TRANSFER` `SHARE_AMOUNT` `HUNGRY_THRESHOLD` + `_agent_act` 内 inline 的同色阈值 35° |
| 视觉 | `WORLD_W` `WORLD_H` `HUD_TOP_H` `HUD_BOTTOM_H` |

### 回归 / 调参命令

```bash
SDL_VIDEODRIVER=dummy DEBUG_TELEMETRY=1 python -u game/adversarial_evolution.py --ticks 1500 --seed 42
```

每 50 tick 打一次 `pop / food / avgAgg / avgCoop / good / stage`。

### 每局自动落盘

按 `ESC` / `R` / 关窗 / 崩溃时自动保存 JSON 到 `game/runs/YYYY-MM-DD_HH-MM-SS.json`。

JSON 结构：

```json
{
  "timestamp": "2026-07-07_23-41-39",
  "ended_reason": "ESC",                     // "ESC" | "reset" | "window-close" | "crash"
  "ticks": 500, "births": 218, "deaths": 166,
  "final": {
    "pop": 132, "avgAgg": 0.54, "avgCoop": 0.52, "goodRate": 0.61,
    "stage": "朴素合作", "maxGen": 2, "food": 60
  },
  "stage_transitions": [                     // 完整切换序列（不限 220 tick）
    {"tick": 1,   "stage": "起始混乱"},
    {"tick": 60,  "stage": "朴素合作"},
    {"tick": 93,  "stage": "未分化"}
  ],
  "history": [                               // 最近 220 tick 4 指标
    {"tick": 0, "pop": 80, "agg": 0.50, "coop": 0.50, "good": 0.50}
  ]
}
```

`game/runs/` 已加入 `.gitignore`，不污染仓库。可以用 `matplotlib` 加载多份 JSON 叠加画对比图。

---

## ⑤ 来源与对应

书仓在工作区根 `repo/` 目录。游戏内术语译名以 `repo/核心词汇表.md` 为准。

**游戏与书的对应（仅"直接实现"层面）**：

| 书中概念 | 游戏实现 |
|---|---|
| 夺利亏损定律 `1+1<2` | 攻击者固定付 0.06 夺利税 |
| 合作红利定律 `1+1>2` | 同色分享 = 1:1（字面），聚簇红利（涌现）|
| 短视夺利递进律 | 涌现：seed=99 avgAgg 0.50→0.84 |
| 善选择 | 未实现（C 类）|
| TFT | 未实现（C 类）|
| 维度跃升 / 维度坍缩 / 霍布斯丛林 / 伊甸园期 | **阶段分类器全部能识别**（11 档），但因缺善择机制，伊甸园期极难稳住 |

书中有一份作者自己写的离散策略模拟程序 `repo/对抗演化与合作跃升（下卷）——生命奇迹与永生哲学/03 附录/01 对抗演化模拟程序说明.md`，里面有 `修身 1.00 / 无条件利他 0.98 / 夺利 0.93 / TFT 0.80 / GVBE_1 0.60 ...` 的适应度参考表 —— 是后续加「善选择 / punish」机制时的最佳数值校准起点。