# 首次搜索卡顿问题分析报告

## 摘要
首次搜索明显卡顿，主要原因是应用在主线程（UI 线程）同步执行 SQLite 查询与大量 Python 侧处理，且数据库缺乏针对查询列的索引并且首次磁盘读取缺少预热。建议优先将查询移出 UI 线程、增加必要索引或使用 FTS，并在启动时做轻量预热。

## 现象复现
- 启动应用后，第一次输入查询并按回车或触发候选加载，界面无响应 0.5–3 秒（视机器与磁盘速度）。

## 关键证据（代码定位）
- search.py 在初始化时调用 init_database（search_modules/bootstrap.py），使用 `sqlite3.connect('stardict.db')` 在主线程建立连接。
- 在 search_modules/navigation.py 中，on_search_text_changed 与 on_enter_pressed 直接在主线程调用 `self.cursor.execute(...)`：
  - 精确词匹配：SELECT ... FROM stardict WHERE word LIKE ? COLLATE NOCASE LIMIT 800
  - 语义检索：SELECT ... WHERE translation LIKE ? OR detail LIKE ? LIMIT 2500（并可能追加多次类似查询），随后在 Python 中对数千行做向量化与余弦计算。
- check_db.py 示例显示 stardict 使用普通表（未显示索引）。

## 根本原因
1. 同步 I/O：所有数据库查询在 UI 线程同步执行，导致界面被阻塞。
2. 未建立索引或未使用全文索引：LIKE / %...% 查询将触发全表扫描。大量扫描首次需从磁盘读页，开销高。
3. 首次查询涉及从磁盘读取大量数据（OS 缓存冷启动），后续查询受益于缓存。
4. Python 侧的向量化与排序在结果集较大时耗时明显（尤其在首次触发大量扫描时）。

## 优先级与修复建议（按优先级排序）
1. 把所有数据库查询迁移到后台线程／线程池（高优先级，最低成本）
   - Qt: 使用 QThread / QRunnable / QtConcurrent.run 或 Python threading.Thread，把查询异步化并在回调中更新 UI。
2. 为常用过滤列建索引（高优先级）
   - 对 prefix 搜索: `CREATE INDEX IF NOT EXISTS idx_stardict_word_nocase ON stardict(word COLLATE NOCASE);`
   - 对 translation/detail 可考虑：`CREATE INDEX IF NOT EXISTS idx_stardict_translation ON stardict(translation);`
3. 使用 FTS5 建立全文检索表（中高优先级，最佳针对 LIKE %x% 与文本搜索）
   - 示例：
     - `CREATE VIRTUAL TABLE stardict_fts USING fts5(word, translation, detail, content='stardict', content_rowid='rowid');`
     - 插入或使用 content= 方式保持同步，查询用 MATCH 更快。
4. 轻量预热数据库（中优先级）
   - 在后台线程启动时执行一次小查询，如 `SELECT rowid FROM stardict LIMIT 1;` 或主动读取若干页以把文件载入 OS 缓存。
5. 打开数据库的只读或只读 URI 模式以避免不必要的写入开销（视需求而定）：
   - `sqlite3.connect('file:stardict.db?mode=ro', uri=True)`
6. 减少一次性拉取行数与客户端处理量
   - 把 LIMIT 2500 调小或先只取必要字段并分页处理，尽量在 SQL 层做过滤/排序，减少 Python 侧计算。

## 快速代码示例
- 后台预热（最小修改，主线程无阻塞）:
```python
import threading

def warm_db(conn):
    try:
        cur = conn.cursor()
        cur.execute('SELECT rowid FROM stardict LIMIT 1')
        cur.fetchall()
    except Exception:
        pass

# 在 init_database 或 init_user_data 后：
threading.Thread(target=warm_db, args=(self.conn,), daemon=True).start()
```

- 在 UI 线程外执行查询（示例思路）：
  - 使用 QtConcurrent.run 或 QRunnable 将 `self.cursor.execute(...)` 放入后台，完成后发信号通知主线程更新候选列表。

## 验证建议（如何测量优化效果）
1. 在未优化前记录第一次按回车到 UI 响应的时间（ms）。
2. 实施 "迁移查询到后台"，重复测量；期望首次卡顿大幅下降（界面不再冻结）。
3. 添加索引/FTS 后，测量单次查询耗时与 CPU/IO 占用，应进一步降低。

## 结论
首次卡顿为多因子叠加：主线程同步 DB 查询 + 无索引导致全表扫描 + 首次磁盘 I/O。最有效也最安全的立刻改动是把数据库操作移到后台线程并做一次启动预热；随后添加索引或 FTS 以从根本上减少查询成本。

---
如需，可继续：
- 生成具体的 SQL 建表/索引脚本并提交 PR；
- 提供 QtConcurrent/QRunnable 的具体重构补丁；
- 帮助测试并比较优化前后性能数据。
