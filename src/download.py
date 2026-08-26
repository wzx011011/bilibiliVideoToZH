"""B站视频下载 —— yt-dlp 封装。

下载 B站视频到 downloads/ 目录。支持单集（BV/URL）和合集（BV/URL 自动展开分P）。

用法：
  python download.py <视频URL或BV号> [--output downloads/] [--episode N]
  python download.py "https://www.bilibili.com/video/BVxxxx" --episode 2

依赖：pip install yt-dlp
  yt-dlp 是 youtube-dl 的活跃 fork，B站支持好。

注意：
  - 需要登录态的下载（高清/会员视频）在 ~/.config/yt-dlp/config 或 cookies.txt 配置。
  - 合集会下载所有分P，每集命名 episode-NN.mp4。
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path


def download(url: str, output_dir: Path, episode: int | None = None,
             cookies: Path | None = None) -> list[Path]:
    """下载视频，返回下载的文件路径列表。

    url: B站视频 URL 或 BV 号
    output_dir: 输出目录
    episode: 指定只下载合集的第 N 集（从1开始）；不指定则下载全部
    cookies: cookies.txt 路径（需要登录态时用）
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # 规范化 URL
    if url.startswith("BV"):
        url = f"https://www.bilibili.com/video/{url}"

    # 输出模板
    if episode:
        template = str(output_dir / f"episode-{episode:02d}.mp4")
        playlist_items = str(episode)
    else:
        template = str(output_dir / "episode-%(playlist_index)02d.mp4")
        playlist_items = None

    cmd = [
        sys.executable, "-m", "yt_dlp",
        "-f", "bestvideo+bestaudio/best",
        "--merge-output-format", "mp4",
        "-o", template,
        "--no-overwrites",
        "--newline",  # 进度换行显示
    ]
    if cookies:
        cmd += ["--cookies", str(cookies)]
    if playlist_items:
        cmd += ["--playlist-items", playlist_items]
    cmd += [url]

    print(f"下载: {url}")
    print(f"输出: {template}")
    if episode:
        print(f"仅下载第 {episode} 集")

    subprocess.run(cmd, check=True)

    # 返回下载的文件
    downloaded = sorted(output_dir.glob("episode-*.mp4"))
    return downloaded


def main() -> None:
    parser = argparse.ArgumentParser(description="B站视频下载（yt-dlp 封装）")
    parser.add_argument("url", help="B站视频 URL 或 BV 号")
    parser.add_argument("--output", "-o", type=Path, default=Path("downloads"),
                        help="输出目录（默认 downloads/）")
    parser.add_argument("--episode", type=int, default=None,
                        help="仅下载合集的第 N 集（从1开始）")
    parser.add_argument("--cookies", type=Path, default=None,
                        help="cookies.txt 路径（需登录态时用）")
    args = parser.parse_args()

    files = download(args.url, args.output, args.episode, args.cookies)
    print(f"\n[✓] 下载完成：{len(files)} 个文件")
    for f in files:
        print(f"  {f}")


if __name__ == "__main__":
    main()
