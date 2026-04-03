# 开发者说明文档

## 1. 项目结构与文件关系

### 1.1 核心文件结构

```
I_love_English/
├── search_modules/
│   ├── ai_assistant.py      # AI 助手相关功能
│   ├── ai_prompts.py         # AI 提示词配置
│   ├── bootstrap.py          # 启动相关
│   ├── infrastructure.py     # 基础设施功能
│   ├── llm_translation.py    # LLM 翻译功能
│   ├── navigation.py         # 导航相关功能
│   ├── ui.py                 # UI 相关功能
│   └── user_features.py      # 用户功能模块（本文档重点）
├── .gitignore
├── README.md
├── check_db.py
├── requirements.txt
├── search.py                 # 主搜索文件
└── start.bat                 # 启动脚本
```

### 1.2 文件依赖关系

| 文件 | 依赖文件 | 依赖内容 |
|------|----------|----------|
| user_features.py | infrastructure.py | build_highlighted_text_html 函数 |
| user_features.py | ai_prompts.py | default_ai_prompts, loads_prompts, prompt_text 函数 |
| user_features.py | PyQt6 | 各种 UI 组件 |

## 2. user_features.py 文件分析

### 2.1 文件地位与作用

`user_features.py` 是整个项目的核心功能模块之一，主要负责用户交互相关的功能实现。它通过 `UserFeaturesMixin` 类的形式，为应用提供了丰富的用户功能，包括：

- AI 提示词管理
- 单词复习与排序
- 随机考词功能
- 选词成文功能
- 单词关联功能
- 收藏夹管理
- 笔记管理
- 用户界面交互

### 2.2 核心功能模块

#### 2.2.1 AI 提示词管理

- **功能**：管理和获取 AI 提示词配置
- **关键方法**：
  - `get_ai_prompts()`: 获取合并后的 AI 提示词配置
  - 依赖 `ai_prompts.py` 中的函数来加载和处理提示词

#### 2.2.2 单词复习与排序

- **功能**：管理用户的复习单词，支持多种排序方式
- **关键方法**：
  - `get_reviewing_word_records()`: 获取复习单词记录
  - `get_reviewing_words()`: 获取复习单词列表
  - `get_basis_options()`: 获取排序依据选项
  - `sort_words_by_basis()`: 根据指定依据排序单词

#### 2.2.3 随机考词功能

- **功能**：从用户的单词库中随机选取单词进行考核
- **关键方法**：
  - `on_inner_quiz_clicked()`: 开始随机考词
  - `build_quiz_items()`: 构建考词界面
  - `on_quiz_hint_clicked()`: 提供 AI 提示
  - `on_quiz_submit_clicked()`: 提交考核结果
  - `apply_quiz_proficiency_updates()`: 应用熟练度更新

#### 2.2.4 选词成文功能

- **功能**：根据用户选择的单词生成英文短文
- **关键方法**：
  - `on_inner_wordcraft_clicked()`: 激活选词成文功能
  - `run_wordcraft_ai_generation()`: 运行 AI 生成短文
  - `build_wordcraft_prompt()`: 构建 AI 提示词
  - `run_wordcraft_explain_flow()`: 运行解释流程

#### 2.2.5 单词关联功能

- **功能**：管理单词之间的关联关系
- **关键方法**：
  - `add_word_link()`: 添加单词关联
  - `delete_word_link()`: 删除单词关联
  - `get_word_links()`: 获取单词关联
  - `build_words_link_section()`: 构建关联单词界面

#### 2.2.6 收藏夹管理

- **功能**：管理用户的单词收藏夹
- **关键方法**：
  - `toggle_favorite_current()`: 切换当前单词的收藏状态
  - `load_favorites_list()`: 加载收藏夹列表
  - `get_current_folder_id()`: 获取当前收藏夹 ID
  - `load_folders()`: 加载收藏夹

#### 2.2.7 笔记管理

- **功能**：管理用户的单词笔记
- **关键方法**：
  - `get_note()`: 获取单词笔记
  - `save_current_note()`: 保存当前笔记

### 2.3 技术实现亮点

