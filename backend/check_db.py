

import sqlite3
import os

print("Current folder:", os.getcwd())
print("Database exists:", os.path.exists("restaurants.db"))

conn = sqlite3.connect("restaurants.db")

cursor = conn.cursor()

cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
print("Tables:", cursor.fetchall())
cursor.execute('DROP TABLE IF EXISTS password_reset_tokens')
conn.close()

