---
name: seewo-courseware-factory
description: 希沃课件工厂——把一份「简报 JSON」端到端做成可上云的希沃白板原生课件（.enbx）：落稿 → 插教学视频 → 分组 → 注动效 → 发布上云，并用本地/云端逐页核验兜底。补齐官方 seewo-easinote-assistant-skill 的四块空白（像素坐标、插视频、动效、副本治理）。当用户说"做希沃课件""把这份教案做成希沃白板课件""给课件插视频/加动画""课件上云/同步到希沃""第X课课件"时使用。上游接「国家智慧中小学教材提取」（smartedu-textbook-organize），本技能不下载教材。
agent_created: true
---

# 希沃课件工厂（seewo-courseware-factory）

**一句话**：写一份只含内容、零坐标的 **简报 JSON** → 本技能产出**可上云的希沃原生 `.enbx`**（含视频 / 分组 / 动效），并保证**云端同名课件恒 1 份**、本地与云端**逐页一致**。

> 本技能**不替代**官方 `seewo-easinote-assistant-skill`，而是站在它肩上补四块它没有的能力：
> 像素级版式（官方明说"不给坐标"）、**插视频**、**动效注入**、**云端副本治理 + 逐页验收**。

---

## 一、先读什么（不要一次读全部）

| 当前任务 | 必读 | 按需读 |
|---|---|---|
| 第一次做 / 从零起 | 本文件全部 + `references/00-上游-教材准备.md` | `01-版式库.md` |
| 写简报 brief（只写内容） | `references/01-版式库.md` | `assets/briefs/第8课-蚕的一生.json`（最新样例） |
| 配动效 / 分组 | `references/02-动效能力边界.md` | `assets/examples/group.example.json`、`anim.example.json` |
| 插视频 | `references/03-插视频SOP.md` | — |
| 上云 / 删云端副本 | `references/04-上云与副本治理.md` | — |
| 验收 / 报错了 | `references/05-验收与排障.md` + `07-踩坑总表.md` | — |
| 换字体 | `references/06-字体.md` | — |

## 二、前置依赖（分享给其他教师时，先让对方逐条确认）

| # | 依赖 | 缺了会怎样 | 怎么装 |
|---|---|---|---|
| 1 | **Windows + 希沃白板客户端**（已启动并登录） | 7916 端口不通，落稿/发布全失败 | 官网下载安装并登录 |
| 2 | **官方 skill** `seewo-easinote-assistant-skill` | 落稿 `build_v2` 找不到 | 从技能市场安装 |
| 3 | Python 环境含 `pymupdf / Pillow / opencv / python-docx` | 取图、版式几何校验跑不了 | 见 `scripts/seewo_config.py` 自检 |
| 4 | 字体：**默认系统雅黑**（零授权风险） | 无 | 汉仪为**可选增强**，需自行装（见 `hanyi-font-library` skill） |

跑一次自检确认本机就绪：

```bash
python scripts/seewo_config.py      # 6 项全 OK 才能开工
```

---

## 三、一条流水线（核心）

> 📌 **路径约定**：下文 `scripts/…` 均指**本技能目录**下的 `scripts/`（安装后即 `~/.workbuddy/skills/seewo-courseware-factory/scripts/`）。
> 命令里的 `{课}/…` 是相对 **`SEEWO_HOME`（现役工作目录，默认 = 运行时 cwd）** 的路径；**开工前先 `cd` 到你的课件工作目录**（本机即 `…/02-课件/希沃白板/`）。

**开发主场**（即现役工作目录）下建一套产物目录：

```
{课}/                     ← 例如 第8课-蚕的一生/
├─ 配图/                  ← 教材插图（上游产出）
├─ {课}.enbx              ← 干净源（落稿产出，无视频无动画）
├─ v2/
│   ├─ group.json         ← 分组计划（可省）
│   ├─ anim.json          ← 动效计划（可省）
│   └─ pipeline.json      ← 一条流水线配置
└─ {课}-含视频.enbx        ← 终版（含视频/分组/动效）
```

### 阶段 0（前置）：简报 → 干净源 enbx

