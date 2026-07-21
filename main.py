import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI

from app.db import connect, disconnect, get_generations_collection
from app.schemas import (
    GenerationMetadata,
    GenerationOutput,
    GenerationRequest,
    GenerationResponse,
    GenerationResult,
)
from app.utils.content_generator import generate_content_draft, score_content_quality
from app.utils.image_generator import generate_image

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    connect()
    yield
    disconnect()


app = FastAPI(
    title="Content Generator",
    lifespan=lifespan,
    docs_url="/content-generation/docs",
    openapi_url="/content-generation/openapi.json",
)


@app.post("/content-generation/generate", response_model=GenerationResponse)
def generate(request: GenerationRequest) -> GenerationResponse:
    logger.info(
        "Received generation request (generation_id=%s, is_regenerate=%s)",
        request.generation_id,
        request.input.is_regenerate,
    )

    started_at = time.monotonic()
    created_at = datetime.now(timezone.utc)

    collection = get_generations_collection()

    previous_content = None
    next_version = 1

    if request.input.is_regenerate:
        latest = collection.find_one(
            {"generation_id": request.generation_id},
            sort=[("metadata.version", -1)],
        )
        if latest:
            previous_content = latest["output"]["content"]
            next_version = latest["metadata"]["version"] + 1
            logger.info(
                "Found previous version to use as context (generation_id=%s, previous_version=%d)",
                request.generation_id,
                latest["metadata"]["version"],
            )
        else:
            logger.warning(
                "is_regenerate=True but no previous version found (generation_id=%s)",
                request.generation_id,
            )

    try:
        draft = generate_content_draft(request.input, previous_content)
        quality_score = score_content_quality(request.input, draft)
        image_url = generate_image(request.generation_id, request.input, draft)
    except Exception:
        logger.exception("Generation failed (generation_id=%s)", request.generation_id)
        raise

    completed_at = datetime.now(timezone.utc)

    result = GenerationResult(
        source=request.source,
        generation_id=request.generation_id,
        status="COMPLETED",
        input=request.input,
        output=GenerationOutput(
            title=draft.title,
            content=draft.content,
            image_url=image_url,
            word_count=len(draft.content.split()),
        ),
        metadata=GenerationMetadata(
            generation_time_seconds=round(time.monotonic() - started_at, 2),
            quality_score=quality_score,
            version=next_version,
            created_at=created_at.isoformat(),
            completed_at=completed_at.isoformat(),
        ),
    )

    db_doc = result.model_dump()
    metadata = db_doc.pop("metadata")
    db_doc["created_at"] = metadata.pop("created_at")
    db_doc["completed_at"] = metadata.pop("completed_at")
    db_doc["metadata"] = metadata

    collection.insert_one(db_doc)
    logger.info(
        "Generation completed and stored (generation_id=%s, version=%d, quality_score=%d)",
        request.generation_id,
        next_version,
        quality_score,
    )

    return GenerationResponse(
        source=result.source,
        generation_id=result.generation_id,
        status=result.status,
        output=result.output,
        metadata=result.metadata,
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080)
