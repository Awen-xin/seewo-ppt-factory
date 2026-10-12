# assets · 样例与素材

> 本目录只放**可分享的样例**，不含任何个人成果（第 N 课成品课件仍在现役目录）。

## `briefs/` —— 简报样例（3 份）

交给 `版式库/make_deck.py` 的输入，**只写内容、不写坐标**：

```bash
python scripts/版式库/make_deck.py --brief assets/briefs/第8课-蚕的一生.json --out <课名>/v2/pages.json
```

| 文件 | 说明 |
|---|---|
| `第6课-植物的繁殖.json` | 8 页，含 mindmap / match 活动页 |
| `第7课-种子的传播.json` | 页数最多的样例，含 photo_trio 等多图版式 |
| `第8课-蚕的一生.json` | 15 页，含 9 张教材配图 + 配对活动 |

简报字段与版式清单见 `references/01-版式库.md`。

## `examples/` —— 流水线三段输入示例

| 文件 | 对应步骤 | 关键点 |
|---|---|---|
| `pipeline.example.json` | `seewo_build.py`（总编排） | 四阶段顺序：video → group → anim → publish |
| `group.example.json` | `enbx_group.py`（②分组） | 一起动 → 打包 `<Group>`；提问页不分组 |
| `anim.example.json` | `enbx_anim.py`（③动画） | 一元素一动画；先进入+后强调要拆元素 |

> 三个示例里的 `index` 均为**示意**，实际必须用 `enbx_dump.py` 在**干净源**上逐页核对后再填。
> 完整规则见 `references/02-动效能力边界.md` 与 `references/07-踩坑总表.md`。
