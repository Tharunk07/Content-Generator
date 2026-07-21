import logging
from typing import Optional

from google import genai
from google.genai import types

from app.config import GEMINI_TEXT_MODEL
from app.schemas import ContentDraft, GenerationInput, QualityAssessment

logger = logging.getLogger(__name__)

_client = genai.Client()


def _build_prompt(input_data: GenerationInput, previous_content: Optional[str]) -> str:
    prompt = f"""
Content type: {input_data.content_type}
Target audience: {input_data.audience}
Tone: {input_data.tone}
Language: {input_data.language}
Visual style (for context only, not for the copy itself): {input_data.visual_style}
Topic: {input_data.topic}

Instructions: {input_data.instructions}

Write the content in {input_data.language}, matching the requested tone and
audience. The body must be between 300 and 400 words. Also produce a short,
attention-grabbing title.
""".strip()

    if previous_content:
        prompt += f"""

This is a regeneration request. Here is the most recent previously generated
version of this content, which you should use as context/base:

---
{previous_content}
---

Refine and improve on the previous version above according to this specific
request: {input_data.regenerate_query or "Improve overall quality, clarity, and engagement."}
"""

    return prompt


def generate_content_draft(
    input_data: GenerationInput, previous_content: Optional[str] = None
) -> ContentDraft:
    logger.info(
        "Generating content draft (topic=%r, content_type=%r, regenerate=%s)",
        input_data.topic,
        input_data.content_type,
        previous_content is not None,
    )
    prompt = _build_prompt(input_data, previous_content)

    try:
        response = _client.models.generate_content(
            model=GEMINI_TEXT_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=input_data.persona,
                response_mime_type="application/json",
                response_schema=ContentDraft,
            ),
        )
    except Exception:
        logger.exception("Gemini content generation call failed (model=%s)", GEMINI_TEXT_MODEL)
        raise

    draft = ContentDraft.model_validate_json(response.text)
    logger.info(
        "Content draft generated (title=%r, word_count=%d)",
        draft.title,
        len(draft.content.split()),
    )
    return draft


def score_content_quality(input_data: GenerationInput, draft: ContentDraft) -> int:
    logger.info("Scoring content quality (title=%r)", draft.title)
    prompt = f"""
Rate the following {input_data.content_type} on a scale of 0-100, considering
how well it fits the requested tone ("{input_data.tone}"), audience
("{input_data.audience}"), and topic ("{input_data.topic}"), as well as
overall clarity and engagement.

Title: {draft.title}

Content:
{draft.content}
""".strip()

    try:
        response = _client.models.generate_content(
            model=GEMINI_TEXT_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=QualityAssessment,
            ),
        )
    except Exception:
        logger.exception("Gemini quality scoring call failed (model=%s)", GEMINI_TEXT_MODEL)
        raise

    score = QualityAssessment.model_validate_json(response.text).quality_score
    logger.info("Quality score received: %d", score)
    return score
