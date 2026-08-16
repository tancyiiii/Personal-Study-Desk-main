# business.py — Pure business logic layer
# =========================================
# All AI calls, data processing, and RAG operations.
# Zero GUI imports, reusable independently.

import json
import os
import re
import sys
import yaml
from dotenv import load_dotenv
from typing import Callable, Optional, Dict, Any, List

from resource_path import resource_path
from schemas import QuizSet
import demo_data

# DeepSeek's OpenAI-compatible endpoint rejects OpenAI's "developer" role.
# PhiData maps system messages to "developer" by default, so keep them as
# "system" for every provider in this app.
import phi.model.openai.chat as _phi_chat
_original_fmt = _phi_chat.OpenAIChat.format_message

def _patched_fmt(self, msg, map_system_to_developer=False):
    return _original_fmt(self, msg, map_system_to_developer)

_phi_chat.OpenAIChat.format_message = _patched_fmt

def _load_environment():
    load_dotenv()
    if getattr(sys, "frozen", False):
        load_dotenv(os.path.join(os.path.dirname(sys.executable), ".env"))


_load_environment()

from config import ConfigManager
from study_agents import StudyAgents
from rag_helper import RAGHelper


# ── Public helper: set env var for the chosen provider ──
def set_api_key_env(provider: str, api_key: str) -> None:
    """Set the environment variable for the given provider."""
    api_key = api_key.strip()
    if api_key and not api_key.isascii():
        raise ValueError("API 密钥只能包含 ASCII 字符，请检查是否粘贴了正确的密钥（不要包含中文）。")
    env_map = {
        "deepseek": "DEEPSEEK_API_KEY",
        "openai":   "OPENAI_API_KEY",
        "groq":     "GROQ_API_KEY",
    }
    var_name = env_map.get(provider)
    if var_name:
        os.environ[var_name] = api_key


# ── Re-export original pure classes ──
__all__ = [
    "ConfigManager", "StudyAgents", "RAGHelper", "StudyAssistantHandler",
    "DemoStudyAssistantHandler", "set_api_key_env",
]


