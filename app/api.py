from fastapi import FastAPI
from pydantic import BaseModel, Field

from app.main import run_refactor_agent
from finetune.extension import describe_agent_finetune_playbook

app = FastAPI(title="Autonomous Refactor Agent", version="0.1.0")


class AnalyzeRequest(BaseModel):
    target_path: str = Field(..., min_length=1, description="Repo-relative path to analyze")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/refactor/analyze")
def analyze(body: AnalyzeRequest) -> dict:
    return run_refactor_agent(body.target_path)


@app.get("/v1/finetune/playbook")
def finetune_playbook() -> dict:
    return describe_agent_finetune_playbook()
