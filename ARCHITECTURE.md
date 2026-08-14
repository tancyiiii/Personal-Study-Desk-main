# 架构概览

本项目是一个基于多智能体的桌面学习助手。界面层、业务编排层、智能体层和数据层保持分离，便于单独修改和扩展。

## 整体结构

```text
┌───────────────────────────────────────────────┐
│            PySide6 桌面界面                    │
│                main_gui.py                    │
│  侧边栏 / 仪表盘 / AI 辅导 / RAG 问答          │
└─────────────────────┬─────────────────────────┘
                      │
                      ▼
┌───────────────────────────────────────────────┐
│          业务编排层 StudyAssistantHandler      │
│                business.py                    │
│  分析 / 路线图 / 资源 / 测验 / 辅导 / RAG      │
└──────┬──────────────────────────┬─────────────┘
       │                          │
       ▼                          ▼
┌──────────────────┐   ┌────────────────────────┐
│ 智能体工厂        │   │ RAG 检索               │
│ study_agents.py  │   │ rag_helper.py          │
│ 角色与模型配置    │   │ 文档处理 / 向量检索     │
└────────┬─────────┘   └───────────┬────────────┘
         │                         │
         ▼                         ▼
┌──────────────────┐   ┌────────────────────────┐
│ 配置与提示词      │   │ ChromaDB 向量数据库     │
│ config.py        │   └────────────────────────┘
│ prompts.yaml     │
└──────────────────┘
```

## 模块职责

### main_gui.py

PySide6 原生界面层，负责：

- 左侧栏：AI 提供商、模型、API 密钥、深色模式、历史生成记录。
- 创建学习计划的步骤页与进度页。
- 学习仪表盘 5 个标签页。
- 线程化执行耗时任务，避免阻塞界面。
- 状态文件与设置文件的读写。

关键界面组件：

- `SidebarWidget`：侧边栏，设置区域可展开/收起。
- `Step1CategoryWidget` / `Step2DetailsWidget`：收集学习需求。
- `Step3GeneratingWidget`：展示生成进度。
- `DashboardWidget`：路线图、资源、测验、AI 辅导、RAG 问答。

### business.py

业务编排层，封装所有 AI 调用，界面层不直接操作模型。核心类为 `StudyAssistantHandler`。

关键方法：

- `analyze_student()`：生成学生分析。
- `create_roadmap()`：生成学习路线图。
- `find_resources()`：查找学习资源。
- `generate_quiz()`：生成测验。
- `get_tutoring()`：AI 辅导问答。
- `add_document_to_rag()` / `query_documents()`：RAG 文档问答。

### study_agents.py

智能体工厂，根据配置创建不同角色的智能体：

- `student_analyzer_agent()`
- `roadmap_creator_agent()`
- `quiz_generator_agent()`
- `tutor_agent()`
- `resource_finder_agent()`
- `rag_tutor_agent()`

每个智能体从 `prompts.yaml` 加载角色设定，并根据模型提供商选择不同后端。

### config.py

配置管理单例，负责：

- 加载 `prompts.yaml`。
- 获取角色、提示词、学习风格、学科分类和知识水平信息。
- 使用动态参数格式化提示词。

### prompts.yaml

全部提示词与角色设定文件，当前使用简体中文。结构：

- `personas`：各智能体角色。
- `prompts`：各任务提示词模板。
- `learning_styles`：学习风格说明与建议。
- `subject_categories`：学科分类与时长。
- `knowledge_levels`：知识水平定义。

模板中的 `{topic}`、`{question}`、`{context}` 等占位符由 `config.py` 在运行时替换。

### rag_helper.py

RAG 检索层，负责：

- 加载 PDF 和文本文件。
- 文本分块与向量化。
- 写入 ChromaDB 向量数据库。
- 相似性检索。
- 清空与统计文档数量。

## 数据持久化

用户数据统一保存在：

```text
%APPDATA%\StudyAssistant\
```

文件说明：

- `study_assistant_state.json`：当前计划 + 历史生成记录列表。
- `settings.json`：深色模式等偏好。
- `study_assistant.log`：错误日志。

历史记录采用“新记录插入最前”的方式保存，最多保留最近 20 条。每次完整生成计划时写入一条历史记录，其他刷新操作不会重复追加。

## 主要工作流

### 初始计划生成

```text
用户填写需求
  → 学生分析
  → 生成路线图
  → 查找资源
  → 保存当前计划并写入历史
  → 进入仪表盘
```

### AI 辅导

```text
用户输入问题
  → WorkerThread 后台调用 get_tutoring()
  → 聊天气泡追加回答
```

### RAG 文档问答

```text
上传 PDF/TXT
  → rag_helper 分块并写入 ChromaDB
  → 用户提问
  → 相似性检索
  → rag_tutor_agent 基于上下文回答
```

## 打包机制

`build_exe.bat` 调用 PyInstaller，使用 `study_assistant.spec` 打包为单文件 exe。

关键点：

- `assets/icon.ico` 同时用于 exe 文件图标和窗口图标。
- `prompts.yaml` 作为数据文件打包。
- `resource_path.py` 负责在源码运行和 exe 运行之间定位资源文件。
- 运行时通过 DWM API 切换原生标题栏深浅色。

## 设计原则

1. **界面与业务分离**：`main_gui.py` 只负责交互，计算逻辑在 `business.py`。
2. **配置驱动**：角色、提示词、学科、风格都来自 `prompts.yaml`。
3. **异步执行**：AI 请求在 `WorkerThread` 中运行，界面保持响应。
4. **可扩展**：新增智能体、提示词、学习风格或模型提供商时无需改动界面层。

## 相关文档

- [README.md](README.md)：项目总览。
- [QUICKSTART.md](QUICKSTART.md)：快速上手。
- [FILE_GUIDE.md](FILE_GUIDE.md)：文件说明。
