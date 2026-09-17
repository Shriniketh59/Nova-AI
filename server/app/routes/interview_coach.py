import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..agents.problem_gen_agent import ProblemGenAgent
from ..agents.review_agent import ReviewAgent
from ..core import db
from ..middleware.auth_middleware import get_current_user
from ..utils.code_validation import quick_validate_code

router = APIRouter()

problem_gen_agent = ProblemGenAgent()
review_agent = ReviewAgent()


class NewProblemBody(BaseModel):
    category: str
    difficulty: str = "medium"


@router.post("/api/coach/problems", status_code=201)
async def new_problem(body: NewProblemBody, current_user: dict = Depends(get_current_user)):
    user_id = current_user["id"]
    result = await problem_gen_agent.run(body.category, body.difficulty)
    problem_data = result["output"]

    problem_result = await db.query(
        """INSERT INTO practice_problems (user_id, title, difficulty, category, description, constraints, example_input, example_output)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8) RETURNING *""",
        [
            user_id, problem_data["title"], body.difficulty, body.category,
            problem_data["description"], problem_data.get("constraints"),
            problem_data.get("example_input"), problem_data.get("example_output"),
        ],
    )
    problem = problem_result["rows"][0]

    session_result = await db.query(
        "INSERT INTO interview_sessions (user_id, problem_id) VALUES ($1, $2) RETURNING *",
        [user_id, problem["id"]],
    )
    session = session_result["rows"][0]

    return {"problem": problem, "sessionId": session["id"]}


@router.get("/api/coach/sessions")
async def list_sessions(current_user: dict = Depends(get_current_user)):
    user_id = current_user["id"]
    result = await db.query(
        """SELECT s.id, s.status, s.attempts, s.best_confidence, s.updated_at,
                  p.title, p.difficulty, p.category
           FROM interview_sessions s
           JOIN practice_problems p ON p.id = s.problem_id
           WHERE s.user_id = $1
           ORDER BY s.updated_at DESC""",
        [user_id],
    )
    return result["rows"]


@router.get("/api/coach/sessions/{session_id}")
async def get_session(session_id: str, current_user: dict = Depends(get_current_user)):
    user_id = current_user["id"]
    session_result = await db.query(
        """SELECT s.*, p.title, p.difficulty, p.category, p.description, p.constraints, p.example_input, p.example_output
           FROM interview_sessions s
           JOIN practice_problems p ON p.id = s.problem_id
           WHERE s.id = $1 AND s.user_id = $2""",
        [session_id, user_id],
    )
    if not session_result["rows"]:
        raise HTTPException(status_code=404, detail="Session not found")
    session = session_result["rows"][0]

    submissions_result = await db.query(
        "SELECT * FROM session_submissions WHERE session_id = $1 ORDER BY created_at ASC",
        [session_id],
    )

    return {"session": session, "submissions": submissions_result["rows"]}


class SubmitBody(BaseModel):
    code: str
    language: str = "python"


@router.post("/api/coach/sessions/{session_id}/submit")
async def submit_solution(session_id: str, body: SubmitBody, current_user: dict = Depends(get_current_user)):
    user_id = current_user["id"]
    session_result = await db.query(
        """SELECT s.*, p.description FROM interview_sessions s
           JOIN practice_problems p ON p.id = s.problem_id
           WHERE s.id = $1 AND s.user_id = $2""",
        [session_id, user_id],
    )
    if not session_result["rows"]:
        raise HTTPException(status_code=404, detail="Session not found")
    session = session_result["rows"][0]

    fenced_code = f"```{body.language}\n{body.code}\n```"
    validation = quick_validate_code(fenced_code)
    critique = await review_agent.critique(body.code, question=session["description"], domain="code")

    confidence_score = critique["confidenceScore"]
    confidence = {
        "score": confidence_score,
        "label": "high" if confidence_score >= 70 else "medium" if confidence_score >= 30 else "low",
        "reason": critique["confidenceReason"],
    }
    solved = validation["pass"] and confidence_score >= 70

    await db.query(
        "INSERT INTO session_submissions (session_id, code, language, validation, confidence, feedback) VALUES ($1, $2, $3, $4, $5, $6)",
        [session_id, body.code, body.language, json.dumps(validation), json.dumps(confidence), "; ".join(critique["issues"]) or None],
    )

    new_status = "solved" if solved else session["status"]
    best_confidence = max(session["best_confidence"] or 0, confidence_score)
    await db.query(
        "UPDATE interview_sessions SET attempts = attempts + 1, best_confidence = $1, status = $2, updated_at = now() WHERE id = $3",
        [best_confidence, new_status, session_id],
    )

    return {
        "validation": validation,
        "confidence": confidence,
        "feedback": critique["issues"],
        "status": new_status,
    }
