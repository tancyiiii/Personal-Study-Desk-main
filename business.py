# business.py — Pure business logic layer
# =========================================
# All AI calls, data processing, and RAG operations.
# Zero GUI imports, reusable independently.

import os
import sys
import yaml
from dotenv import load_dotenv
from typing import Optional, Dict, Any, List
from resource_path import resource_path

# ── DeepSeek monkey-patch (no "developer" role support) ──
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
    "set_api_key_env",
]


# ── StudyAssistantHandler — stripped of all Streamlit dependencies ──
class StudyAssistantHandler:
    """Orchestrates all AI study-assistant operations. No GUI dependency."""

    def __init__(self, topic, subject_category, knowledge_level, learning_goal,
                 time_available, learning_style, model_name="deepseek-chat",
                 provider="deepseek"):
        self.topic = topic
        self.subject_category = subject_category
        self.knowledge_level = knowledge_level
        self.learning_goal = learning_goal
        self.time_available = time_available
        self.learning_style = learning_style
        self.model_name = model_name
        self.provider = provider
        self.agents = StudyAgents(
            topic, subject_category, knowledge_level, learning_goal,
            time_available, learning_style, model_name, provider
        )
        self.config = self._load_config()
        self.rag_helper: Optional[RAGHelper] = None

    # ── private helpers ──
    def _load_config(self) -> dict:
        with open(resource_path("prompts.yaml"), "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def _format_prompt(self, prompt_template: str, **kwargs) -> str:
        return prompt_template.format(**kwargs)

    # ── public business methods ──
    def analyze_student(self) -> str:
        """Return student analysis markdown string."""
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
        resp = analyzer.run(prompt, stream=False)
        return resp.content

    def create_roadmap(self, student_analysis: str) -> str:
        """Return learning roadmap markdown string."""
        creator = self.agents.roadmap_creator_agent()
        prompt = self._format_prompt(
            self.config["prompts"]["roadmap_creation"]["base"],
            student_analysis=student_analysis,
            topic=self.topic,
            learning_goal=self.learning_goal,
            time_available=self.time_available,
            knowledge_level=self.knowledge_level,
        )
        resp = creator.run(prompt, stream=False)
        return resp.content

    def find_resources(self) -> str:
        """Return learning resources markdown string."""
        finder = self.agents.resource_finder_agent()
        prompt = self._format_prompt(
            self.config["prompts"]["resource_finding"]["base"],
            topic=self.topic,
            learning_goal=self.learning_goal,
            knowledge_level=self.knowledge_level,
            learning_style=self.learning_style,
        )
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

    def get_tutoring(self, student_question: str, context: str = "") -> str:
        """Return tutoring response string."""
        tutor = self.agents.tutor_agent()
        prompt = self._format_prompt(
            self.config["prompts"]["tutoring"]["base"],
            student_question=student_question,
            context=context,
            knowledge_level=self.knowledge_level,
        )
        resp = tutor.run(prompt, stream=False)
        return resp.content

    def initialize_rag(self, collection_name: str = "study_materials") -> None:
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
        relevant_docs = self.rag_helper.query(question, k=k)
        if not relevant_docs:
            return ("I couldn't find relevant information in your uploaded documents. "
                    "Please try rephrasing your question or upload more materials.")
        context = "\n\n".join(relevant_docs)
        rag_tutor = self.agents.rag_tutor_agent()
        prompt = self._format_prompt(
            self.config["prompts"]["rag_query"]["base"],
            question=question,
            context=context,
        )
        resp = rag_tutor.run(prompt, stream=False)
        return resp.content

    def get_document_count(self) -> int:
        if not self.rag_helper:
            return 0
        return self.rag_helper.get_document_count()

    def clear_documents(self) -> bool:
        if not self.rag_helper:
            return False
        return self.rag_helper.clear_database()
