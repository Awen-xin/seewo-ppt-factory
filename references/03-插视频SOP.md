# 03 · 插视频 SOP（文件层下沉）

> 一句话结论：**官方希沃技能没有"插视频"能力，但下沉到文件格式层已端到端打通。**
> 核心原理：`.enbx` 只是普通 ZIP，`<Video>` 本来就是合法的幻灯片元素，客户端认得它。

---

## 一、为什么不能"直接"插

希沃本地 MCP（`http://127.0.0.1:7916/mcp`，共 61 个工具）把所有"正规路"都堵死：

| 尝试过的路 | 结果 |
|---|---|
| MCP 有没有 `add_video_element` | **没有**。增元素只有 text/image/shape/table/mindmap/poem/wordcard/hanzi/pinyin/ruled/plot/activity 共 **13** 个 |
| 两个 `generate_video_from_*` 工具 | 是"**用课件生成讲稿视频**"，方向相反 |
| `RenderSlideML` 写 `<Video>` / `<Media>` | 报「**未知标签，已忽略**」。SlideML 只认 `Page` / `TextElement` / `Image` |
| `set_element_properties` 造视频元素 | 属性组只有 layout/图片/文本/形状/slide，**没有 media/video 组** |
| `add_image_element` 传 mp4 | 报 `File extension mp4 is not registered for PictureAdapter` |
| PPTX（`add_movie`）→ `new_cloud_courseware_from_pptx` | 视频被**拍平**，导入后 1 页 0 元素 |
| 直接改**云课件**缓存注入 `<Video>` | 云课件一打开就**重新下载覆盖**，注入被删 |

**唯一可行**：自造含真实 `<Video>` 的**本地** `.enbx` → 以「本地课件」打开 → 再触发云同步。
本地课件不会被云端回灌覆盖。

---

## 二、活路径

```
自造含 <Video> 的本地 .enbx
        │  os.startfile()  ← 关键：以「本地课件」打开（不是 ensys_open_file）
        ▼
客户端加载为本地课件，视频元素在（get_elements 返回 type:"Video"）
        │  不被云端回灌覆盖（本地课件天生不受影响）
        ▼
sync_current_courseware  →  上云，返回「课件云端 ID：<guid>」
```

三个决定成败的细节：
1. **必须 `os.startfile()`**，不能用 `ensys_open_file`（后者报"不是有效的应用程序"）。
2. **页面外壳要归一化**：直接打包客户端缓存的 `Slide_N.xml`（带动画扩展、`ThemeId=12`）会弹
   "部分元素无法解析"且**只加载 1 页**；改写成干净外壳（丢动画扩展、`ThemeId=-1`）才正常。
3. **同步前必须等加载完**：shell 一注册就有返回，但 10MB 的视频页还没落位，此时读到**空页**，
   会把空视频页推上云。

---

## 三、先判断属于哪种情况

```
要给一个希沃课件加本地视频
├─ 课件是「本地 enbx 文件」        → --src 指向它
├─ 课件是「已打开的（云/本地）课件」 → --src current（按名+大小反查缓存）
└─ 课件是「从零新建」              → 先用 build_v2 生成 enbx，再注入视频
```

> ⚠️ **顺序铁律**：视频注入要放在**课件内容定稿之后**（它生成一个新的课件文件）。
> **先插视频、再改课件是错的。**

---

## 四、标准 6 步

| 步骤 | 动作 | 要点 |
|---|---|---|
| 0 前置 | 打开希沃客户端并登录；**清代理** | `unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY all_proxy` |
| 1 定源 | 确定母本课件 | 目录 `.enbx` / 缓存目录 / `current` 三选一 |
| 2 定视频 | 确认 mp4 路径 | 建议 H.264，兼容性最好 |
| 3 生成 | 跑 `enbx_video.py` | 自动做外壳归一化、资源重映射、同内容复用、孤儿剪枝 |
| 4 打开校验 | 脚本自动 `os.startfile` + 回读 | **页数齐 + 视频页元素达标 + 连续两次一致** 才放行 |
| 5 同步 | 加 `--sync` | 只认返回文本里的 `课件云端 ID：<guid>` |
| 6 验收 | 截图确认 + 清理旧版 | 云端**同名会撞车**，更新后必须删旧留新（见 `04-上云与副本治理.md`） |