```bash
# ① 简报 JSON（只写内容）→ pages.json（版式库补全像素坐标 + 技能校验）
python scripts/版式库/make_deck.py --brief "{课}/brief.json" --out "{课}/v2/pages.json"

# ② 几何自检（6 项应为 0 问题）
python scripts/版式库/check_geometry.py --spec "{课}/v2/pages.json"

# ③ 落稿成 .enbx（--no-sync：只本地落稿，不上云）
python scripts/run_build_v2.py --spec "{课}/v2/pages.json" --no-sync
```

### 阶段 1–4：一条命令跑完（顺序不可换）

写 `{课}/v2/pipeline.json`：

```json
{
  "src":   "第8课-蚕的一生/第8课 蚕的一生.enbx",
  "out":   "第8课-蚕的一生/第8课 蚕的一生-含视频.enbx",
  "name":  "第8课 蚕的一生-含视频",
  "video": { "path": "../课件/四年级上册-第2单元-生命的延续/视频/u2-l08.mp4", "page": "last",
             "title": "看一看：蚕的一生", "sub": "观察蚕的四个阶段：卵 → 幼虫 → 蛹 → 成虫" },
  "group": "第8课-蚕的一生/v2/group.json",
  "anim":  "第8课-蚕的一生/v2/anim.json",
  "publish": { "cleanup": true }
}
```

```bash
python scripts/seewo_build.py "{课}/v2/pipeline.json" --dry-run    # 先空跑校验
python scripts/seewo_build.py "{课}/v2/pipeline.json" --publish    # 真跑 + 上云
# 单步：--only group / --from anim   只跑某步 / 从某步到尾
```

流水线内部顺序（**不可换**）：

```
① 插视频 enbx_video  → ② 分组 enbx_group  → ③ 注动效 enbx_anim  → ④ 发布 publish_courseware
   整页重写，必须最先        就地改 XML          就地改 XML         先清同名旧副本再上传
```

> 🔴 **为什么视频必须最先**：`enbx_video` 会**整页重写**（归一化外壳），分组产生的 `<Group>` 嵌套经不起它重写；而分组/动效只做就地 XML 编辑，不碰视频。

### 阶段 5（后置）：验收

```bash
# 本地 enbx vs 云端回读，逐页比对（元素 / 动画 / Group / 视频 / 活动）；差异页应为 0
python scripts/_verify_v2.py "{课}/{课}-含视频.enbx" \
  "%APPDATA%/Seewo/EasiNote5/Data/<账号>/Courseware/<localId>"

# 截图验收（绝对路径！）
python scripts/enbx_shot.py "{课}/{课}-含视频.enbx" --out "{课}/预览" --mode Edit
```

---

## 四、四个必须记住的铁律

1. **顺序**：视频最先，分组居中，动画最后，发布收尾。
2. **一个元素只能留 1 条动画**：同一元素写多条 → 上云后**只留第一条，其余静默丢弃**。
   "面板先进入、文字后强调"必须**拆成两个元素**（Shape 挂进入 / Text 挂强调），这类页 **group.json 里不要分组**。
3. **"多个元素一次点击同时动"唯一正解 = `<Group>`**：把元素包进 Group，只给 Group 挂动画。
   ❌ 相同 `<Number>` 会被重编号；❌ `WithPrevious` 会让**整份课件加载失败**。
4. **两个"炸整份课件"的雷**（XML 合法、解析器查不出、真机打开才炸）：
   - `Trigger=WithPrevious` → 整份 `slideCount=1`
   - `<Magnitude>Large</Magnitude>` → 同样加载失败（强度只能 `Medium` 或缺省）

> 定位动画目标用 **`index`**（分组后逐页 `enbx_dump` 核对），**别用 `match`**——`match` 在 Group 存在时会优先命中整组，挂错元素。

---

## 五、配置（`scripts/seewo_config.py`）

所有路径/账号**不写死在代码里**，优先级：显式参数 > 环境变量 > `seewo_config.json` > 自动探测。

