# 05 · 测试报告

> 历史记录：本文写于 v1 → v2 重写期间，里面的行数、默认值和流程描述只反映当时的状态。当前行为以仓库根目录的 README 与 [06-auto-grid.md](06-auto-grid.md)、[07-performance.md](07-performance.md) 为准。


环境：Windows 10/11 · Python 3.12.10 · Pillow 11.3.0 · moviepy 2.1.2 · 系统 ffmpeg 7.1（gyan 完整版）
测试命令（仓库根目录）：

```text
python -m unittest discover -s tests -v
```

## 1. 自动化测试

64 个用例，全部通过，8 秒左右跑完。

| 分组 | 数量 | 覆盖内容 |
|---|---|---|
| 纯逻辑（无 I/O） | 18 | 网格解析与校验、采样时刻、时间码格式、布局几何、字体尺寸、扩展名、颜色、错误压缩、中文宽度对齐、报表汇总、参数校验、`--version` |
| 目录发现 | 2 | 排序、去重、递归、缺失路径与非视频文件 |
| 端到端（真实 ffmpeg + 真实视频） | 42 | 产物尺寸与时戳像素、跳过/覆盖、dry-run 零写入、坏文件隔离、帧数溢出、像素预算、递归、同名冲突、并发与日志、Unicode 文件名、缺失路径、ffmpeg 回退、静默模式、报表顺序、无效字体、输出目标是文件、超短视频、hms 格式、自动网格选档与像素降档、`--frames` 推导网格、坏 `--grid` 退出码、`-g` 短选项、重定向下的 emoji 文件名、`-n --log` 零写入、同一目录多种写法去重、帧尺寸不符、空报表、临时文件残留、格子内容互不相同 |

关键断言不是“有没有文件”，而是：

- 产物尺寸必须等于 `格数 × (源宽 + 2×白边)` 算出来的值；
- 左上角必须能找到红色像素（时间戳真的画上去了）；
- 第二次运行必须报告 `skipped: already exists` 且 mtime 不变；
- `-n` 之后 `sheets/` 目录必须不存在；
- 坏文件排在最前时，好文件仍然产出，退出码为 1；
- `9 帧放 2×2` 必须失败并给出 “do not fit a 2x2 grid”；
- 4K 级像素预算必须触发 `over the 1 MP limit`。

## 2. 实测对比

测试素材：`long.mp4`（1080p，19 分 34 秒，40 MB，AV1）+ `short.mp4`（1080p，60 秒）。

| 指标 | v1.1.0 | v2.0.0 | 变化 |
|---|---|---|---|
| 两个视频总耗时 | 19.8 s | **7.7 s** | 2.6× 更快 |
| 其中长视频 | — | 3.46 s | — |
| 其中短视频 | — | 3.33 s | — |
| 产物 | 7688×4328，2.1 MB | 7696×4336，2.4 MB | 白边 1→2 px，JPEG 质量 75→85 |
| 内存峰值 1080p | 303 MB | **207 MB** | 校验改为 1/8 解码 |
| 内存峰值 4K | 1,115 MB | **699 MB** | 同上，省下一整份画布 |

单文件 60 秒 1080p 的绝对数字（同一台机器）：

| 后端 | 耗时 |
|---|---|
| v1（moviepy 逐帧 seek） | 9.35 s |
| v2 + 系统 ffmpeg | **4.1 s** |
| v2 + moviepy 自带 ffmpeg | 8.6 s |
| v2 + 完全没有 ffmpeg（moviepy 兜底） | 8.6 s |

内存之所以没降，是实测推翻了设计假设：36 MP 画布 + JPEG 编码缓冲各占 100 MB（4K 各 400 MB），帧列表只占其中一部分，而且 moviepy 的帧缓冲会复用。这条写在 [03-design.md](03-design.md) §4.3 里，没有粉饰。

## 3. 正确性抽查

长视频产物的第一格与最后一格（从成品裁切，坐标 `(0,0)` 与右下格）：

| 位置 | 时戳 | 对应采样时刻 |
|---|---|---|
| 第 1 格 | `00:01` | 0.5 s（避开片头黑场） |
| 第 16 格 | `19:34` | 1174.42 s，影片总长 1174.47 s |

