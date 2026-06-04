from mistralai.client import Mistral
import os
import json
from typing import List, Dict
from sqlalchemy.orm import Session
from app.models.course import Course, Module
from app.models.lesson import Lesson

class AIService:
    def __init__(self):
        self.api_key = os.getenv("MISTRAL_API_KEY")
        self.model = "mistral-tiny" # Default to a fast/cheap model
        self.client = Mistral(api_key=self.api_key) if self.api_key else None

    async def get_course_context(self, db: Session, course_id: str) -> str:
        """
        Gathers text content from all lessons in a course to provide context for the AI.
        """
        course = db.query(Course).filter(Course.id == course_id).first()
        if not course:
            return ""

        context_parts = [f"Course Title: {course.title}", f"Description: {course.description}"]
        
        for module in course.modules:
            context_parts.append(f"\nModule: {module.title}")
            for lesson in module.lessons:
                if lesson.content_type == "text" and lesson.content_data:
                    # Limit content per lesson to avoid blowing out token limits for now
                    content_preview = lesson.content_data[:1000] 
                    context_parts.append(f"- Lesson: {lesson.title}\n  Content: {content_preview}")
        
        return "\n".join(context_parts)

    async def ask_question(self, db: Session, course_id: str, question: str) -> str:
        if not self.client:
            return "AI Service is not configured. Please add MISTRAL_API_KEY to your environment."

        course_context = await self.get_course_context(db, course_id)
        
        system_prompt = (
            "You are a helpful AI Learning Assistant for the Stratos LMS. "
            "Your goal is to help students understand course material. "
            "Use the provided course context to answer the student's question. "
            "If the answer isn't in the context, use your general knowledge but mention it's outside the course scope. "
            "Be concise, encouraging, and academic.\n\n"
            f"--- COURSE CONTEXT ---\n{course_context}\n----------------------"
        )

        try:
            chat_response = self.client.chat.complete(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": question},
                ],
            )
            return chat_response.choices[0].message.content
        except Exception as e:
            print(f"Mistral Error: {e}")
            return "Sorry, I encountered an error while processing your request."

    async def generate_quiz(self, content: str, num_questions: int = 5) -> List[Dict]:
        """
        Generates a quiz from the provided lesson content using AI.
        """
        if not self.client:
            raise Exception("AI Service not configured")

        prompt = (
            f"Generate a quiz with exactly {num_questions} questions based on the following educational content:\n\n"
            f"--- CONTENT ---\n{content}\n----------------\n\n"
            "Include a mix of these types:\n"
            "1. multiple_choice (4 options)\n"
            "2. fill_in_the_blanks (sentence with ___)\n"
            "3. objective (short one-word or one-phrase answer)\n"
            "4. essay (reflective question)\n\n"
            "Return the result as a raw JSON list of objects with this schema:\n"
            "[\n"
            "  {\n"
            "    \"type\": \"multiple_choice\",\n"
            "    \"question\": \"...\",\n"
            "    \"data\": {\"options\": [\"...\", \"...\", \"...\", \"...\"], \"correct_index\": 0},\n"
            "    \"explanation\": \"...\"\n"
            "  },\n"
            "  {\n"
            "    \"type\": \"fill_in_the_blanks\",\n"
            "    \"question\": \"The capital of France is ___.\",\n"
            "    \"data\": {\"answer\": \"Paris\"},\n"
            "    \"explanation\": \"...\"\n"
            "  }\n"
            "]\n"
            "Only return the JSON. No preamble or markdown blocks."
        )

        try:
            response = self.client.chat.complete(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
            )
            raw_content = response.choices[0].message.content
            # Clean possible markdown blocks if AI ignored 'Only return JSON'
            if "```json" in raw_content:
                raw_content = raw_content.split("```json")[1].split("```")[0]
            elif "```" in raw_content:
                raw_content = raw_content.split("```")[1].split("```")[0]
            
            return json.loads(raw_content.strip())
        except Exception as e:
            print(f"Quiz Generation Error: {e}")
            raise e

    async def generate_image_keyword(self, text: str) -> str:
        """
        Analyzes the provided text and returns a single keyword for image searching.
        """
        if not self.client:
            # Fallback
            return "education"

        prompt = (
            f"Analyze the following text and provide exactly ONE English keyword "
            f"that would be best for searching a professional stock photo for a course: '{text}'. "
            "Return only the keyword, no punctuation or extra text."
        )

        try:
            response = self.client.chat.complete(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
            )
            keyword = response.choices[0].message.content.strip().lower()
            return keyword
        except Exception as e:
            print(f"Keyword Generation Error: {e}")
            return "education"

ai_service = AIService()
