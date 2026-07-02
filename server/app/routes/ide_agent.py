from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..agents.code_agent import CodeAgent
from ..agents.planner_agent import PlannerAgent
from ..agents.review_agent import ReviewAgent

router = APIRouter()
code_agent = CodeAgent()
review_agent = ReviewAgent()
planner_agent = PlannerAgent()


class IdeAgentBody(BaseModel):
    agent: str | None = None
    input: str | None = None


@router.post("/api/ide/agent")
async def ide_agent(body: IdeAgentBody):
    if not body.agent or not body.input:
        raise HTTPException(status_code=400, detail="agent and input are required")

    try:
        if body.agent == "code":
            result = await code_agent.run(body.input)
            return {"output": result["output"]["answer"], "confidence": result["output"]["confidence"]}

        if body.agent == "planner":
            result = await planner_agent.run(body.input)
            plan = result["output"]
            steps = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(plan["steps"]))
            md = f"# Intent\n{plan['intent']}\n\n# Task Type\n{plan['taskType']}\n\n# Steps\n{steps}"
            return {"output": md}

        if body.agent == "review":
            critique = await review_agent.critique(body.input, question=body.input, evidence_summary=body.input, contradictions=[])
            issues = "\n".join(f"- {i}" for i in critique["issues"]) if critique["issues"] else "- None"
            md = f"# Verdict\n{'Pass' if critique['pass'] else 'Issues found'}\n\n# Issues\n{issues}\n\n# Confidence\n{critique['confidenceScore']}% — {critique['confidenceReason']}"
            return {"output": md}

        raise HTTPException(status_code=400, detail=f"Unknown agent: {body.agent}")
    except HTTPException:
        raise
    except Exception as err:
        raise HTTPException(status_code=500, detail=str(err))
