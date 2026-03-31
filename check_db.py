import sqlite3

conn = sqlite3.connect('stardict.db')
cursor = conn.cursor()

cursor.execute('SELECT name FROM sqlite_master WHERE type="table"')
print('Tables:', cursor.fetchall())

cursor.execute('PRAGMA table_info(stardict)')
print('Columns:', cursor.fetchall())

cursor.execute('SELECT * FROM stardict LIMIT 3')
print('Sample data:', cursor.fetchall())

conn.close()