1. **Mixin 设计模式**：使用 Mixin 类将功能模块化，便于集成到主应用中
2. **多线程处理**：使用 threading 模块处理 AI 请求，避免阻塞 UI
3. **SQLite 数据库操作**：直接操作数据库进行数据存储和检索
4. **PyQt6 UI 组件**：使用 PyQt6 构建用户界面
5. **AI 集成**：与各种 AI 模型集成，提供智能功能
6. **响应式设计**：根据用户操作动态更新 UI

## 3. 代码结构与关键类/方法

### 3.1 UserFeaturesMixin 类

这是文件的核心类，提供了所有用户相关的功能。它被设计为一个 Mixin 类，可以与其他类混合使用。

### 3.2 关键方法分类

#### 3.2.1 数据管理方法

- **数据库操作**：直接操作 SQLite 数据库，如 `touch_reviewing_word()`, `increment_query_count()`
- **配置管理**：管理用户配置，如 `load_wordcraft_config()`, `save_wordcraft_config()`

#### 3.2.2 UI 相关方法

- **界面初始化**：如 `init_inner_workspace()`, `_init_quiz_panel()`
- **界面更新**：如 `refresh_internal_page()`, `update_inner_toolbar_visual()`
- **事件处理**：如 `on_inner_quiz_clicked()`, `on_word_link_clicked()`

#### 3.2.3 AI 相关方法

- **提示词管理**：如 `get_ai_prompts()`, `build_wordcraft_prompt()`
- **AI 调用**：如 `_quiz_hint_worker()`, `_wordcraft_worker()`
- **结果处理**：如 `on_quiz_grade_result()`, `on_wordcraft_explain_result()`

#### 3.2.4 辅助方法

- **文本处理**：如 `strip_special_markers()`, `markdown_to_html_fragment()`
- **数据排序**：如 `sort_words_by_basis()`
- **工具方法**：如 `parse_iso_ts()`, `normalize_link_pair()`

## 4. 功能修改与扩展指南

### 4.1 新增功能时的关注要点

#### 4.1.1 功能模块新增

| 功能模块 | 需要重点关注的文件 | 关注的联系 | 完全解耦的文件 |
|----------|-------------------|------------|----------------|
| AI 提示词管理 | user_features.py, ai_prompts.py | 提示词定义与使用的对应关系 | bootstrap.py, check_db.py, start.bat |
| 单词复习系统 | user_features.py | 与数据库操作的交互 | llm_translation.py, navigation.py |
| 随机考词功能 | user_features.py | 与 AI 提示词的配合，与数据库的交互 | bootstrap.py, check_db.py, start.bat |
| 选词成文功能 | user_features.py | 与 AI 模型的交互，与用户配置的关联 | llm_translation.py, navigation.py |
| 单词关联功能 | user_features.py | 与数据库表结构的关联 | llm_translation.py, navigation.py |
| 收藏夹管理 | user_features.py | 与文件夹系统的集成 | llm_translation.py, navigation.py |
| 笔记管理 | user_features.py | 与数据库的交互 | llm_translation.py, navigation.py |
| UI 交互功能 | user_features.py, ui.py | 与 PyQt6 组件的交互 | bootstrap.py, check_db.py, start.bat |

#### 4.1.2 技术实现关注要点

1. **数据库操作**：
   - 关注数据库表结构的兼容性
   - 确保 SQL 语句的正确性和安全性
   - 注意事务处理和错误处理

2. **AI 集成**：
   - 关注 API 调用的稳定性和错误处理
   - 确保提示词的格式和内容正确
   - 注意多线程处理，避免阻塞 UI

3. **UI 设计**：
   - 关注用户体验和界面一致性
   - 确保响应式设计，适应不同操作
   - 注意事件处理和信号槽的连接

4. **配置管理**：
   - 关注配置的存储和加载
   - 确保默认值的合理性
   - 注意配置变更的兼容性

### 4.2 修改现有功能时的关注要点

#### 4.2.1 功能模块修改

