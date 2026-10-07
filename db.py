import sqlite3
from pathlib import Path
import pandas as pd
from config import DB_PATH

def _conn():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.execute("""CREATE TABLE IF NOT EXISTS violations(
        id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, camera TEXT,
        type TEXT, confidence REAL, image TEXT)""")
    return c

def log(ts, camera, vtype, conf, image):
    with _conn() as c:
        c.execute("INSERT INTO violations(ts,camera,type,confidence,image) VALUES(?,?,?,?,?)",
                  (ts, camera, vtype, conf, image))

def history():
    with _conn() as c:
        return pd.read_sql("SELECT * FROM violations ORDER BY id DESC", c)