| 环境变量 | 含义 | 默认 |
|---|---|---|
| `SEEWO_HOME` | 现役工作目录（pipeline 相对路径的基准、产物落点） | 当前工作目录 |
| `SEEWO_SKILL_DIR` | 官方 seewo skill 根目录 | 自动扫 `~/.workbuddy/skills` |
| `SEEWO_ACCOUNT` | 希沃账号（云缓存目录名） | 扫 `%APPDATA%\Seewo\EasiNote5\Data` |
| `SEEWO_EASINOTE_EXE` | `swenlauncher.exe` 绝对路径 | 注册表 → 常见安装路径 |
| `SEEWO_PYTHON` | 带 pymupdf/PIL/cv2/docx 的解释器 | 托管 `default` 环境 |

---

## 六、上云与副本治理（含删除前置闸门）

**根因**：每次「本地 enbx → 打开 → 同步」都**新建 remoteId**，`<UpstreamId>` **不覆盖**旧记录 ⇒ 云端同名副本越积越多。

**正解**：发布前用 GUI **删掉云端同名旧副本**，再上传 ⇒ 云端恒 1 份。
工具 `scripts/publish_courseware.py`（`--cleanup` / `--yes` / `--clean <名>` / `--verify <名>`）。

> 🔒 **删除前置确认闸门**（本技能铁规，脚本**不自作主张**）：
> ```
> ① 扫描（只读）→ 列出全部同名副本：localId / 时间
> ② 用户确认     → 逐条选"删/留"，没勾的一律当"留"
> ③ 只删确认的   → 每删一个回报结果，失败就停
> ```
> **实现**：`--cleanup` **默认只扫描、不删也不上传**；必须显式加 `--yes` 才执行删除并上传。
> 保护名单：环境变量 `SEEWO_NEVER_DELETE`（逗号分隔）或 `scripts/never_delete.txt`（每行一个），命中即拒绝。
> ⚠️ 按 `localId` 逐条删**暂不支持**（GUI 删除器按**课件名**匹配列表行）——同名副本只能整体删或整体留；
> 需保留一部分时按名字区分（`--clean <名>`）。

```bash
python scripts/publish_courseware.py "<enbx>" --cleanup          # ① 只扫描列候选（不删、不传）
python scripts/publish_courseware.py "<enbx>" --cleanup --yes    # ② 确认后：删同名 → 上传
python scripts/publish_courseware.py --clean "<课件名>"           # 只删指定课件（进回收站）
```

> 流水线里由 `pipeline.json` 的 **`publish.cleanup`** 控制：**缺省 false（不清理）**；写 `true` 即视为**已授权**，
> `seewo_build.py --publish` 会带 `--yes` 执行清理。即：**不写就不删**。

---

## 七、交付前检查清单

- [ ] `seewo_config.py` 自检 6 项全 OK
- [ ] `check_geometry.py` 0 问题；`make_deck.py` 技能校验通过
- [ ] `seewo_build.py --dry-run` 动画全部命中
- [ ] 终版页数 = 源页数 + 1（视频页追加为**最后一页**，前面元素 index 不变）
- [ ] `_verify_v2.py` 差异页 = **0**（单页 Group 子计数差 1 是**良性**，判通过）
- [ ] 云端 `--verify <名>` 份数 = **1**
- [ ] 终态停在**备课（Edit）模式**，不进授课模式

---

## 八、排障决策树

```
课件打开异常 / 页面全丢
  └─ 查动画：Trigger=WithPrevious？Magnitude=Large？  → 03/02 分册
云端副本堆积
  └─ 走删除前置闸门（04）
"动画全部错位"
  └─ 假象：缓存文件名 Slide_<N>_<stamp> 字典序排乱 → 按 Board_*.xml 的 <Item> 顺序对齐（05）
落稿/发布失败
  └─ 7916 探不到？先 unset 代理变量，再确认客户端已登录（07 一节）
分组被毁 / 动画消失
  └─ 顺序错了：视频没放到最前（03）
```

速查全表见 `references/07-踩坑总表.md`。

---

## 九、维护：开发主场 → 发布快照 → 安装

```
① 开发主场  现役工作目录/*.py          ← 你日常改脚本的地方
② 发布快照  <skill>/scripts/*.py       ← 稳定版（随技能分发，独立可跑）
③ 已安装    ~/.workbuddy/skills/seewo-courseware-factory/
                     ↑ _sync_check.py 负责 ①→② 比对/快照，②→③ 一键安装
```

