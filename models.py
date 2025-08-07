from database import Base
from sqlalchemy import Column, Integer, String, Text

class Flashcard(Base):
    __tablename__ = "flashcards"

    id = Column(Integer, primary_key=True, index=True)
    question = Column(Text)
    answer = Column(Text)
    distractors = Column(Text)  # ✅ NEW
    stack_name = Column(String, index=True)
