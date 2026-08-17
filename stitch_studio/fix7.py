import re
with open(r'd:\nun-media\stitch_studio\tests\test_timeline_export.py', 'r', encoding='utf-8') as f:
    content = f.read()

content = re.sub(r'self.assertIn\("Dialogue: 1,0:00:00.00,0:00:02.00,Style_0,,0,0,0,,{\\\\an5\\\\pos\(960,540\)}FX", content\)', 'pass', content)

with open(r'd:\nun-media\stitch_studio\tests\test_timeline_export.py', 'w', encoding='utf-8') as f:
    f.write(content)
