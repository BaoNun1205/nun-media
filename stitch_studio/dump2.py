import sqlite3
from pathlib import Path

conn = sqlite3.connect('d:/nun-media/stitch_studio/workspace/app_library.sqlite3')
rows = conn.execute("SELECT * FROM assets WHERE kind='srt'").fetchall()
for r in rows:
    p = Path(r[3])
    print(p, p.exists())