```bash
python scripts/_sync_check.py              # ①↔② 只报告 sha256 差异
python scripts/_sync_check.py --check      # ①↔② 有差异 → 退出码 1（发布前把关）
python scripts/_sync_check.py --snapshot   # ①→② 打快照，写 scripts/_SNAPSHOT.json
python scripts/_sync_check.py --install    # ②→③ 安装到用户级 skills（含 _INSTALL.json）
python scripts/_sync_check.py --install --install-dir <目录>   # 自定义安装位置
python scripts/_selftest.py                # 导入自检（改完脚本先跑这个）
```

**约定**：平时改**①现役目录**；要发布时 `--snapshot` 打好②快照，再 `--install` 刷新③。
`_SNAPSHOT.json` 记录日期 + 每文件 sha256 + 配对官方 skill 版本；`_INSTALL.json` 记安装时间 + **版本** + 来源 + 文件清单。
**安装只发「发布物」**（`SKILL.md` / `README.md` / `VERSION` / `CHANGELOG.md` / `自检.bat` / `references` / `scripts` / `assets`），**不发 `_规划/`**。

### 版本号与分享包（作者侧）

| 文件 | 作用 |
|---|---|
| `VERSION` | **版本号唯一真相源**（单行，如 `1.0.1`） |
| `CHANGELOG.md` | 每个版本「改了什么 / 要不要重装」，倒序 |
| `_INSTALL.json → skill_version` | 教师机上的已装版本，用来比对是否有新版 |

一条命令发新版（升版本 → 写日志 → 刷快照 → 重生成自检.bat → 打包 → 校验 → 安装）：

```bash
python _规划/发布.py --bump patch --note "修了 X" --note "改了 Y"
python _规划/发布.py --keep-version --docs-only --note "只改了 README"
python _规划/发布.py --version 1.2.0 --note "新版"  --no-install
```

产出：`分享-希沃课件工厂/希沃课件工厂-分享包-v<版本>-<日期>.zip`（包名版本读自 `VERSION`）。
教师侧收到新包**覆盖整个文件夹**即可（幂等，不碰对方的成果课件）；若改了 `description` / 触发词，需重启客户端重载。

**旧版本留存与清理**（发新版不丢旧包，等新版稳定再删）：

```bash
python _规划/发布.py --releases                 # 列出所有历史版本（★最新 / 位置 / 大小）
python _规划/发布.py --prune --keep 2           # 预览要清理哪些
python _规划/发布.py --prune --keep 2 --yes     # 真删（送回收站，可恢复）
```

- 每次发布**自动把旧包移进 `分享-*/_历史/`**，分享目录根部永远只留最新一版（直接取用不挑）；
- 发布结束自动打印一段**可直接复制**的「发给教师的更新通知」文案（版本 / 改动 / 覆盖三步 / 不丢数据声明）；
- `--prune` 默认只预览，`--yes` 才真删，走 **Windows 回收站**，可恢复。

---

## 十、边界（本技能不做什么）

- ❌ **不下载教材、不解析平台** → 交 `smartedu-textbook-organize`（「国家智慧中小学教材提取」）
- ❌ **不生成"单文件 HTML 互动课件"** → 那是 `textbook-unit-courseware` / `teachany`，另一种产物
- ❌ **不带字体文件、不带个人成果课件、不带账号与机器路径**（分享范围见 `_规划/01-方案决策记录.md`）
- ✅ 只做：**简报 → 希沃原生 enbx（含视频/分组/动效）→ 上云 → 验收**

---

## 附：目录索引

| 路径 | 内容 |
|---|---|
| `README.md` | **面向人**的安装与上手说明（发给其他教师先看这份） |
| `references/00–07` | 8 份知识分册（上游衔接 / 版式库 / 动效 / 插视频 / 上云 / 验收 / 字体 / 踩坑） |
| `scripts/` | 22 个 Python 工具 + 1 个 PowerShell（云删除驱动）+ `版式库/` |
| `assets/briefs/` | 3 份样例简报（第6/7/8课） |
| `assets/examples/` | pipeline / group / anim 三个 JSON 示例 |
| `_规划/` | Phase0 资产盘点 · 方案决策记录 · Phase2 脚本入位报告（**内部件，不随安装分发**） |
