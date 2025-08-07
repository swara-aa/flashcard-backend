from fastapi import FastAPI, UploadFile, File, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session
import fitz
import openai
import os
import re
import json
from dotenv import load_dotenv
from ast import literal_eval

import database
import models
from models import Flashcard

load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")

models.Base.metadata.create_all(bind=database.engine)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_db():
    db = database.SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.get("/")
def read_root():
    return {"message": "Hello from FastAPI!"}

@app.post("/upload-pdf")
async def upload_pdf(pdf: UploadFile = File(...)):
    try:
        pdf_bytes = await pdf.read()
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            text = "".join([page.get_text() for page in doc])
        return {"extracted_text": text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read PDF: {str(e)}")

class TextInput(BaseModel):
    text: str

@app.post("/generate-flashcards")
async def generate_flashcards(payload: TextInput, db: Session = Depends(get_db)):
    try:
        chunks = [payload.text[i:i+2000] for i in range(0, len(payload.text), 2000)]
        generated_cards = []

        for chunk in chunks:
            prompt = f"""
            From the PDF provided, create 5 flashcards that would help a student understand the concepts in this chunk:

            {chunk}

            Format:
            Q1: ...
            A1: ...
            Q2: ...
            A2: ...
            """

            response = openai.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
            )

            content = response.choices[0].message.content
            qa_pairs = re.findall(r"(Q\d+:.*?)(?:\n|$)(A\d+:.*?)(?:\n|$)", content)

            for q, a in qa_pairs:
                question = q[3:].strip()
                answer = a[3:].strip()

                distractor_prompt = f"""
                The correct answer to the following question is: "{answer}"

                Generate 3 realistic and plausible but incorrect answers (distractors) for this question:
                "{question}"

                Respond ONLY with a JSON list of 3 strings. Do NOT include labels like A, B, or C.
                """

                distractor_response = openai.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=[{"role": "user", "content": distractor_prompt}],
                    temperature=0.7,
                )

                raw_output = distractor_response.choices[0].message.content.strip()

                try:
                    if raw_output.startswith("["):
                        distractors = json.loads(raw_output)
                        if not all(isinstance(d, str) for d in distractors):
                            raise ValueError("Distractors must be strings")
                        distractors = distractors[:3]
                    else:
                        raise ValueError("Not a JSON list")
                except Exception as e:
                    print("❌ Failed to parse distractors:", e)
                    distractors = ["Incorrect Answer 1", "Incorrect Answer 2", "Incorrect Answer 3"]

                flashcard = Flashcard(
                    question=question,
                    answer=answer,
                    distractors=json.dumps(distractors)
                )
                db.add(flashcard)

                generated_cards.append({
                    "question": question,
                    "answer": answer,
                    "distractors": distractors
                })

        db.commit()
        return {"cards": generated_cards}

    except Exception as e:
        print("❌ Error during flashcard generation:", e)
        raise HTTPException(status_code=500, detail=str(e))

class StackInput(BaseModel):
    stack_name: str
    cards: list[dict]

@app.post("/save-stack")
def save_stack(data: StackInput, db: Session = Depends(get_db)):
    try:
        for card in data.cards:
            db.add(Flashcard(
                question=card["question"],
                answer=card["answer"],
                stack_name=data.stack_name,
                distractors=json.dumps(card.get("distractors", []))
            ))
        db.commit()
        return {"message": "Stack saved successfully"}
    except Exception as e:
        print("Error saving stack:", e)
        raise HTTPException(status_code=500, detail="Failed to save stack.")

@app.get("/get-stacks")
def get_stacks(db: Session = Depends(get_db)):
    stacks = db.query(Flashcard.stack_name).distinct().all()
    return {"stacks": [s[0] for s in stacks if s[0] is not None]}

@app.get("/get-stack/{stack_name}")
def get_stack(stack_name: str, db: Session = Depends(get_db)):
    flashcards = db.query(Flashcard).filter(Flashcard.stack_name == stack_name).all()
    return {
        "cards": [
            {
                "question": card.question,
                "answer": card.answer,
                "distractors": literal_eval(card.distractors or "[]")
            }
            for card in flashcards
        ]
    }
