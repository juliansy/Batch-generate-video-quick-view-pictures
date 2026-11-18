<div align="center">

<br>

**简体中文** · [English](README.md)

<br>

</div>

<div align="center">

![Python](https://img.shields.io/badge/python-3.9%2B-3776AB?logo=python&logoColor=white)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-4C566A)
![moviepy](https://img.shields.io/badge/moviepy-2.x-2EA043)
![License](https://img.shields.io/badge/license-MIT-green)
[![Release](https://img.shields.io/github/v/release/juliansy/video-quick-view?color=orange&label=release)](https://github.com/juliansy/video-quick-view/releases)
![Stars](https://img.shields.io/github/stars/juliansy/video-quick-view?color=yellow)

</div>

# 批量视频速览图

每个视频一张速览图：等间隔取帧拼成网格，每格标时间码。不打开播放器也能认出文件是什么。

**下载：**[最新版本](https://github.com/juliansy/video-quick-view/releases/latest)——包含 `qvp.py`、`qvp.bat`、`requirements.txt`、两份 README 和许可证。

## 做什么

- 找到所有视频：`.mp4` `.m4v` `.mov` `.avi` `.mkv` `.webm` `.flv` `.wmv` `.mpg` `.mpeg` `.ts` `.m2ts`。
- 按片长与画幅选网格：横屏 **2x2 → 3x2 → 3x3 → 4x3 → 4x4 → 5x4 → 5x5**，竖屏 **4x1 → 8x3**。
- 认手机写入的旋转标记，竖拍的片子输出就是正的。
- 每格左上角标时间码（`00:26`，超过一小时是 `1:01:05`）。
- 存成 `sheets/<文件名>_collage.jpg`。
- 已存在的图会跳过，并说明每个文件为什么跳过或失败。

### 格式与体积

默认 JPEG：任何看图软件、浏览器、聊天窗口都能打开。质量 82、色度不降采样——红色时间码保持锐利，不会糊进背景。

`--format avif` 写出同样画面的 AVIF，体积约为三分之一（166 MP：JPEG 12 MB，AVIF 4 MB），代价是编码更慢。AVIF 需要较新的查看器：Windows 11 照片、Chrome、Edge、Firefox、macOS 预览都能开；Windows 10 需要装商店里的免费 AVIF 扩展。

真正贵的是内存，这个数是实测的：100 MP 的拼图峰值 1.1 GB，208 MP 为 2.2 GB，约 11 字节/像素（画布、编码缓冲、在飞的帧）。`-j 4` 会同时保留四份。`--max-pixels`（默认 320,000,000）是闸门；机器小就调低它，用 `-j 1`，并把 `--decode-workers` 调小，减少同时在飞的帧。

## 目录长什么样

```text
D:\Videos\
├── qvp.py                          脚本
├── lecture-01.mp4                  会被读取的视频
├── talk-02.mp4                     另一个
└── sheets\                         第一次运行时创建
    ├── lecture-01_collage.jpg      lecture-01.mp4 生成的速览图
    └── talk-02_collage.jpg         talk-02.mp4 生成的速览图
```

不带参数时处理脚本自己所在的目录；给路径就处理别处。

## 需要什么

- Python 3.9 或更新
- `pip install "moviepy>=2" pillow`（AVIF 输出需要 Pillow 11.3 或更新；JPEG 不受影响）
- 建议装 ffmpeg：`winget install Gyan.FFmpeg`，或任意版本放进 `PATH`

ffmpeg 可选：系统里有就用（快约 2 倍），没有就用 moviepy 自带的那份。

## 怎么用

双击 **`qvp.bat`**，或把文件夹拖到它上面。命令行：

```text
python qvp.py                             # 脚本旁边的视频
python qvp.py "D:\Videos"                 # 一个文件夹
python qvp.py "D:\Videos" -R -j 4         # 连子目录，同时处理 4 个
python qvp.py -n "D:\Videos"              # 只看计划，不写文件
python qvp.py -g 4x4 "D:\Videos"          # 固定网格，不用自动
```

### 参数

| 参数 | 默认 | 作用 |
| --- | --- | --- |
| `-o, --out DIR` | `<视频目录>/sheets` | 输出目录 |
| `--frames N` | 每格一帧 | 每个视频取几帧；自动选能装下的最小网格（上限 25，再多要用 `-g` 指定） |
| `-g, --grid CxR` | `auto` | 列x行（`4x4`、`4*4`、`4×4`、`4,4` 都能用），`auto` 表示自动选 |
| `-b, --border PX` | 2 | 每格白边宽度 |
| `-c, --color C` | `red` | 时间码颜色 |
| `--font PATH` | 自动 | 时间码字体文件 |
| `--font-size PX` | 自动 | 字号，默认按格子缩放 |
| `--time-format auto\|hms\|ms` | auto | `auto`：`00:26`（超过一小时自动带小时）；`hms`：固定 `00:00:26`；`ms`：总分钟数，3661 秒是 `61:01` |
| `-R, --recursive` | 关 | 连子目录一起处理 |
| `-j, --jobs N` | 1 | 同时处理几个视频 |
| `--cuda` | 关 | 用 GPU 解码，失败退回软件 |
| `--batch-seek N` | `--cuda` 时 4，否则 1 | 一个 ffmpeg 进程带几个 seek |
| `--decode-workers N` | 自动（约 cpu/4） | 整轮运行的解码进程数，由 `-j` 分摊 |
| `-f, --force` | 关 | 覆盖已存在的图 |
| `-n, --dry-run` | 关 | 只分析不写文件 |
| `--max-pixels N` | 320,000,000 | 拒绝更大的画布（峰值内存约 11 字节/像素） |
| `--format jpeg\|avif` | `jpeg` | 图片格式；AVIF 约为三分之一大小，写盘更慢 |
| `--quality 1-100` | JPEG 82 / AVIF 60 | 编码质量 |
| `--ffmpeg PATH` | 自动 | 优先尝试的 ffmpeg |
| `--log FILE` | — | 追加运行日志 |
| `-q, --quiet` | 关 | 只打印汇总 |
| `-V, --version` | — | 打印版本 |

退出码：`0` 正常或跳过（存在的空目录也返回 `0`；路径不存在但还有其它输入时只报警告）、`1` 至少一个文件失败、`2` 参数有误、完全没有可用输入或缺少 ffmpeg/moviepy、`130` 中断。

## 输出

```text
qvp 2.10.0
2 video(s) | grid auto | sheets/ next to each video
[1/2] lecture-01.mp4 … ok
[2/2] talk-02.mp4 … ok
#  file            grid  frames  canvas     time   result
-  --------------  ----  ------  ---------  -----  ------
1  lecture-01.mp4  4x3   12      5136x2172  1.21s  ok
2  talk-02.mp4     2x2   4       2568x1448  0.40s  ok

2 done, 0 skipped, 0 failed | 1.85s
```

`canvas` 是速览图的像素尺寸，`time` 是这个文件花的时间。标签和错误提示是英文；来自视频本身的报错沿用 ffmpeg 的原文。

## 线上视频

`qvp_online.py` 出的是同一种速览图，只是输入从文件换成了 URL。它向 [yt-dlp](https://github.com/yt-dlp/yt-dlp) 要一条直链，让 ffmpeg 在远端流里 seek，因此不需要先把整片下载下来。

```bat
python qvp_online.py "https://www.bilibili.com/video/BV..."
python qvp_online.py -g 4x4 --frame-workers 6 URL1 URL2
```

除 `ffmpeg` 外还需要 `yt-dlp`；B 站这类 CDN 要求的 `Referer`/`User-Agent` 脚本会自己带。签名直链一两个小时就会过期，脚本会重新解析而不是让任务失败。每帧的传输量大致等于码率乘关键帧间隔，所以"帧数少 + 低码率"才是它划算的场景——具体数字、参数与反例见 [`docs/09`](docs/09-online.md)。

## 自动网格

| 片长 | 网格 | 格数 | 每格秒数 |
| --- | --- | --- | --- |
| 20 秒内 | 2x2 | 4 | 5 |
| 40 秒内 | 3x2 | 6 | 7 |
| 1 分钟内 | 3x3 | 9 | 7 |
| 3 分钟内 | 4x3 | 12 | 15 |
| 5 分钟内 | 4x4 | 16 | 19 |
| 12 分钟内 | 5x4 | 20 | 36 |
| 超过 12 分钟 | 5x5 | 25 | 29–72+ |


竖屏（高大于宽——短视频信息密度大，格子保持竖长、行数慢慢加）：

| 时长 | 网格 | 格数 |
| --- | --- | --- |
| 6 秒内 | 4x1 | 4 |
| 10 秒内 | 5x1 | 5 |
| 15 秒内 | 6x1 | 6 |
| 20 秒内 | 4x2 | 8 |
| 28 秒内 | 5x2 | 10 |
| 38 秒内 | 6x2 | 12 |
| 1 分钟内 | 7x2 | 14 |
| 3 分钟内 | 8x2 | 16 |
| 超过 3 分钟 | 8x3 | 24 |

短片密、长片疏；竖屏只多一次尺寸比较，不额外探测。4K 的 5x5 是 208 MP，在默认 320 MP 预算内；更大的画布会逐级降档，直到放得下。详见 [`docs/06-auto-grid.md`](docs/06-auto-grid.md)。

## GPU 解码

`--cuda` 走 ffmpeg 的 CUDA hwaccel，失败自动退回软件；报表里标 `ok (GPU)` 或 `ok (software fallback)`。默认关闭，收益取决于显卡、驱动、ffmpeg 构建和编码格式——依赖它之前先用 `tools/bench_hw.py` 测一下。`--batch-seek` 保持默认（`--cuda` 时是 4）；小显存卡上八个 4K 输入一批可能到约 3.5 GB 显存。

## 安全

- 只读输入。速览图先写临时文件，校验后再原子替换（JPEG 会按 1/8 尺寸解码一次；AVIF 只查容器头，不解码整张）。
- 一个坏文件不会中断整批：标为 `failed`，其余继续，退出码 `1`。
- 已存在的图会跳过，除非加 `--force`。
- 唯一会被删的是它自己留下的 `.tmp-*` 临时文件，而且要超过一小时。

## 限制

- 按固定间隔取帧，不识别镜头切换。
- 每个视频一张原分辨率大图：4K 的 4x4 约 133 MP、约 1.4 GB 内存；`--format avif` 只减体积，不减内存。
- 片头片尾各跳过 1 秒；不足 4 秒的片子改为跳过总长的四分之一。
- 取帧要 seek：每次从前一个关键帧解到目标时刻，4K 即使在并行下也要几秒。
- 只用画面，音频、字幕、封面不参与。
- 由不同分辨率片段拼成的文件（前段 720p、后段 1080p）会按探测尺寸缩放并补黑边，不拉伸。
- 部分 MPEG-TS 录制在片尾附近对快速定位返回空帧，会自动改用较慢的精确 seek 重取，能出图，只是稍慢。
- 旋转只认容器的显示矩阵（display matrix）。ffmpeg 自己忽略的 `rotate` 标签不会被采信，这类文件保持 ffmpeg 解出的方向。
- 同名不同扩展名（`talk.mp4`、`talk.mkv`）共用一个输出名：排序在前的（`talk.mkv`）出图，另一个跳过；两个都要就改个名。

## 项目文档

发布前先跑 `python tools\release_check.py`（打包用 `tools\make_package.py`），检查项与人工清单见 [`docs/08`](docs/08-release.md)。

设计、评审与测量笔记（中文）：[`docs/06`](docs/06-auto-grid.md) 与 [`docs/07`](docs/07-performance.md) 描述当前默认值；`docs/01`–`docs/05` 是 v1 到 v2 重写期间的记录，保留的是当时的推理，不代表今天的代码。

## 许可

MIT，见 [LICENSE](LICENSE)。