# ── StudyAssistantHandler — stripped of all Streamlit dependencies ──
class StudyAssistantHandler:
    """Orchestrates all AI study-assistant operations. No GUI dependency."""

    def __init__(self, topic, subject_category, knowledge_level, learning_goal,
                 time_available, learning_style, model_name="deepseek-v4-flash",
                 provider="deepseek", trace_callback: Optional[Callable] = None):
        self.topic = topic
        self.subject_category = subject_category
        self.knowledge_level = knowledge_level
        self.learning_goal = learning_goal
        self.time_available = time_available
        self.learning_style = learning_style
        self.model_name = model_name
        self.provider = provider
        self.trace_callback = trace_callback
        self.agents = StudyAgents(
            topic, subject_category, knowledge_level, learning_goal,
            time_available, learning_style, model_name, provider,
            trace_callback=trace_callback,
        )
        self.config = self._load_config()
        self.rag_helper: Optional[RAGHelper] = None
        self._tutor_agent = None
        self._rag_tutor_agent = None

    # ── private helpers ──
    def _load_config(self) -> dict:
        with open(resource_path("prompts.yaml"), "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def _format_prompt(self, prompt_template: str, **kwargs) -> str:
        return prompt_template.format(**kwargs)

    def _trace(self, stage: str, detail: str) -> None:
        if self.trace_callback:
            try:
                self.trace_callback(stage, detail)
            except Exception:
                pass

    def set_trace_callback(self, callback: Optional[Callable]) -> None:
        self.trace_callback = callback
        self.agents.trace_callback = callback

    # ── public business methods ──
    def analyze_student(self) -> str:
        """Return student analysis markdown string."""
        self._trace("student_analyzer", "读取学生档案并评估能力差距")
        analyzer = self.agents.student_analyzer_agent()
        prompt = self._format_prompt(
            self.config["prompts"]["student_analysis"]["base"],
            topic=self.topic,
            subject_category=self.subject_category,
            knowledge_level=self.knowledge_level,
            learning_goal=self.learning_goal,
            time_available=self.time_available,
            learning_style=self.learning_style,
        )
        self._trace("student_analyzer", "已生成学情分析")
        resp = analyzer.run(prompt, stream=False)
        return resp.content

    def create_roadmap(self, student_analysis: str) -> str:
        """Return learning roadmap markdown string."""
        self._trace("roadmap_creator", "编排学习阶段、里程碑与复习节点")
        creator = self.agents.roadmap_creator_agent()
        prompt = self._format_prompt(
            self.config["prompts"]["roadmap_creation"]["base"],
            student_analysis=student_analysis,
            topic=self.topic,
            learning_goal=self.learning_goal,
            time_available=self.time_available,
            knowledge_level=self.knowledge_level,
        )
        self._trace("roadmap_creator", "已生成个性化学习路线")
        resp = creator.run(prompt, stream=False)
        return resp.content

    def find_resources(self) -> str:
        """Return learning resources markdown string."""
        self._trace("resource_finder", "调用国内搜索工具查找学习资源")
        finder = self.agents.resource_finder_agent()
        prompt = self._format_prompt(
            self.config["prompts"]["resource_finding"]["base"],
            topic=self.topic,
            learning_goal=self.learning_goal,
            knowledge_level=self.knowledge_level,
            learning_style=self.learning_style,
        )
        self._trace("resource_finder", "已整理并校验资源列表")
        resp = finder.run(prompt, stream=False)
        return resp.content

    def generate_quiz(self, difficulty_level: str = "intermediate",
                      focus_areas: str = "general", num_questions: int = 10) -> str:
        """Return quiz markdown string."""
        generator = self.agents.quiz_generator_agent()
        prompt = self._format_prompt(
            self.config["prompts"]["quiz_generation"]["base"],
            topic=self.topic,
            difficulty_level=difficulty_level,
            focus_areas=focus_areas,
            num_questions=num_questions,
        )
        resp = generator.run(prompt, stream=False)
        return resp.content

    def generate_quiz_structured(self, difficulty_level: str = "intermediate",
                                 focus_areas: str = "general",
                                 num_questions: int = 8) -> Dict[str, Any]:
        """Return a machine-readable quiz for interactive rendering."""
        self._trace("quiz_generator", "生成结构化测验")
        generator = self.agents.quiz_generator_agent(structured=True)
        schema = json.dumps(QuizSet.model_json_schema(), ensure_ascii=False, indent=2)
        prompt = self._format_prompt(
            self.config["prompts"]["quiz_generation"]["structured"],
            topic=self.topic,
            difficulty_level=difficulty_level,
            focus_areas=focus_areas,
            num_questions=num_questions,
            schema=schema,
        )
        resp = generator.run(prompt, stream=False)
        if isinstance(resp.content, QuizSet):
            return resp.content.model_dump()
        parsed = self._parse_quiz_json(resp.content)
        if parsed is not None:
            return parsed
        self._trace("quiz_generator", "模型未输出合法 JSON，返回可读版本")
        return {"questions": [], "raw": str(resp.content)}

    @staticmethod
    def _parse_quiz_json(content: Any) -> Optional[Dict[str, Any]]:
        """Extract a QuizSet-shaped object from common LLM output wrappers."""
        if not isinstance(content, str):
            return None
        text = content.strip()
        fence = re.search(r"```(?:json)?\s*(.+?)```", text, re.DOTALL)
        if fence:
            text = fence.group(1)
        else:
            start = text.find("{")
            end = text.rfind("}")
            if start >= 0 and end > start:
                text = text[start:end + 1]
        try:
            data = json.loads(text)
            return QuizSet.model_validate(data).model_dump()
        except Exception:
            return None

    def get_tutoring(self, student_question: str, context: str = "") -> str:
        """Return a tutoring response while preserving conversation memory."""
        self._trace("tutor_agent", "结合当前问题与历史对话进行多轮辅导")
        if self._tutor_agent is None:
            self._tutor_agent = self.agents.tutor_agent(persistent=True)
        prompt = self._format_prompt(
            self.config["prompts"]["tutoring"]["base"],
            student_question=student_question,
            context=context,
            knowledge_level=self.knowledge_level,
        )
        resp = self._tutor_agent.run(prompt, stream=False)
        self._trace("tutor_agent", "辅导回答已交付")
        return resp.content

    def clear_tutoring_memory(self) -> None:
        """Start a new tutoring conversation."""
        self._tutor_agent = None
        self._trace("tutor_agent", "已开启新对话")

    def initialize_rag(self, collection_name: str = "study_materials_bge") -> None:
        self.rag_helper = RAGHelper(collection_name=collection_name)

    def add_document_to_rag(self, file_path: str, file_type: str = "pdf") -> bool:
        if not self.rag_helper:
            self.initialize_rag()
        if file_type == "pdf":
            return self.rag_helper.load_pdf(file_path)
        elif file_type == "text":
            return self.rag_helper.load_text(file_path)
        return False

    def query_documents(self, question: str, k: int = 4) -> str:
        if not self.rag_helper:
            return "No documents have been uploaded yet. Please upload study materials first."
        self._trace("rag_retriever", "使用本地中文向量模型检索文档")
        relevant_docs = self.rag_helper.query_with_metadata(question, k=k)
        if not relevant_docs:
            return ("I couldn't find relevant information in your uploaded documents. "
                    "Please try rephrasing your question or upload more materials.")
        self._trace("rag_retriever", f"命中 {len(relevant_docs)} 个知识片段")
        context = "\n\n".join(
            f"[来源: {item['source']}, 页码: {item['page'] + 1}]\n{item['content']}"
            for item in relevant_docs
        )
        self._trace("rag_tutor", "依据文档证据组织回答")
        if self._rag_tutor_agent is None:
            self._rag_tutor_agent = self.agents.rag_tutor_agent(persistent=True)
        prompt = self._format_prompt(
            self.config["prompts"]["rag_query"]["base"],
            question=question,
            context=context,
        )
        resp = self._rag_tutor_agent.run(prompt, stream=False)
        self._trace("rag_tutor", "带引用的文档回答已交付")
        return resp.content

    def get_document_count(self) -> int:
        if not self.rag_helper:
            return 0
        return self.rag_helper.get_document_count()

    def clear_documents(self) -> bool:
        if not self.rag_helper:
            return False
        result = self.rag_helper.clear_database()
        if result:
            self._rag_tutor_agent = None
        return result


class DemoStudyAssistantHandler(StudyAssistantHandler):
    """Deterministic handler for offline judging and presentation."""

    def analyze_student(self) -> str:
        self._trace("demo_mode", "离线加载示例学情分析")
        return demo_data.DEMO_ANALYSIS

    def create_roadmap(self, student_analysis: str) -> str:
        self._trace("demo_mode", "离线加载示例学习路线")
        return demo_data.DEMO_ROADMAP

    def find_resources(self) -> str:
        self._trace("demo_mode", "离线加载国内学习资源")
        return demo_data.DEMO_RESOURCES

    def generate_quiz(self, difficulty_level: str = "intermediate",
                      focus_areas: str = "general", num_questions: int = 10) -> str:
        self._trace("demo_mode", "离线加载示例测验")
        return demo_data.DEMO_QUIZ_MARKDOWN

    def generate_quiz_structured(self, difficulty_level: str = "intermediate",
                                 focus_areas: str = "general",
                                 num_questions: int = 8) -> Dict[str, Any]:
        self._trace("demo_mode", "离线加载可判分测验")
        return demo_data.DEMO_QUIZ

    def get_tutoring(self, student_question: str, context: str = "") -> str:
        self._trace("demo_mode", "离线生成多轮辅导演示回答")
        return demo_data.demo_tutoring_answer(student_question)

    def query_documents(self, question: str, k: int = 4) -> str:
        self._trace("demo_mode", "离线生成带引用的文档回答")
        return demo_data.DEMO_RAG_ANSWER
