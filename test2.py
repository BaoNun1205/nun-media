import subprocess
import base64

ass_content = """[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,100,&HFFFFFFFF,&H000000FF,&H33888888,&H33888888,0,0,0,0,100,100,0,0,3,10,0,5,10,10,10,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.00,0:00:05.00,Default,,0,0,0,,{\\pos(960,540)}I TWISTED AROUND AND SHOUTED
"""
with open("test2.ass", "w") as f:
    f.write(ass_content)

subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=white:s=1920x1080:d=1", "-vf", "subtitles=test2.ass", "-vframes", "1", "test2.png"])
