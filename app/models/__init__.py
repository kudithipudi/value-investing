from pydantic import BaseModel, Field


class IdeaIn(BaseModel):
    kind: str = Field(default="pitch", pattern="^(pitch|position)$")
    ticker: str | None = None
    company: str | None = None
    direction: str | None = Field(default=None, pattern="^(long|short|long/short)?$")
    thesis: str | None = None
    challenge: str | None = None
    author: str | None = None
    price_at_pitch: float | None = None
    pitch_date: str | None = None
    target_price: float | None = None


class IssueIn(BaseModel):
    title: str
    issue_number: int | None = None
    season: str | None = None
    source_url: str
