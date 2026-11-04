# GUOXUE｜八字手环概念与 Part1 规则研究

> **GitHub 全量上传进行中。** 当前 main 先提供当前代码、研究入口和小文件；全部历史分卷仍在校验，Release 尚为草稿。原研究验收100%与本次上传进度分别记录。附件和完整恢复清单通过核验后会更新此提示。

这里保存两个相关项目：桌面项目中的 App 界面概念图、生成提示词、文化合作纪录片演示材料与制作素材；以及 Part1 命理规则研究的现行交付、来源材料、运行代码和本次上传时仍可取得的完整研究目录历史。

研究工作优先。App 图片是界面概念稿；新增手环显示、个人基础主题接合和物理呈现仍属后续工作。本仓库不表示已经完成可发布的 App 或实物手环。

## 先读哪里

恢复现行资料后，建议按这个顺序阅读：

1. `research/研究成果总览.txt`：研究做了什么、结论和边界。
2. `research/最终验收与使用说明_rev624.txt`、`research/当前研究与接续入口_rev625.txt`：最终验收与当前状态。
3. `research/part1-final/00_0_当前有效入口_请先读_r1.txt`：285 个永久交付文件的现行入口。
4. `research/part1-final/研究阅读/00_研究导航/95方法_逐规则与算法阅读导航.txt`：按具体方法查规则、算法、来源及示例。
5. `research/规则运行与完整算例_rev626.txt`：用较直白的语言说明规则怎样运行。

`DELIVERY_MANIFEST_r1.json` 与 `DELIVERY_FREEZE_r1.json` 对应现行 285 个永久交付文件。较早清单、旧说明与旧进度按原字节保留；文件名中较旧的 `pending`、`98.75%` 或旧收件报告不应当作当前结论。rev624 的外部最终验收 ZIP、rev625 当前状态与 rev626 讲解不属于这 285 件，但本次也一并收录。

## 研究结论的含义

原任务按约定范围的研究交付验收为 **100.00/100**。这个数字表示交付与验收完成，**不是命理预测准确率，也不是现实作用已被证明**。资料来源核对、规则实现正确性与现实预测验证分别记录；现实预测验证没有因此增加。

登记的 95 个方法各自保留原精确版本、请求合同、适用范围、来源、反例和限制。它们不应混成统一投票，也不表示任意八字已有公认唯一答案；并非全部方法都已自动接到个人主题或相同时间能力。象征份额、权重和阈值中有明确的工程约定，应按原文、后注、现代解释、工程推导的来源层次阅读。

首次来源收件报告存在实质遗漏；现行 r1 修复了 379 条路径并重新核对全 95 原清单的 49,419 条路径。旧错误回执保留作历史，最终完整性应以 r1 及 rev624／625 的证据为准。关于范围、阴性结果、未知结果及证据复用的精确说明，均以原交付文件为准。

## 克隆与大资料恢复

