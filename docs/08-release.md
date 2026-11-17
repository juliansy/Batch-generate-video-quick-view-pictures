# 发布前检查（Release checklist）

这个文件是给"要打 tag 的人"看的，也是 `tools/release_check.py` 的说明书。

## 为什么要它

每一条检查都对应一次真实事故：

| 事故 | 现在由谁拦 |
|---|---|
| 示例输出写着 `qvp 2.9.5`，二进制是 2.9.6，而 2.9.5 从未发布 | `V3` |
| `docs/07` 的用例数连续四轮写错（57 → 64 → 96 → 102） | `T2` |
| README 选项表还列着已删除的 `--hwaccel` | `F1` |
| 中英文 README 的章节顺序/层级漂移 | `H1` |
| 只对写代码的人有意义的措辞进了公共仓库 | `I1` |
| 真实片名、个人目录路径进了公开文件 | `P1` |
| 补丁脚本把 `qvp.bat` 改成 LF，打进 zip 上传 | `N1` / `N2` |
| CHANGELOG 跳号 2.9.2、又记了没打 tag 的 2.9.5 | `K1` |
| zip 里的 README 还是上一版 | `V5` |

## 一条命令

```bat
python tools\release_check.py
```

要连发布包一起验：

```bat
python tools\release_check.py --package video-quick-view-2.9.8.zip
```

打包用 `python tools\make_package.py`：它按固定清单打 zip，拒绝把非 CRLF 的 `qvp.bat` 静默修好，然后自动跑一遍 `--package` 检查。

退出码 0 才允许打 tag。`--skip-tests` 只跑文档类检查，用于改文案时的快速迭代，**不能**用于发版。

## 它检查什么

| 代号 | 检查 |
|---|---|
| `V1` | `qvp.py` 里的 `VERSION` |
| `V2` | `qvp --version` 的输出与 `VERSION` 一致 |
| `V3` | 中英 README 的示例输出首行与二进制一致 |
| `V4` | `CHANGELOG.md` 第一条版本号与当前版本一致 |
| `V5` | 发布包里的 README 示例也是当前版本 |
| `T1` | 测试真的跑通 |
| `T2` | 当前文档里每一处"NN 个用例"都等于实际用例数（历史记录类文档不参与） |
| `F1` | 解析器里的每个参数都在 README 选项表里，反之亦然 |
| `H1` | 中英 README 的二级/三级标题数量、层级、顺序一致 |
| `I1` | 公共文档里没有只对写代码的人有意义的措辞（禁用词表见脚本里的 `INTERNAL_VOICE`） |
| `P1` | 没有个人目录路径或真实素材标题（`D:\Videos` 是文档里的占位符，放行） |
| `N1` | `*.py`/`*.md` 是 LF，`*.bat` 是 CRLF |
| `N2` | 发布包里只有一个顶层目录、`qvp.bat` 是 CRLF、能跑 `-V` |
| `N3` | 必需文件齐全 |
| `K2` | 每个 tag 都有对应的 CHANGELOG 条目 |
| `K3` | 在解压出来的发布包里也能跑通（`N3` 只要求 checkout 里的 `.gitignore`/`.gitattributes`，`K1` 在无 `.git` 时降级为提示） |

## 它检查不了什么

工具能查"字符串对不对"，查不了"这句话是不是真的"：

- 示例输出里的耗时、尺寸是否来自真跑；
- 同一件事在中英文里是否同样诚实；
- 某个限制到底是"写清楚了"还是"藏起来了"；
- release note 有没有替自己辩解。

这四条只能靠下面的人工清单。

## 人工清单（发版前逐条过）

1. 在干净目录用 README 里的两条命令重新生成示例，把输出**粘贴**进中英 README，不要手改数字。
2. 跑 `python tools\release_check.py`，全绿。
3. 打 zip，再跑 `--package`，全绿。
4. 解压 zip，`cmd /c qvp.bat -V`，再用包里的 README 走一遍"下载 → 出图"。
5. 读一遍 `CHANGELOG.md` 最后一条：只写"变了什么"，不写"我认为怎样"。
6. 读一遍 release note：英文半区不能有中文，中文半区不能机翻腔；两段都不该出现只对写代码的人有意义的话。
7. 检查 GitHub 页面的 about/topics 是否还准确。
8. 发布后下载一次资产，核对 sha256 与本地一致。

## 例外怎么处理

确实需要保留的措辞，写进 `tools/release_allow.txt`：

```text
docs/05-test-report.md|<短语>|v1→v2 重写期的历史记录，顶部有横幅说明
```

格式是 `文件|短语|理由`。没有理由的例外一律不接受——例外的理由本身也会进版本库，被下一个人看到。
