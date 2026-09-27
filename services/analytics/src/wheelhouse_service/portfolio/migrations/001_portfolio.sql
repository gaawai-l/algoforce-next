CREATE TABLE IF NOT EXISTS captures(id TEXT PRIMARY KEY,source TEXT,account TEXT,at TEXT,payload TEXT);
CREATE INDEX IF NOT EXISTS capture_account ON captures(source,account,at);
CREATE TABLE IF NOT EXISTS records(id TEXT PRIMARY KEY,source TEXT,account TEXT,kind TEXT,broker_id TEXT,at TEXT,payload TEXT);
CREATE INDEX IF NOT EXISTS records_identity ON records(source,account,kind,broker_id,at);
CREATE TABLE IF NOT EXISTS cycles(id TEXT PRIMARY KEY,source TEXT,account TEXT,payload TEXT);
CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY,cycle_id TEXT,payload TEXT);
CREATE TABLE IF NOT EXISTS annotations(id INTEGER PRIMARY KEY AUTOINCREMENT,source TEXT,account TEXT,kind TEXT,code TEXT,at TEXT,author TEXT,reason TEXT,payload TEXT);
CREATE TABLE IF NOT EXISTS fee_overlays(id INTEGER PRIMARY KEY AUTOINCREMENT,event_id TEXT,fee TEXT,at TEXT,author TEXT,reason TEXT);
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY AUTOINCREMENT,source TEXT,account TEXT,at TEXT,action TEXT,entity_id TEXT,author TEXT,reason TEXT);
