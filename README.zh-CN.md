<div align="center">

<br>

**简体中文** · [English](README.md)

<br>

</div>

<div align="center">

![Python](https://img.shields.io/badge/python-3.9%2B-3776AB?logo=python&logoColor=white)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-4C566A)
![moviepy](https://img.shields.io/badge/moviepy-2.x-2EA043)
![License](https://img.shields.io/badge/license-GPL--3.0-blue)
[![Release](https://img.shields.io/github/v/release/juliansy/video-quick-view?color=orange&label=release)](https://github.com/juliansy/video-quick-view/releases)
![Stars](https://img.shields.io/github/stars/juliansy/video-quick-view?color=yellow)

</div>

# 批量生成视频速览图

给一个装满视频的文件夹，每个视频出一张速览图：均匀截取的画面排成网格，每格标着时间点。不打开播放器，也能一眼看出这是什么片子。

**下载：**[最新版本](https://github.com/juliansy/video-quick-view/releases/latest)——压缩包里是 `qvp.py`、两份 README 和许可证。

## 它做什么

- 找出你指定位置的所有视频：`.mp4` `.m4v` `.mov` `.avi` `.mkv` `.webm` `.flv` `.wmv` `.mpg` `.mpeg` `.ts` `.m2ts`。
- 按片长自动选网格：**2×2 → 3×2 → 3×3 → 4×3 → 4×4 → 5×4 → 5×5**，开头密、后面逐步放缓。
- 在每张左上角标时间点（`00:26`；超过一小时是 `1:01:05`），红字带黑色描边。
- 按选中的网格加白边拼成一张，存成 `sheets/<文件名>_collage.jpg`。
- 已经做过的跳过，跳过的和失败的都会说明原因。

## 文件夹长什么样

```text
D:\Videos\
├── qvp.py              脚本
├── lecture-01.mp4      会被读取的视频
├── talk-02.mp4         另一个
└── sheets\             第一次运行时自动创建
    ├── lecture-01_collage.jpg
    └── talk-02_collage.jpg
```

不带参数时，脚本读它自己所在的文件夹，所以视频要和 `qvp.py` 放在一起。要处理别处，把文件夹（或几个文件）作为参数传进去。

## 需要什么

- Python 3.9 或更高
- 两个包：

```text
pip install "moviepy>=2" pillow
```

- FFmpeg：系统里有 `ffmpeg` 就用系统的（大约快一倍）；没有就用 moviepy 自带的那份。不需要额外安装。

## 怎么用

双击 **`qvp.bat`**，或把文件夹拖到它上面。它用默认配置调用 `qvp.py`，跑完停住不关窗口。

在终端里：

```text
python qvp.py                        # 脚本旁边的视频
python qvp.py D:\Videos              # 一个文件夹
python qvp.py D:\Videos\a.mp4        # 单个文件
python qvp.py D:\Videos -R -j 4      # 连子目录，同时处理 4 个
python qvp.py -n D:\Videos           # 只看计划，不写文件
python qvp.py -g 4x4 D:\Videos       # 固定网格，不用自动
```

### 选项

| 选项 | 默认 | 作用 |
| --- | --- | --- |
| `-o, --out DIR` | `<视频所在目录>/sheets` | 产物目录 |
| `--frames N` | 每格一张 | 截几张；会自动选能装下它的最小网格 |
| `-g, --grid CxR` | `auto` | 列 × 行；`auto` 表示按片长自动选 |
| `-b, --border PX` | 2 | 每张画面四周白边像素 |
| `-c, --color C` | `red` | 时间点颜色 |
| `--font PATH` | 自动 | 时间点字体文件 |
| `--font-size PX` | 自动 | 时间点字号（默认按格宽缩放） |
| `--time-format auto\|hms\|ms` | auto | 时间格式：`00:26` / `00:00:26` / `26:00` |
| `-R, --recursive` | 关 | 连子目录 |
| `-j, --jobs N` | 1 | 同时渲染几个视频 |
| `--decode-workers N` | 自动 | 并行取帧的 ffmpeg 进程数；`1` = 串行，`0` = 按核数自动 |
| `--cuda` | 关闭 | 用 GPU 解码；失败自动退回软件 |
| `--batch-seek N` | GPU 4 / CPU 1 | 每个进程带的 seek 数；批量能摊薄解码器启动成本 |
| `-f, --force` | 关 | 覆盖已存在的速览图 |
| `-n, --dry-run` | 关 | 只分析，不写文件 |
| `--max-pixels N` | 2 亿 | 画布超过这个像素数就拒绝 |
| `--ffmpeg PATH` | 自动 | 优先尝试的 ffmpeg |
| `--log FILE` | 无 | 追加写运行日志 |
| `-q, --quiet` | 关 | 只打印汇总行 |
| `-V, --version` | — | 显示版本 |

退出码：`0` 全部成功或跳过；`1` 至少一个失败；`2` 参数错误；`130` 被中断。

### 输出

```text
[1/2] lecture-01.mp4 … ok
#  file            grid  frames  canvas     time    result
-  --------------  ----  ------  ---------  ------  ------
1  lecture-01.mp4  4x4   16      7696x4336  3.81s   ok
2  talk-02.mp4     2x2   4       648x488    3.27s   ok

2 done, 0 skipped, 0 failed in 7.7s
```

`canvas` 是这张 JPEG 的尺寸，`time` 是这个文件花的时间。对同一批再跑一次，会显示 `skipped: already exists (use --force to overwrite)`。

控制台信息只有英文。

### 自动网格

两分钟的片子 4 格就够，两小时的片子 4 格又太少，所以网格跟着片长走：

| 片长 | 网格 | 格数 | 每格间隔 |
| --- | --- | --- | --- |
| 20 秒以内 | 2 × 2 | 4 | 5 秒 |
| 40 秒以内 | 3 × 2 | 6 | 7 秒 |
| 1 分钟以内 | 3 × 3 | 9 | 7 秒 |
| 3 分钟以内 | 4 × 3 | 12 | 15 秒 |
| 5 分钟以内 | 4 × 4 | 16 | 19 秒 |
| 12 分钟以内 | 5 × 4 | 20 | 36 秒 |
| 超过 12 分钟 | 5 × 5 | 25 | 72 秒以上 |

开头密度涨得快（40 秒的片子已经给 6 格），越往后越慢——短视频画面变化更频繁。4K 的 5×5 是 208 MP，超过默认预算，会自动降成 5×4；“先按阶梯选，再按预算逐级降”。推导过程见 [`docs/06-auto-grid.md`](docs/06-auto-grid.md)。

### GPU 解码

`--cuda` 通过 ffmpeg 的 CUDA hwaccel 解码，某帧失败自动退回软件，报表里标 `ok (GPU)` 或 `ok (software fallback)`。默认关闭。

收益取决于显卡、驱动、ffmpeg 构建和编码格式：有的配置明显更快，有的持平甚至更慢。依赖它之前先在自己的文件上量一遍：

```text
python tools/bench_hw.py "D:\Videos\clip.mp4"
```

`--batch-seek` 保持默认（`--cuda` 时是 4），因为“每帧一个进程”会让每一帧都重付一次 CUDA 上下文开销。小显存卡注意用量：八个 4K 输入一批可能接近 3.5 GB。

## 安全

- 输入只读。速览图先写临时文件，重新打开校验通过，再原子替换。
- 一个视频坏掉不会中断整批：它会被标成 `failed` 并给出原因，其余照常，退出码为 `1`。
- 已存在的速览图默认跳过，加 `--force` 才覆盖。
- 不删除任何文件。

## 限制

- 按固定间隔截取，不识别镜头切换：长时间静止的画面会在好几格里重复。
- 每个视频一张原分辨率大图。1080p 的 4 × 4 约 33 MP、5 × 4 约 42 MP；4K 的 4 × 4 约 133 MP、约 0.7 GB 内存。`--max-pixels` 会拒绝超过 2 亿像素的画布。
- 片头与片尾各跳过 1 秒，所以淡入、片尾卡不会是首末两格；但如果片子结尾本身就是黑屏，最后一格仍会是黑的。
- 取帧靠 seek：每次 seek 都要从前一个关键帧解到目标时刻，所以 4K 即使并行也要几秒。“批量 seek”与 `--decode-workers` 只能拿内存换速度。
- 只用画面。音频、字幕、封面都不参与。

## 项目文档

设计、评审与测量记录，供想了解默认值来历的人查阅：

- [docs/01-decomposition.md](docs/01-decomposition.md)——旧脚本逐行做了什么
- [docs/02-review.md](docs/02-review.md)——它错在哪，附实测证据
- [docs/03-design.md](docs/03-design.md)——当前流程，以及为什么这么定
- [docs/04-code-review.md](docs/04-code-review.md)——实现评审
- [docs/05-test-report.md](docs/05-test-report.md)——测试结果、耗时与内存
- [docs/06-auto-grid.md](docs/06-auto-grid.md)——为什么是 2×2 / 3×3 / 4×4 / 5×5，附实测数据
- [docs/07-performance.md](docs/07-performance.md)——性能剖析、优化项、被否掉的方案、GPU 测量

## 测试

```text
python -m unittest discover -s tests -v
```

## 许可

GPL-3.0，见 [LICENSE](LICENSE)。
