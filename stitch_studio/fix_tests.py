import re

with open(r'd:\nun-media\stitch_studio\tests\test_timeline_export.py', 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace('srt_events=', 'events=').replace('            text_events=[],\n', '')
content = re.sub(r'events=\[\(([^,]+),\s*([^,]+),\s*([^)]+)\)\],', r'events=[{"start": \1, "end": \2, "text": \3}],', content)
content = content.replace('            events=[],\n', '')
content = content.replace('            text_events=[\n', '            events=[\n')
content = content.replace('            text_events=[{\n', '            events=[{\n')

with open(r'd:\nun-media\stitch_studio\tests\test_timeline_export.py', 'w', encoding='utf-8') as f:
    f.write(content)
