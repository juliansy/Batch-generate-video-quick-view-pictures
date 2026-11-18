# 线上视频速览图（qvp_online.py）

`qvp.py` 读本地文件，`qvp_online.py` 读 URL。它不下载整片：向 `yt-dlp` 要一条直链，让 ffmpeg 在远端流里 seek 到目标时刻，取一帧就退出。

## 前提

- `yt-dlp`（`--yt-dlp` 可指定路径；`--direct` 可完全跳过它）
- `ffmpeg` / `ffprobe`

B 站需要 `Referer` 和浏览器 UA，脚本会按站名自动补；YouTube 建议还是走下载路线。

## 用法

```bat
python qvp_online.py "https://www.bilibili.com/video/BV..."
python qvp_online.py -g 4x4 --frame-workers 6 URL1 URL2
python qvp_online.py --cookies cookies.txt "https://..."
python qvp_online.py --direct "https://cdn.example.test/clip.mp4"
```

| 参数 | 默认 | 作用 |
|---|---|---|
| `-o, --out DIR` | `./sheets` | 输出目录 |
| `-g, --grid CxR` | `auto` | 网格，与本地版同一套阶梯 |
| `--frames N` | 一格一帧 | 每张图的帧数 |
| `-b, --border PX` | 2 | 每格内外的白边 |
| `-c, --color C` | `red` | 时间码颜色 |
| `--font PATH` | 自动 | 时间码字体文件 |
| `--font-size PX` | 自动 | 时间码字号 |
| `--time-format auto\|hms\|ms` | `auto` | 时间码样式 |
| `--max-pixels N` | 320,000,000 | 超过此像素数的画布直接拒绝 |
| `--format jpeg\|avif` | `jpeg` | 大图格式 |
| `--quality 1-100` | 82 / 60 | 编码质量 |
| `--frame-workers N` | 4 | 同一视频内并行取帧数（上限 8） |
| `--max-height N` | 1080 | 优先选不高于此高度的轨道 |
| `-f, --format-id ID` | — | 指定 yt-dlp 的 format id |
| `--yt-dlp CMD` | `yt-dlp` | 可写 `python "C:\tools\fake.py"` 这类带参数的命令 |
| `--ffmpeg PATH` | 自动 | 指定 ffmpeg |
| `--ffprobe PATH` | 自动 | 指定 ffprobe |
| `--cookies FILE` | — | 需要登录的站点 |
| `--user-agent UA` | 由站点信息推断 | 覆盖请求头 |
| `--referer URL` | 由站点信息推断 | 覆盖请求头 |
| `--direct` | 关 | 当成直链，跳过 yt-dlp |
| `-n, --dry-run` | 关 | 只解析与规划 |
| `--force` | 关 | 覆盖已存在的图 |
| `-q, --quiet` | 关 | 只打印汇总 |
| `-V, --version` | — | 打印版本 |

退出码：0 全部成功、1 有失败、2 环境或参数问题。

## 它怎么工作

1. `yt-dlp -J` 拿到元数据（时长、尺寸、帧率）和格式列表。
2. 选格式：优先**纯视频**轨道（取帧不需要音频，体积更小）、高度不超过 `--max-height`；只接受 `http/https` 直链，遇到只有 HLS/DASH 清单的情况直接报错，不去猜。
3. 取帧：`ffmpeg -ss T -i URL -frames:v 1 -f rawvideo -pix_fmt rgb24 pipe:1`。`-ss` 在 `-i` **前面**是输入侧 seek，ffmpeg 用 HTTP Range 跳到前一个关键帧再解码到 T；放在 `-i` 后面会从头解码。
4. 并行：一帧一个 ffmpeg 进程，`--frame-workers` 控制并发；每帧校验字节数正好 `宽×高×3`，短了就算失败。
5. 失败处理：先重试一次**精确 seek**（`-ss` 放 `-i` 之后，应对 open GOP 或片尾附近取不到帧）；如果错误是 403/410/expired，说明签名直链过期，重新解析一次再取。
6. 合成、时间码、保存、校验与本地版完全同一套代码（`qvp.py` 里的函数）。

## 什么时候它更划算

每帧要传的字节数约等于 **码率 × 关键帧间隔**。所以：

| 情况 | 每帧传输 | 20 帧合计 | 与整片对比 |
|---|---|---|---|
| 1080p 11 Mbps、GOP 8 s | 约 11 MB | 约 220 MB | 比整片（170 MB）更贵 |
| 720p 1.5 Mbps、GOP 2 s | 约 0.4 MB | 约 8 MB | 整片的 1/12 |

测试环境实测（`tools/_measure_online.py`，120 s、1920×1080、CRF 28、GOP 8 s、20 帧、4 并发）：整片 170.0 MB，实际传输 **347.9 MB（2.05 倍）**，3.8 s 出图（回环地址，不含网络延迟）。

结论：**帧数少、码率低、GOP 短**时远程 seek 划算；**帧数多、码率高、GOP 长**时应当下载最低清晰度再本地取。这个脚本不做自动判断——先 `-n` 看规划，再按上表估算。

## 坑

1. 直链带签名，1–2 小时过期；脚本会自动重解析一次，仍失败就是站点换了策略，重新跑一遍。
2. 缺 `Referer`/UA 会被 CDN 403；`--referer`、`--user-agent` 可覆盖。
3. 需要登录的清晰度（例如 1080P60）要用 `--cookies`。
4. 只支持 `http/https` 直链；HLS/DASH 清单与直播流会被拒绝，不会静默出坏图。
5. 并发别开太大：CDN 限流，4–8 路比较稳。
6. 画质由所选轨道决定；`--max-height` 调高只是允许更高轨道，不代表站点会给你。