一共 16 格、4×4、画布 7696×4336，每格 1918×1082（源 1080p + 2 px 白边）。

## 4. 回归清单：v1 的每一个已知缺陷现在如何

| v1 缺陷 | 现在的行为 | 验证 |
|---|---|---|
| 坏文件中止整批 | 只该文件失败，其余继续，退出码 1 | `test_bad_file_does_not_stop_the_batch` |
| `NUM_FRAMES=0` 崩 | 参数校验拒绝（1..256），退出码 2 | `test_option_validation` |
| 帧数 > 格数静默丢帧 | 明确失败并说明格数 | `test_frames_that_do_not_fit_the_grid_fail_loudly` |
| 非原子写 | 临时文件 + 校验 + `os.replace` | `test_renders_a_grid_of_the_expected_size` 检查无残留 |
| 静默覆盖 | 默认跳过，`--force` 才覆盖 | `test_second_run_skips_and_force_rewrites` |
| 无汇总/无退出码 | 表格 + 汇总 + 0/1/2/130 | 全部端到端用例 |
| 顺序不可复现 | 按文件名排序 + 结果按输入序 | `test_finds_sorts_and_dedupes`、`test_report_numbers_stay_in_discovery_order` |
| 白边 1.25 被截成 1 px | `--border` 整数，默认 2 | `test_layout_geometry` |
| 字体缺失不可读 | 多候选字体 + 描边 + 自适应字号 | `test_unusable_font_fails_the_file_not_the_batch`（显式字体错时明确失败） |
| 每帧重复加载字体 | 每个视频一次 | 代码审查 |

## 5. 复现步骤

```text
git clone https://github.com/juliansy/video-quick-view
cd video-quick-view
pip install -r requirements.txt
python -m unittest discover -s tests -v
python qvp.py --frames 16 --grid 4x4 -n "D:\Videos"   # 先看计划
python qvp.py -R -j 4 "D:\Videos"                     # 再真正跑
```

## 5.5 v2.2 的启动与探测性能

v2.1 用 moviepy 读元数据，每个视频要 ~1 秒，30 个视频在出第一行表格前要等 15 秒以上。v2.2 改成 ffprobe：

| 指标 | v2.1 | v2.2 |
|---|---|---|
| 单文件探测 | 1019 ms（moviepy 打开 clip） | **70 ms**（ffprobe JSON） |
| 30 个视频的计划阶段 | 15.8 s | **2.3 s** |
| 首行输出的时间 | 计划结束后（单文件约 1.2 s） | **0.13 s**（版本号）+ 0.14 s（视频数） |
| 30 个视频 `-n -R` 总耗时 | 16.4 s | **2.4 s** |

moviepy 没有删：系统没有 ffmpeg、又没有 ffprobe 时，探测与取帧仍回退到 moviepy。`main()` 只在“没有任何 ffmpeg 且 moviepy 缺失”时报错退出 2。

## 5.6 v2.3 的并行取帧

`--decode-workers` 的选档逻辑（`decode_plan`）有纯逻辑用例；`--decode-workers 2` 的端到端用例确认产物尺寸不变；非法值退出码 2。前后对比与阶段剖析见 [07-performance.md](07-performance.md)。

## 5.7 v2.4 的硬件解码

`hardware_modes()`、已移除参数被拒绝、GPU 失败回退软件（mock 掉 `grab_frame_ffmpeg` 让 cuda 抛错，断言报表出现 `software fallback`）都有用例；真实 GPU 的像素一致性用例默认跳过，`QVP_TEST_CUDA=1` 时执行（本机跑过，平均差 <3/255）。

## 6. 未覆盖与残余风险

- 没有测试 4K/HDR/旋转元数据的真实素材（只测了合成 4K，内存数据来自另一台机器的采样）。
- 没有测试磁盘写满、权限拒绝、目标被占用（Windows 文件锁）——代码路径存在，但没有用例。
- `--jobs > 1` 只测了成功路径，没有测“两个文件同时失败”的报表顺序。
- 中断（Ctrl-C）后的 `.tmp` 清理写进了 `finally`，但没有自动化用例（需要注入信号）。