| 功能模块 | 需要重点关注的文件 | 关注的联系 | 完全解耦的文件 |
|----------|-------------------|------------|----------------|
| AI 提示词管理 | user_features.py, ai_prompts.py | 提示词变更对其他功能的影响 | 所有与 AI 功能无关的文件 |
| 单词复习系统 | user_features.py | 排序逻辑变更对用户体验的影响 | 所有与复习功能无关的文件 |
| 随机考词功能 | user_features.py | 考词逻辑变更对熟练度计算的影响 | 所有与考词功能无关的文件 |
| 选词成文功能 | user_features.py | 生成逻辑变更对用户体验的影响 | 所有与成文功能无关的文件 |
| 单词关联功能 | user_features.py | 关联逻辑变更对数据库结构的影响 | 所有与关联功能无关的文件 |
| 收藏夹管理 | user_features.py | 收藏逻辑变更对文件夹系统的影响 | 所有与收藏功能无关的文件 |
| 笔记管理 | user_features.py | 笔记逻辑变更对数据库操作的影响 | 所有与笔记功能无关的文件 |
| UI 交互功能 | user_features.py, ui.py | 界面变更对用户操作的影响 | 所有与 UI 功能无关的文件 |

#### 4.2.2 技术实现关注要点

1. **兼容性**：
   - 关注现有数据的兼容性
   - 确保修改后的功能向后兼容
   - 注意 API 接口的稳定性

2. **性能**：
   - 关注修改对性能的影响
   - 确保数据库操作的效率
   - 注意 UI 响应的速度

3. **可靠性**：
   - 关注错误处理和异常情况
   - 确保功能的稳定性
   - 注意边界情况的处理

4. **可维护性**：
   - 关注代码的可读性和可维护性
   - 确保注释的完整性
   - 注意代码风格的一致性

### 4.3 功能扩展的最佳实践

1. **模块化设计**：
   - 将功能按模块划分，便于维护和扩展
   - 遵循现有的 Mixin 设计模式
   - 保持代码的清晰结构

2. **接口设计**：
   - 设计清晰的接口，便于与其他模块交互
   - 保持接口的稳定性
   - 注意参数和返回值的一致性

3. **测试策略**：
   - 为新增或修改的功能编写测试
   - 确保测试覆盖主要场景
   - 注意边界情况的测试

4. **文档更新**：
   - 及时更新相关文档
   - 确保文档与代码同步
   - 注意文档的清晰性和完整性


## 5. 性能优化建议

1. **数据库操作优化**：
   - 使用参数化查询避免 SQL 注入
   - 批量操作减少数据库连接次数
   - 合理使用索引提高查询速度

2. **UI 响应优化**：
   - 耗时操作使用多线程处理
   - 避免在主线程中进行网络请求
   - 使用异步更新 UI 元素

3. **代码结构优化**：
   - 模块化代码，将相关功能分组
   - 提取重复代码为公共方法
   - 使用更清晰的命名和注释

4. **内存使用优化**：
   - 及时释放不再使用的资源
   - 避免不必要的对象创建
   - 合理使用缓存

## 6. 常见问题与解决方案

### 6.1 AI 调用失败

**问题**：AI 调用失败，提示配置不完整

**解决方案**：
- 确保在设置中正确配置了 API URL、API Key 和模型
- 检查网络连接是否正常
- 查看错误信息，根据具体错误进行处理

### 6.2 数据库操作失败

**问题**：数据库操作失败，如插入、更新或查询失败

**解决方案**：
- 检查数据库连接是否正常
- 确保 SQL 语句正确
- 检查数据库表结构是否正确

### 6.3 UI 响应缓慢

**问题**：UI 响应缓慢，特别是在进行 AI 操作时

**解决方案**：
- 确保耗时操作在后台线程中执行
- 避免在主线程中进行网络请求
- 优化代码，减少不必要的计算

## 7. 总结

`user_features.py` 是一个功能丰富的模块，为应用提供了多种用户交互功能。它通过 Mixin 设计模式，将各种功能模块化，便于集成和扩展。

要修改或扩展此文件的功能，需要：
1. 理解现有代码结构和功能
2. 确定修改的范围和影响
3. 遵循现有的代码风格和设计模式
4. 测试修改后的功能，确保其正常工作

同时，需要关注与其他文件的依赖关系，特别是与 `infrastructure.py` 和 `ai_prompts.py` 的交互，以确保修改不会破坏现有功能。