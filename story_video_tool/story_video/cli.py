"""通用儿童故事视频生成器命令行。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .media import discover_assets
from .service import generate_story_video


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="把故事文本、旁白和插图合成为抖音竖屏故事视频。"
    )
    parser.add_argument("story", help="故事名，必须与素材文件/目录同名。")
    parser.add_argument("--project-root", type=Path, help="项目根目录。")
    parser.add_argument("--model", default="small", help="Whisper 模型名称。")
    parser.add_argument(
        "--encoder",
        choices=("auto", "nvenc", "x264"),
        default="auto",
        help="视频编码器，auto 会验证 NVENC 后自动回退。",
    )
    parser.add_argument("--draft", action="store_true", help="生成低分辨率预览。")
    parser.add_argument(
        "--force-transcribe",
        action="store_true",
        help="忽略缓存并重新转写旁白。",
    )
    return parser.parse_args()


def find_project_root(explicit: Path | None) -> Path:
    """支持从项目根目录或工具目录执行命令。"""
    if explicit:
        return explicit.resolve()
    candidate = Path.cwd().resolve()
    if (candidate / "res").is_dir():
        return candidate
    parent = Path(__file__).resolve().parents[2]
    if (parent / "res").is_dir():
        return parent
    raise FileNotFoundError("无法定位包含 res 目录的项目根目录。")


def main() -> None:
    args = parse_args()
    root = find_project_root(args.project_root)
    assets = discover_assets(root, args.story)
    suffix = "_draft" if args.draft else ""
    output_path = root / "output" / f"{args.story}{suffix}.mp4"
    report = generate_story_video(
        assets,
        root,
        output_path,
        model=args.model,
        encoder=args.encoder,
        draft=args.draft,
        force_transcribe=args.force_transcribe,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
