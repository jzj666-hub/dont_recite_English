# I Love English

一个基于 PyQt6 的英语查词与离线翻译工具，支持：

- 扩展态查词与句子翻译
- 内化态收藏与在背管理
- 单词批注、关联词与 AI 辅助能力
- 析文标签页：仅导入 Markdown（.md），支持完成框选后基于上下文生成 AI 划线注解并保存

## 环境要求

- Python 3.10+
- Windows（当前项目已提供 `start.bat`）

## 安装依赖

```bash
pip install -r requirements.txt
```

## 启动方式

```bash
python search.py
```

或双击：

- `start.bat`

## 数据文件

- `stardict.db`：词库数据
- `user_data.db`：用户数据（收藏、在背、批注、设置等）
