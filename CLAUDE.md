# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目性质

`E:/Adversarial-Evolution/` 是一个**游戏开发工作区**，题材取自同目录 `repo/` 下的开源中文著作《**对抗演化与合作跃升**》（Wing-2025/Adversarial-Evolution）。

- 游戏的设计母题、机制原型、关卡剧情、术语、典故均来自 `repo/`。
- `repo/` 内容是**只读参考资料**，不要在游戏代码中 import 或硬编码大段原文；引用术语时参见 `repo/核心词汇表.md` 作为权威译名表。

## 仓库当前布局

```
E:/Adversarial-Evolution/
├── .claude/                  # Claude Code 配置
├── repo/                     # 原始书仓（参考材料，不要直接改动）
│   ├── README.md             # 全书导览、章节链接、参考文献
│   ├── 核心词汇表.md          # 中英术语权威表 → 游戏内术语首选这里
│   ├── 全书选萃.md            # 三卷精选节选
│   ├── 全书导读/              # LLM导读各卷
│   ├── PDF/                  # 三卷 PDF
│   ├── 对抗演化与合作跃升（上卷）/  # 生命演化：单细胞→多细胞→文明
│   ├── 对抗演化与合作跃升（中卷）/  # 人类演化：人族起源、帝国兴亡
│   ├── 对抗演化与合作跃升（下卷）/  # 生命奇迹与永生哲学
│   ├── English Version/      # 英文翻译版
│   ├── LLM自动校订版/         # LLM 校订稿
│   ├── 全书音频连载/          # 喜马拉雅音频索引
│   └── check_windows_compatibility.py  # 修复 Windows 非法文件名的工具
└── CLAUDE.md                 # 本文件
```

## 书中可入游戏的核心概念

下列术语都有 `repo/核心词汇表.md` 中的正规定义。设计/编码时若要在 UI、文案、数值中引用，**优先用此处的统一译名**。

**核心张力（游戏最常用的对偶）**
- 对抗演化 (Adversarial Evolution) ↔ 合作跃升 (Cooperative Ascension)
- 合作红利定律 `1+1>2` ↔ 夺利亏损定律 `1+1<2`
- 好善疾恶主义 ↔ 伪善主义 (Hypocrisyism)
- 修身主义 ↔ 夺利主义 (Grabbingism)
- 维度跃升 ↔ 维度坍缩（Dimensional Collapse）

**机制原型**
- **善选择 (Virtue Selection)** — 群体筛选/惩罚机制，可对应游戏中的法律、声誉、淘汰系统。
- **针锋相对 (Tit-for-Tat)** — 经典博弈策略，可作为 AI 行为或玩家对手规则。
- **混沌对抗困境 (Chaotic Adversarial Dilemma)** — 中后期环境/经济/人口张力，对应后期关卡。
- **逆淘汰 (Reverse Selection)** — 善良者被淘汰、夺利者获优势的劣化螺旋，可作为恶性事件链。
- **短视夺利递进律** — 夺利行为不断加码的内卷，可作为难度递增设计依据。
- **大腐化期 / 霍布斯丛林 (Hobbesian Jungle)** — 失败状态 / 坏结局。
- **伊甸园时期 (Edenic Period) / 大跃进时期** — 黄金期 / 满收益稳态。

**演化阶段（自然关卡/章节划分依据）**
- 上卷：单细胞 → 真核（内共生）→ 多细胞 → 人类 → 文明底层逻辑
- 中卷：人族起源 → 部落 → 帝国兴亡 → 制度演化
- 下卷：高维生命 / 永生 / 意识 / 智能与压缩

## 工作流约定

1. **设计引用前先核对**：`repo/核心词汇表.md` 是术语真理之源；引用具体观点时回到 `repo/README.md` 章节链接定位原文段落。
2. **路径注意**：`repo/` 内目录名包含全角空格与 `：`, `——` 等字符，shell 操作请用引号包裹或在 `repo/` 内先运行 `python check_windows_compatibility.py`。
3. **不要修改 `repo/`**：它是上游参考材料，所有游戏产物放在工作区根目录（`E:/Adversarial-Evolution/`，不含 `.claude/` 与 `repo/`）。

## 常用命令

工作区目前尚未生成游戏代码；常用命令会在选型后写入此节（典型候选：`npm run dev` / `python main.py` / `cargo run` 等）。在选定技术栈之前没有可写的"构建/测试"指令。

修复 `repo/` 在 Windows 下的非法路径（如克隆产生）：

```bash
cd "E:/Adversarial-Evolution/repo"
python check_windows_compatibility.py
```

## 已选定的技术栈

游戏《**对抗演化 · 涌现**》使用 Python 3.12 + pygame 2.6 实现，单文件：

- `game/adversarial_evolution.py` — 全部代码（World / Agent / Renderer / main）
- `requirements.txt` — `pygame>=2.6`

### 运行

```bash
# 交互式
python game/adversarial_evolution.py

# 无渲染冒烟测试（用于回归）
SDL_VIDEODRIVER=dummy python game/adversarial_evolution.py --ticks 1000 --seed 42

# 调试遥测（每 50 tick 打印一次种群均值）
SDL_VIDEODRIVER=dummy DEBUG_TELEMETRY=1 python -u game/adversarial_evolution.py --ticks 1000 --seed 42
```

### 交互控制

| 按键 | 作用 |
|---|---|
| `SPACE` | 暂停 / 继续 |
| `R` | 用新随机种子重置世界 |
| `N` | 切换鼠标点击模式 → 注入新个体 |
| `F` | 切换鼠标点击模式 → 投放食物 |
| `+` / `-` | 加 / 减仿真速度（最多 8x） |
| `ESC` | 退出 |

### 机制要点（实现与书中的对应）

- 8 个 trait 全随机初始化：`aggression` / `cooperation` / `metabolism` / `speed` / `sense` / `defense` / `repro_thr` / `mut_rate`
- 颜色由 (aggression, cooperation) 在 trait 空间的角度映射到 HSL hue —— 玩家**不靠策略标签**直接"看到"涌现
- 攻击者每次出击支付"夺利税"，对应书中的**夺利亏损定律** (`1+1<2`)
- 同 hue 邻居之间可分享能量，对应**合作红利定律** (`1+1>2`) 的可执行形式
- 食物总量为绝对值（不随人口扩张），保证密度依赖的生存压力
- 调试遥测下可见 `avgAgg` 上升 + `avgCoop` 下降，对应**短视夺利递进律**与无外部约束时的**霍布斯丛林**轨迹

### 已调通的平衡点（基准 seed=42 / 99）

- 初始 80 个体 → ~150–240 稳态
- 典型轨迹：合作者先扩散 → 攻击者通过选择接管 → 平均 `aggression` 由 ~0.5 升到 ~0.75
- 偶发的"合作繁荣-崩溃"脉冲（如 seed=42 的 t≈750 爆 2000+ 后回稳）属于涌现动态，不视为 bug

### 调参入口

集中在 `game/adversarial_evolution.py` 顶部：

- `INIT_POP` / `INIT_FOOD` / `FOOD_TARGET` / `FOOD_SPAWN_PER_TICK` —— 生态承载
- `MAX_ENERGY` / `START_ENERGY` / `METAB_BASE` / `METAB_SCALE` —— 个体能量学
- `REPRO_BASE` / `REPRO_SCALE` 与 `_agent_act` 末尾的 `0.05` 概率 —— 繁殖闸门
- 攻击/分享阈值在 `_agent_act` 内 inline