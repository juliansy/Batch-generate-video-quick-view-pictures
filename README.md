# Batch-generate-video-quick-view-pictures
# 批量生成视频速览图-Python

## 功能

从当前文件夹中的视频文件中截取指定数量的帧（默认16张），

在每张图片左上角标记对应的时间位置，并为每张图片添加白边后，

将这些图片按照指定的网格排列方式（默认4x4）拼贴成一张大图，最终将拼贴图保存到输出文件夹中

## 前提

- 安装 Python, 无版本要求

- 安装 moviepy, pillow

``` python

pip install moviepy

pip install pillow

```
