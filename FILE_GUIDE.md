# 文件指南

本文件说明项目中各文件的作用，方便快速定位需要修改的内容。

## 文档

| 文件 | 说明 |
| --- | --- |
| `README.md` | 项目总览、功能、快速开始与常见问题 |
| `QUICKSTART.md` | 5 分钟上手指南 |
| `ARCHITECTURE.md` | 系统架构与模块职责 |
| `FILE_GUIDE.md` | 当前文件指南 |

## 核心代码

| 文件 | 说明 |
| --- | --- |
| `main_gui.py` | PySide6 桌面界面：侧边栏、步骤页、仪表盘、AI 辅导聊天、RAG 问答、历史记录 |
| `business.py` | 业务编排层：学生分析、路线图、资源、测验、辅导、RAG 调用 |
| `study_agents.py` | 智能体工厂：定义各 AI 智能体角色、模型和工具 |
| `rag_helper.py` | RAG 检索：PDF/TXT 加载、分块、向量化、ChromaDB 查询 |
| `config.py` | 配置管理：加载 `prompts.yaml` 并格式化提示词 |
| `resource_path.py` | 资源路径解析：兼容源码运行与打包后的 exe |

## 配置与提示词

| 文件 | 说明 |
| --- | --- |
| `prompts.yaml` | 智能体角色、任务提示词、学习风格、学科分类、知识水平 |
| `requirements.txt` | Python 依赖清单 |
| `pyproject.toml` | 项目元数据与工具配置 |
| `.gitignore` | Git 忽略规则 |

## 启动与构建

| 文件 | 说明 |
| --- | --- |
| `StudyAssistant.vbs` | 无控制台方式启动 `main_gui.py` |
| `build_exe.bat` | 使用 PyInstaller 重新打包 exe |
| `study_assistant.spec` | PyInstaller 打包配置 |

## 资源与产物

| 路径 | 说明 |
| --- | --- |
| `assets/icon.ico` | 应用图标 |
| `dist/StudyAssistant.exe` | 打包后的单文件程序 |
| `dist/使用说明.txt` | 打包版用户说明 |

## 用户数据（运行时生成）

程序运行后会在系统用户目录生成：

```text
%APPDATA%\StudyAssistant\
├── study_assistant_state.json
├── settings.json
└── study_assistant.log
```

这些文件不需要手动维护。

## 按目标选择文件

### 修改界面

- 侧边栏、设置、历史记录：`main_gui.py` 中的 `SidebarWidget`
- 仪表盘标签页：`main_gui.py` 中的 `DashboardWidget`

### 修改 AI 行为

- 提示词内容：`prompts.yaml`
- 智能体角色与模型：`study_agents.py`
- 业务调用逻辑：`business.py`

### 修改 RAG

- 文档处理与检索：`rag_helper.py`

### 修改打包

- `study_assistant.spec`
- `build_exe.bat`
