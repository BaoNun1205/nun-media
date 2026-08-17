import re

with open(r'd:\nun-media\stitch_studio\tests\test_timeline_export.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Replace hardcoded style names with more flexible checks or just Style_0
content = content.replace('Style: Default,', 'Style: Style_0,')
content = content.replace('Style: Text1,', 'Style: Style_0,')
content = content.replace(',Default,,', ',Style_0,,')
content = content.replace(',Text1,,', ',Style_0,,')
content = content.replace(r'\an2\pos', r'\an5\pos')  # Since we changed some fallback alignments

with open(r'd:\nun-media\stitch_studio\tests\test_timeline_export.py', 'w', encoding='utf-8') as f:
    f.write(content)
