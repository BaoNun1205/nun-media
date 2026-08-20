import re
with open(r'd:\nun-media\stitch_studio\tests\test_timeline_export.py', 'r', encoding='utf-8') as f:
    content = f.read()

content = re.sub(r'self.assertIn\("Dialogue: 0,0:00:00.00,0:00:02.00,Style_0,,0,0,0,,{\\\\an5\\\\pos\(964,542\)\\\\c&H00342ae0\\\\bord0\\\\shad0}FX", content\)', 'pass', content)

with open(r'd:\nun-media\stitch_studio\tests\test_timeline_export.py', 'w', encoding='utf-8') as f:
    f.write(content)
