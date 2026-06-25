"""生成适合短视频小屏阅读的 ASS 逐字高亮字幕。"""

from __future__ import annotations

import math
from pathlib import Path

from .alignment import Caption, SPOKEN_RE


def ass_time(seconds: float) -> str:
    """将秒转换为 ASS 的 H:MM:SS.cc 时间格式。"""
    centiseconds = max(0, round(seconds * 100))
    hours, rest = divmod(centiseconds, 360000)
    minutes, rest = divmod(rest, 6000)
    secs, cents = divmod(rest, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{cents:02d}"


def ass_escape(text: str) -> str:
    """转义 ASS 控制字符。"""
    return text.replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}")


def karaoke_text(caption: Caption) -> str:
    """使用每个字符的真实持续时间生成 ASS karaoke 标签。"""
    parts: list[str] = []
    previous_end = caption.start
    for item in caption.chars:
        if SPOKEN_RE.fullmatch(item.char):
            gap = max(0.0, item.start - previous_end)
            if gap >= 0.06:
                parts.append(rf"{{\k{max(1, round(gap * 100))}}}")
            duration = max(1, round((item.end - item.start) * 100))
            parts.append(rf"{{\kf{duration}}}{ass_escape(item.char)}")
            previous_end = item.end
        else:
            parts.append(ass_escape(item.char))
    return "".join(parts)


def write_ass(
    path: Path,
    title: str,
    captions: list[Caption],
    width: int,
    height: int,
    audio_duration: float,
) -> None:
    """写入标题、逐字高亮字幕和结尾收束文案。"""
    scale = width / 1080
    caption_size = max(32, round(64 * scale))
    title_size = max(38, round(78 * scale))
    margin_v = round(300 * height / 1920)
    outline = max(3, round(5 * scale))
    shadow = max(2, round(4 * scale))

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 2
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,Microsoft YaHei,{caption_size},&H006AD18F,&H00DFF6FF,&H001D263B,&H80000000,-1,0,0,0,100,100,1,0,1,{outline},{shadow},2,90,190,{margin_v},1
Style: Title,Microsoft YaHei,{title_size},&H00DFF6FF,&H00DFF6FF,&H001D263B,&H50000000,-1,0,0,0,100,100,2,0,1,{outline},{shadow},8,100,100,{round(90 * height / 1920)},1
Style: End,Microsoft YaHei,{round(title_size * 0.72)},&H00DFF6FF,&H00DFF6FF,&H001D263B,&H50000000,-1,0,0,0,100,100,2,0,1,{outline},{shadow},5,100,100,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = [
        (
            "Dialogue: 2,0:00:00.35,0:00:04.80,Title,,0,0,0,,"
            rf"{{\fad(500,700)\blur0.5}}《{ass_escape(title)}》"
        )
    ]
    for caption in captions:
        events.append(
            "Dialogue: 3,"
            f"{ass_time(caption.start)},{ass_time(caption.end)},"
            "Caption,,0,0,0,,"
            rf"{{\fad(90,100)}}{karaoke_text(caption)}"
        )

    end_start = max(0.0, audio_duration - 4.2)
    end_end = max(end_start + 0.5, audio_duration - 0.25)
    events.append(
        "Dialogue: 2,"
        f"{ass_time(end_start)},{ass_time(end_end)},End,,0,0,0,,"
        r"{\fad(700,900)}愿每个夜晚，都有好故事相伴"
    )
    path.write_text(header + "\n".join(events) + "\n", encoding="utf-8-sig")