Git 仓库主要提供代码、说明和较小文稿。**只执行 `git clone` 不会获得全部大资料。** 大文件与现存全历史放在公开 [Release `part1-complete-2026-11-04`](https://github.com/ysun5-byte/GUOXUE/releases/tag/part1-complete-2026-11-04)，由逐路径清单和 SHA-256 校验关联；按内容去重和分卷只减少存储与传输，不会删除重复的原路径。

使用 Python 3.9 或更新版本，不需要额外安装 Python 包。先恢复现行交付到一个新目录：

```bash
git clone https://github.com/ysun5-byte/GUOXUE.git
cd GUOXUE
python3 tools/restore_project.py --scope final --root ../GUOXUE-restored
python3 tools/restore_project.py --scope final --root ../GUOXUE-restored --verify-only
```

`final` 包括桌面项目、285 件现行交付及最终说明与外部验收材料。默认恢复范围也是 `final`；省略 `--root` 时恢复到脚本所在仓库。上面的命令显式选择新目录，便于保留已有工作并单独验收。恢复后的目录与下方路径表对应；后续运行命令应在恢复后的目录执行。

需要逐路径恢复本次仍然存在的旧研究目录时，使用 `history`；需要连同桌面项目与现行阅读副本一起恢复时，使用 `all`：

```bash
python3 tools/restore_project.py --scope history --root ../GUOXUE-restored
python3 tools/restore_project.py --scope all --root ../GUOXUE-restored
python3 tools/restore_project.py --scope all --root ../GUOXUE-restored --verify-only
```

全历史按原路径恢复后需要很大的磁盘空间：原目录约 156 GB，还需要下载缓存和恢复过程中的临时空间；实际字节数以清单统计为准。相同内容的多个原路径会各自恢复为文件，因此去重后的下载体积不能当作恢复后体积。建议先用 `final`，确实需要审计旧版本时再选全历史；无需在旧项目所在电脑另复制一份全历史。

`--cache /其他磁盘/guoxue-cache` 可指定下载缓存位置；默认缓存位于恢复根目录的 `.restore-cache`。缓存中的分卷经过整包 SHA-256 与尺寸校验，恢复 ZIP 成员或拼接分片后还要再核原文件的 SHA-256 与尺寸。文件以二进制方式流式恢复，PDF、Markdown、JSON、ZIP 和原冻结清单均不转码、不改换行、不重新打包。相同下载分卷在一次运行中只获取一次，已验证缓存可继续复用。

已存在且摘要正确的文件会跳过；同内容的正确副本也可用于补回另一条原路径。发现已有文件或缓存损坏时，工具会明确失败，只有显式添加 `--replace-invalid` 才会替换错误的普通文件／缓存。中断后可使用相同命令重试。上传断点以完整分卷为单位；失败的当前分卷会重传，已经完整校验的分卷会复用。`--verify-only` 只检查本地恢复结果，不下载、不写文件。

目的路径中的绝对路径、`..`、反斜杠和已有父级软链接会被拒绝。原目录和文件权限会恢复，目录只读权限在文件全部恢复后才设置。软链接的原目标文字和摘要始终保留在清单中；默认不创建链接，跳过记录另写入缓存的 `skipped-symlinks.jsonl`。显式使用 `--restore-symlinks` 只会建立留在恢复根目录内的安全相对链接。原 `node_modules` 指向外部缓存的绝对链接不会自动重建，也没有遍历或上传其外部缓存内容。

## 路径怎样对应

旧研究根目录是：

```text
/Users/yuanfeisun/Documents/Codex/2026-11-01/00-01-part-1-23
```

| 原资料位置 | 恢复目录中的位置 |
| --- | --- |
| 桌面“八字手环”项目的原相对路径 | 同一个相对路径，例如 `output/app-concept/`、`output/文化合作与科学探索纪录片/`、`work/culture-module/` |
| 旧根目录下的所有现存相对路径，包括旧版本、失败与修正记录、可重新生成的 `prepared_runtime` | `research-history/part1-2026-11-01/原相对路径` |
| `outputs/Part1_研究成果_统一可复现交付/` 中现行永久清单的 285 件 | `research/part1-final/原相对路径` |
| `outputs/研究成果总览_先读这一份.txt` | `research/研究成果总览.txt` |
| `outputs/Part1_研究成果_最终验收与使用说明_rev624.txt` | `research/最终验收与使用说明_rev624.txt` |
| `outputs/Part1_最终验收与独立复核记录_rev624.zip` | `research/最终验收与独立复核记录_rev624.zip` |
| `outputs/当前研究与接续入口_rev625.txt` | `research/当前研究与接续入口_rev625.txt` |
| `outputs/整套规则怎么运行_大白话与完整算例_rev626.txt` | `research/规则运行与完整算例_rev626.txt` |

历史文档里原有的绝对路径不作文字替换，以免改动被冻结的证据。阅读这些路径时，按上表把旧根目录替换为 `research-history/part1-2026-11-01/` 即可找到保留副本。现行交付有独立的相对运行入口，不依赖原机器的绝对路径。

`manifests/project-files.jsonl.gz` 保存每条原路径、范围、字节数、权限和摘要；`directories.jsonl.gz` 保留空／非空目录及其权限和时间；`objects.jsonl.gz` 关联内容对象与 ZIP 成员或有序分片；`release-assets.json` 列出下载地址、分卷尺寸与摘要。这些清单说明本次上传时实际存在并保存了什么。

`manifests/manifest-checksums.json` 对上述四件清单分别固定原文件字节数和 SHA-256，由仓库提交与发布验收记录锚定，不是数字签名。恢复器首先要求四件全部存在且摘要一致，然后才读取路径和开始恢复；`--verify-only` 也遵守同一检查。即使某个文件仍是合法 gzip／JSONL，只要意外少了一条路径或混入另一版目录／对象表，也会先失败，不能按缩水清单报告完整通过。发生清单不一致时，应重新取得同一提交的整套清单。

## 运行现行规则与读取原件

先完成 `final` 恢复，然后进入现行交付目录：

```bash
cd ../GUOXUE-restored/research/part1-final
python3 -I -B research_files_effective_r1.py list-reading
```

当前资料读取默认使用 `research_files_effective_r1.py` 与 `research_catalog_effective_r1.json`。原 `research_files.py`、旧 catalog 及早期说明中的旧读取命令仍保留历史，不应用它们代替当前完整读取器。具体资料键可用当前读取器查看或提取到交付包以外的位置：

```bash
python3 -I -B research_files_effective_r1.py show 资料键
python3 -I -B research_files_effective_r1.py extract 资料键 /包外/目标文件
```

运行规则前，按 `route_manifest.json`、`当前95方法_运行与来源登记.json` 和 `integration_tests/` 选择精确方法及版本，填写该方法自己的 `native_request`。统一请求恰含 `schema_version`、`route_id`、`native_request` 三个字段，schema 版本为 `v1-capability-entry-research-0.8`。准备好实际请求文件后运行：

```bash
python3 -I -B v1_entry.py /包外/请求.json
```

首次运行按固定卷恢复所选组件的 `prepared_runtime` 缓存，无需同时展开全部方法。已有错误组件会被拒绝，不能自动换版本掩盖错误。`entry_status=executed` 只表示原生调用完成；应继续阅读完整报告中的成立条件、来源、功能和未知原因。恢复资料需要联网；恢复完成后的核心读取与规则运行不需联网，也不需访问旧项目目录。详细操作以 `00_0_当前有效入口_请先读_r1.txt` 和 `01_运行与复现说明.txt` 为准。

## 永久保留的历史局限

本次归档保存上传时仍可取得的原目录全部路径；**不宣称所有历史文件的每一个旧字节、全部聊天或工具输出都曾保存下来**。两份早期可变“来源索引_current”导航快照在本次上传前已失存：

| 原尺寸 | 原 SHA-256 |
| --- | --- |
| 8,045 字节 | `fc96b8778abb9424b8194272c190fcd33e35c355f12cf4ae0048010dcf5eec18` |
| 6,309 字节 | `afaba15002c8a635157725509dfa70c55ef0c6d245957569c1e9315a5a142eb0` |

原指针、查找记录、失败恢复候选和后来实际保存的快照均按现状保留，不能拿新版索引、占位文件或候选复原冒充上述原件。当前读取器对这两个摘要明确拒绝并报告 `historical_navigation_snapshot_bytes_unavailable`。它们不作为已采用规则、代码、参数或必要运行输入输出的唯一依赖；这一狭义历史限制不能豁免实际来源补收。

另有早期操作回执曾被后次元数据编译覆盖，旧文件名不能认证首次执行前的不可变时间戳；其说明和后来的有效证据原样保留。全历史恢复也不能还原本机已经不存在的旧字节。

## 来源与使用权

本项目包含第三方古籍、论文、数据和其他来源材料。它们的原来源、版本、引用与已有许可证随材料保留，各自权利仍归相应权利人；公开存档不等于把所有内容改为自由许可。本仓库不为全部材料追加统一 MIT 许可证，也不把收录材料声称为全部原创。复用时请逐项核对原来源、许可及适用条件。
