from pydantic import BaseModel, Field


class Job(BaseModel):
    id: str
    company: str
    title: str
    location: str
    description: str
    employment_type: str = ""
    experience: str = ""
    skills: list[str] = Field(default_factory=list)
    url: str
    source: str
