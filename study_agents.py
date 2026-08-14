from phi.agent import Agent
from phi.model.openai import OpenAIChat
from phi.model.groq import Groq
from phi.tools import Toolkit
from duckduckgo_search import DDGS
import json
import yaml
import os
from resource_path import resource_path


class ChineseDuckDuckGo(Toolkit):
    """DuckDuckGo search that prefers Simplified Chinese results."""

    def __init__(self, max_results: int = 8):
        super().__init__(name="chinese_duckduckgo")
        self.max_results = max_results
        self.register(self.search_chinese)

    def search_chinese(self, query: str) -> str:
        """Search DuckDuckGo with Simplified Chinese region settings."""
        try:
            ddgs = DDGS()
            results = list(ddgs.text(
                keywords=query,
                region="cn-zh",
                max_results=self.max_results,
            ))
            return json.dumps(results, ensure_ascii=False, indent=2)
        except Exception as exc:
            return json.dumps({"error": str(exc)}, ensure_ascii=False)


class StudyAgents:
    def __init__(self, topic, subject_category, knowledge_level, learning_goal, 
        time_available, learning_style, model_name="deepseek-chat", provider="deepseek"):
        """
        Initialize study assistant agents with student information and model configuration.
        
        Args:
            topic (str): The specific topic or subject to study
            subject_category (str): The category of the subject
            knowledge_level (str): Student's current knowledge level
            learning_goal (str): What the student wants to achieve
            time_available (str): How much time the student has
            learning_style (str): Student's preferred learning style
                    model_name (str): The model to use
                    provider (str): The AI provider ("deepseek", "openai", or "groq")
        """
        self.topic = topic
        self.subject_category = subject_category
        self.knowledge_level = knowledge_level
        self.learning_goal = learning_goal
        self.time_available = time_available
        self.learning_style = learning_style
        self.model_name = model_name
        self.provider = provider
        self.personas = self._load_personas()
    
    def _load_personas(self):
        """
        Load personas from the YAML file.
        
        Returns:
            dict: A dictionary of personas with system prompts
        """
        with open(resource_path("prompts.yaml"), "r", encoding="utf-8") as file:
            config = yaml.safe_load(file)
            return config.get("personas", {})
    
    def _get_learning_style_info(self):
        """
        Load learning style-specific information from the YAML file.
        
        Returns:
            dict: Learning style configuration
        """
        with open(resource_path("prompts.yaml"), "r", encoding="utf-8") as file:
            config = yaml.safe_load(file)
            return config.get("learning_styles", {}).get(self.learning_style, {})
    
    def _get_model(self, temperature=0.7):
        """
        Get the appropriate model based on the provider.
        
        Args:
            temperature (float): The temperature setting for the model
            
        Returns:
            Model: The configured model instance
        """
        if self.provider == "groq":
            return Groq(id=self.model_name, temperature=temperature)
        elif self.provider == "deepseek":
            api_key = os.getenv("DEEPSEEK_API_KEY", "").strip() or None
            return OpenAIChat(
                id=self.model_name,
                temperature=temperature,
                api_key=api_key,
                base_url="https://api.deepseek.com"
            )
        else:
            return OpenAIChat(id=self.model_name, temperature=temperature)
    
    def student_analyzer_agent(self):
        """
        Create a student analyzer agent that assesses learning needs and gaps.
        
        Returns:
            Agent: A student analysis-focused agent
        """
        system_prompt = self.personas.get("student_analyzer", {}).get("system_prompt", "")
        learning_style_info = self._get_learning_style_info()
        
        full_prompt = f"""{system_prompt}
        
        You are analyzing a student who wants to learn about {self.topic}.
        
        STUDENT PROFILE:
        - Current Knowledge Level: {self.knowledge_level}
        - Learning Goal: {self.learning_goal}
        - Available Time: {self.time_available}
        - Learning Style: {self.learning_style}
        - Learning Style Notes: {learning_style_info.get('description', '')}
        """
        
        return Agent(
            model=self._get_model(temperature=0.6),
            system_prompt=full_prompt
        )
    
    def roadmap_creator_agent(self):
        """
        Create a roadmap creator agent that designs personalized learning paths.
        
        Returns:
            Agent: A roadmap creation-focused agent
        """
        system_prompt = self.personas.get("roadmap_creator", {}).get("system_prompt", "")
        learning_style_info = self._get_learning_style_info()
        recommendations = learning_style_info.get('recommendations', [])
        
        full_prompt = f"""{system_prompt}
        
        You are creating a personalized learning roadmap for {self.topic}.
        
        STUDENT CONTEXT:
        - Knowledge Level: {self.knowledge_level}
        - Learning Goal: {self.learning_goal}
        - Time Available: {self.time_available}
        - Learning Style: {self.learning_style}
        
        LEARNING STYLE RECOMMENDATIONS:
        {chr(10).join(f'- {rec}' for rec in recommendations)}
        """
        
        return Agent(
            model=self._get_model(temperature=0.7),
            system_prompt=full_prompt
        )
    
    def quiz_generator_agent(self):
        """
        Create a quiz generator agent that creates assessments and practice questions.
        
        Returns:
            Agent: A quiz generation-focused agent
        """
        system_prompt = self.personas.get("quiz_generator", {}).get("system_prompt", "")
        
        full_prompt = f"""{system_prompt}
        
        You are creating quizzes for a student learning {self.topic}.
        
        STUDENT LEVEL: {self.knowledge_level}
        
        Ensure questions are appropriate for this knowledge level and help the student 
        progress toward their goal: {self.learning_goal}
        """
        
        return Agent(
            model=self._get_model(temperature=0.5),
            system_prompt=full_prompt
        )
    
    def tutor_agent(self):
        """
        Create a tutor agent that explains concepts and answers questions.
        
        Returns:
            Agent: A tutoring-focused agent
        """
        system_prompt = self.personas.get("tutor_agent", {}).get("system_prompt", "")
        learning_style_info = self._get_learning_style_info()
        
        full_prompt = f"""{system_prompt}
        
        You are tutoring a student on {self.topic}.
        
        STUDENT CONTEXT:
        - Knowledge Level: {self.knowledge_level}
        - Learning Style: {self.learning_style} - {learning_style_info.get('description', '')}
        
        Adapt your explanations to match their learning style and knowledge level.
        """
        
        return Agent(
            model=self._get_model(temperature=0.7),
            system_prompt=full_prompt
        )
    
    def resource_finder_agent(self):
        """
        Create a resource finder agent that searches for learning materials.
        
        Returns:
            Agent: A resource finding-focused agent with search capabilities
        """
        system_prompt = self.personas.get("resource_finder", {}).get("system_prompt", "")
        learning_style_info = self._get_learning_style_info()
        
        full_prompt = f"""{system_prompt}
        
        You are finding learning resources for {self.topic}.
        
        STUDENT PREFERENCES:
        - Knowledge Level: {self.knowledge_level}
        - Learning Style: {self.learning_style}
        - Learning Goal: {self.learning_goal}
        
        Prioritize resources that match the {self.learning_style} learning style.

        IMPORTANT:
        - Search with Simplified Chinese keywords whenever possible.
        - Prefer Chinese learning platforms (B站、中国大学MOOC、学堂在线、菜鸟教程、知乎、掘金、官方文档中文版等).
        - Respond entirely in Simplified Chinese, including resource names, links, and descriptions.
        - Only include an English resource when it is clearly the best option, and still describe it in Chinese.
        """
        
        return Agent(
            model=self._get_model(temperature=0.6),
            system_prompt=full_prompt,
            tools=[ChineseDuckDuckGo()]
        )
    
    def rag_tutor_agent(self, knowledge_base=None):
        """
        Create a RAG-enabled tutor agent that can answer questions using uploaded documents.
        
        Args:
            knowledge_base: The knowledge base/vector store to use for RAG
            
        Returns:
            Agent: A RAG-enabled tutoring agent
        """
        system_prompt = self.personas.get("tutor_agent", {}).get("system_prompt", "")
        
        full_prompt = f"""{system_prompt}
        
        You are tutoring a student on {self.topic} using provided study materials.
        
        IMPORTANT:
        - Base your answers on the provided context from the student's documents
        - If information isn't in the provided context, acknowledge this
        - Cite specific sections when referencing the materials
        - Help the student understand the material deeply
        
        STUDENT LEVEL: {self.knowledge_level}
        """
        
        agent_config = {
            "model": self._get_model(temperature=0.6),
            "system_prompt": full_prompt
        }
        
        # Add knowledge base if provided
        if knowledge_base:
            agent_config["knowledge_base"] = knowledge_base
            agent_config["search_knowledge"] = True
        
        return Agent(**agent_config)
