import unittest

from business import DemoStudyAssistantHandler, StudyAssistantHandler
from quiz_engine import grade_quiz


class QuizEngineTests(unittest.TestCase):
    def test_option_letters_are_normalized(self):
        correct, graded, _ = grade_quiz(
            [
                {
                    "question": "q1",
                    "question_type": "single_choice",
                    "answer": "B",
                }
            ],
            {0: "B) pandas"},
        )
        self.assertEqual((correct, graded), (1, 1))

    def test_short_answers_are_not_auto_graded(self):
        correct, graded, results = grade_quiz(
            [
                {
                    "question": "q1",
                    "question_type": "short_answer",
                    "answer": "参考答案",
                }
            ],
            {0: "参考答案"},
        )
        self.assertEqual((correct, graded), (0, 0))
        self.assertFalse(results[0]["is_correct"])


class BusinessParserTests(unittest.TestCase):
    def test_parse_fenced_quiz_json(self):
        content = '''```json
{
  "questions": [
    {
      "question": "1+1?",
      "question_type": "single_choice",
      "options": ["1", "2"],
      "answer": "B",
      "explanation": "二",
      "core_concept": "算术"
    }
  ]
}
```'''
        parsed = StudyAssistantHandler._parse_quiz_json(content)
        self.assertEqual(parsed["questions"][0]["answer"], "B")


class DemoHandlerTests(unittest.TestCase):
    def test_demo_handler_has_closed_loop_outputs(self):
        handler = DemoStudyAssistantHandler(
            topic="Python 数据分析",
            subject_category="programming",
            knowledge_level="beginner",
            learning_goal="完成一个数据分析作品集",
            time_available="每周 3-5 小时",
            learning_style="visual",
        )
        self.assertIn("当前水平评估", handler.analyze_student())
        self.assertIn("路线图总览", handler.create_roadmap(""))
        self.assertIn("中国大学 MOOC", handler.find_resources())
        self.assertTrue(handler.generate_quiz_structured()["questions"])
        self.assertIn("详细讲解", handler.get_tutoring("什么是 pandas"))
        self.assertIn("来源引用", handler.query_documents("数据分析步骤"))


if __name__ == "__main__":
    unittest.main()
