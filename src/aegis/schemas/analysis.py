from pydantic import BaseModel, Field


class SyntheticAnalysisRequest(BaseModel):
    seed: int = 26151
    actor_count: int = Field(default=4, ge=2, le=50)
    min_score: float = Field(default=0.0, ge=0.0, le=1.0)


class SyntheticAnalysisResponse(BaseModel):
    seed: int
    actor_count: int
    evidence_count: int
    relationship_count: int
    candidate_count: int
    persisted_hypothesis_count: int
    hypotheses: list[dict[str, object]]
