import sqlite3
import pprint

conn = sqlite3.connect('d:/nun-media/stitch_studio/workspace/app_library.sqlite3')
conn.row_factory = sqlite3.Row
rows = conn.execute("SELECT * FROM assets WHERE kind='srt'").fetchall()
for row in rows:
    pprint.pprint(dict(row))