### 一条命令

```bash
cd <skill>/scripts
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY all_proxy
"<PY>" enbx_video.py \
  --src current \
  --video "…/视频/u2-l06.mp4" \
  --page last \
  --title "看视频：植物的繁殖" \
  --sub "边看边想 —— 植物是用什么繁殖后代的？" \
  --name "第6课-植物的繁殖-含视频" \
  --sync
```

参数：`--src`（目录/`.enbx`/`current`）、`--page`（`last` 或页码 `N`）、`--title`/`--sub`、`--name`（云端名）、`--out`（输出路径）、`--sync`、`--no-open`。

> ⚠️ `--page last` 时视频被**追加为全新一页**（如 15 页 → 16 页），不是塞进最后一页。
> 好处：前 15 页的元素 `index` 在插视频后**保持不变**，group/anim 的 index 无需重算。

---

## 五、验收门禁（脚本已内置，人工复核照这个）

- [ ] 页数 == 母本页数（或 +1，取决于 `--page`）
- [ ] 视频页元素含 `Video`，且元素个数达标、**连续两次读取一致**
- [ ] 同步返回文本里出现 `课件云端 ID：<guid>`
- [ ] 截图里能看到播放器按钮 + 视频首帧

---

## 六、11 个坑（实测）

1. **必须清代理**：任一 `http_proxy` 变量在，7916 返回 502 假死；清掉后 405 = 服务活着（405 正常，裸 GET 不满足 MCP 握手）。
2. `tools_list()` 返回元组 `(rid, obj)`，真工具在 `obj['result']['tools']`。
3. **本地 enbx 的课件名 = 文件名**（去 `.enbx`），`Document.xml` 的 `<Name>` **被无视**。云课件名同取文件名。
4. **页面外壳必须归一化**（丢 `SlideAnimationExtension`、`ThemeId=-1`），否则只加载 1 页。
5. **`os.startfile()` 打开**，不能用 `ensys_open_file`。
6. **资源 ID ≠ 内容 md5**：自己写的用 md5；客户端保存后另分配随机 Id，真 md5 记在 `Reference.xml` 的 `<Hash>` ⇒ 要做 hash→Id 重映射。
7. **资源文件名带后缀**：缓存里是 `<Id>_S4410.xxxx.yyy.<ext>`，查找要按前缀兜底。
8. **`isSynced` / `isCloudCourseware` 都不能判断"上云成功"**：本地新课件 `isSynced` 一出生就 true；同步后 `isCloudCourseware` 仍 false、`remoteId` 仍 null。**唯一可靠信号** = 返回文本的 `课件云端 ID：<guid>`。
9. **刚打开就同步会被静默吞掉**（读到空页）。必须等页数齐 + 视频页元素达标 + **连续两次一致**才同步。
10. **同名云课件会撞车**：`open_cloud_courseware` 按名称**模糊匹配、取最近更新的**那份 ⇒ 废稿必须删（见 `04`）。
11. **没有删除云课件的 MCP 工具**（61 个里没有）⇒ 只能 GUI 删（见 `04`）。**每重跑一次脚本云端就多一份**（同一 enbx 重开也算新课件）。

---

## 七、`.enbx` 格式速查（= 普通 ZIP）

```
Document.xml        课件元信息（<Name> 被无视，实际用文件名）
Board.xml           <Slides><Item>页面Id</Item>…  决定页序
Slides/Slide_N.xml  页面，元素在 <Slide><Elements> 里；<Video> 合法
Resources/<Id>.<ext>  资源；视频/图片都在这
Reference.xml       <Id> → Resources\<Id>.<ext>，<Hash> = 内容 md5
SaveInfoMetadataFile.xml
thumbnail.png
```
所有 XML 带 UTF-8 BOM 写入。客户端用户数据：`%APPDATA%\Seewo\EasiNote5\Data\<你的希沃账号>\Courseware\`
（`CoursewareCacheData.db` 是 SQLite，记 LocalId/RemoteId/LocalRevision/SyncedRevision；每个 `<LocalId>\` 子目录就是该课件的 enbx 等价物）。
