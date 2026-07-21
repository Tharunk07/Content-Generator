from typing import Optional

from pydantic import BaseModel, Field


class GenerationInput(BaseModel):
    display_name: str
    description: str
    persona: str
    content_type: str
    audience: str
    tone: str
    language: str
    visual_style: str
    topic: str
    instructions: str
    is_regenerate: bool = False
    regenerate_query: str = ""


class GenerationRequest(BaseModel):
    source: str
    generation_id: str
    status: str = "PENDING"
    input: GenerationInput


class GenerationOutput(BaseModel):
    title: str
    content: str
    image_url: str
    word_count: int


class GenerationMetadata(BaseModel):
    generation_time_seconds: float
    quality_score: int
    version: int
    created_at: str
    completed_at: str


class GenerationResult(BaseModel):
    source: str
    generation_id: str
    status: str
    input: GenerationInput
    output: GenerationOutput
    metadata: GenerationMetadata


class GenerationResponse(BaseModel):
    source: str
    generation_id: str
    status: str
    output: GenerationOutput
    metadata: GenerationMetadata


class ContentDraft(BaseModel):
    title: str = Field(description="A concise, attention-grabbing title for the content")
    content: str = Field(description="The full body of the generated content, 300-400 words")


class QualityAssessment(BaseModel):
    quality_score: int = Field(ge=0, le=100, description="Overall quality score from 0-100")
