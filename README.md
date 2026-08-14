# Personal-Study-Desk

# 多智能体 AI 学习助手

一个基于多智能体架构的桌面学习助手。程序使用 PySide6 构建原生窗口，不依赖浏览器，适合在学习过程中完成学习计划制定、AI 辅导、测验练习和文档问答。

## 功能总览

- **个性化学习分析**：根据学科、知识水平、目标、可用时间和学习风格生成学生分析。
- **学习路线图**：输出分阶段、带里程碑的个性化学习路径，并支持下载为 Markdown。
- **学习资源**：自动搜索并推荐课程、视频、书籍、文章和练习平台。
- **测验生成**：按难度、重点领域和题目数量生成带解析的测验。
- **AI 辅导**：采用聊天式界面，围绕单个问题提供逐步讲解、示例和延伸内容。
- **文档问答（RAG）**：上传 PDF 或文本文件后，基于文档内容回答问题。
- **深色模式**：在左侧设置中切换，并自动记住偏好。
- **历史生成记录**：每次完整生成计划都会写入侧边栏历史，可随时切回任意一次计划。

## 界面说明

### 左侧栏

- 点击「设置」会在同一侧栏内展开或收起配置区域，不额外弹出页面。
- 设置区域包含：AI 提供商、模型、API 密钥、深色模式、关于。
- 「历史生成」列表显示每次生成的计划主题与时间，点击即可打开对应内容。

### 主区域

生成学习计划后，主区域会显示 5 个标签页：

1. 学习路线
2. 学习资源
3. 生成测验
4. AI 辅导
5. 文档问答（RAG）

## 快速开始

### 源码运行

```bash
pip install -r requirements.txt
pythonw main_gui.py
```

如需在终端查看错误信息：

```bash
python main_gui.py --console
```

首次使用请点击左侧「设置」，选择 AI 提供商并粘贴 API 密钥。DeepSeek 与 Groq 适合日常使用，OpenAI 需要付费密钥。

### 打包版本

- 直接运行 `dist\StudyAssistant.exe`。
- 需要重新打包时执行 `build_exe.bat`，产物位于 `dist\StudyAssistant.exe`。

## 数据与配置

程序将用户数据统一保存在系统用户目录：

```text
%APPDATA%\StudyAssistant\
├── study_assistant_state.json   # 当前计划与历史生成记录
├── settings.json                # 深色模式等界面偏好
└── study_assistant.log          # 运行诊断日志
```

提示词配置位于项目根目录 `prompts.yaml`，当前全部使用简体中文，并保留 `{topic}`、`{question}` 等动态占位符。

## 技术架构

```text
PySide6 GUI (main_gui.py)
        │
        ▼
业务编排层 (business.py)
        │
        ├── 智能体工厂 (study_agents.py)
        ├── 配置与提示词 (config.py / prompts.yaml)
        └── RAG 检索 (rag_helper.py / ChromaDB)
```

工作流：

```text
输入学习目标
  → 学生分析
  → 生成学习路线图
  → 查找学习资源
  → 进入仪表盘
```

更完整的组件说明见 [ARCHITECTURE.md](ARCHITECTURE.md)，文件导航见 [FILE_GUIDE.md](FILE_GUIDE.md)。

## 常见问题

### 启动后提示缺少模块

```bash
pip install -r requirements.txt
```

### 生成失败或提示 API 错误

- 确认侧边栏设置中已填写正确密钥。
- DeepSeek/Groq/OpenAI 密钥不要带多余空格或引号。
- 检查网络连接，或切换到其他模型重试。

### RAG 文档加载失败

- 确认 PDF 未加密且文件未损坏。
- 优先使用较小的文件。
- 可先转换为纯文本再上传。

### 历史记录为空

- 只有完整生成过学习计划后才会产生历史记录。
- 历史数据保存在 `%APPDATA%\StudyAssistant\study_assistant_state.json`。

## 许可

本项目仅用于教育目的。
