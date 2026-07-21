import logging
import secrets
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.db import connect, disconnect, get_agents_collection, get_generations_collection
from app.schemas import (
    AgentCreateResponse,
    AgentDetail,
    AgentInput,
    AgentListResponse,
    GenerationHistoryResponse,
    GenerationInput,
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/content-generation/agents", response_model=AgentCreateResponse)
def create_agent(request: AgentInput) -> AgentCreateResponse:
    agent_id = f"agt_{secrets.token_hex(5)}"
    created_at = datetime.now(timezone.utc)
    status = "created"

    collection = get_agents_collection()
    doc = request.model_dump()
    doc["agent_id"] = agent_id
    doc["status"] = status
    doc["created_at"] = created_at.isoformat()
    collection.insert_one(doc)

    logger.info("Agent created (agent_id=%s, display_name=%s)", agent_id, request.display_name)

    return AgentCreateResponse(
        agent_id=agent_id,
        status=status,
        created_at=created_at.isoformat(),
    )


@app.get("/content-generation/agents", response_model=AgentListResponse)
def list_agents() -> AgentListResponse:
    pipeline = [
        {"$sort": {"created_at": -1}},
        {"$group": {"_id": "$agent_id", "doc": {"$first": "$$ROOT"}}},
        {"$replaceRoot": {"newRoot": "$doc"}},
        {"$sort": {"created_at": -1}},
    ]
    agents = [AgentDetail(**doc) for doc in get_agents_collection().aggregate(pipeline)]
    return AgentListResponse(agents=agents)


@app.get("/content-generation/agents/{agent_id}", response_model=AgentDetail)
def get_agent(agent_id: str) -> AgentDetail:
    agent = get_agents_collection().find_one({"agent_id": agent_id})
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")

    return AgentDetail(**agent)


@app.get(
    "/content-generation/agents/{agent_id}/generations",
    response_model=GenerationHistoryResponse,
)
def get_agent_generations(agent_id: str) -> GenerationHistoryResponse:
    agent = get_agents_collection().find_one({"agent_id": agent_id})
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")

    cursor = get_generations_collection().find({"input.agent_id": agent_id}).sort(
        "created_at", -1
    )

    generations = []
    for doc in cursor:
        metadata = dict(doc["metadata"])
        metadata["created_at"] = doc["created_at"]
        metadata["completed_at"] = doc["completed_at"]
        generations.append(
            GenerationResponse(
                source=doc["source"],
                generation_id=doc["generation_id"],
                status=doc["status"],
                output=GenerationOutput(**doc["output"]),
                metadata=GenerationMetadata(**metadata),
            )
        )

    return GenerationHistoryResponse(generations=generations)


@app.put("/content-generation/agents/{agent_id}", response_model=AgentDetail)
def update_agent(agent_id: str, request: AgentInput) -> AgentDetail:
    collection = get_agents_collection()

    existing = collection.find_one({"agent_id": agent_id})
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")

    collection.update_one({"agent_id": agent_id}, {"$set": request.model_dump()})
    updated = collection.find_one({"agent_id": agent_id})

    logger.info("Agent updated (agent_id=%s, display_name=%s)", agent_id, request.display_name)

    return AgentDetail(**updated)


@app.post("/content-generation/generate", response_model=GenerationResponse)
def generate(request: GenerationRequest) -> GenerationResponse:
    logger.info(
        "Received generation request (generation_id=%s, is_regenerate=%s)",
        request.generation_id,
        request.input.is_regenerate,
    )

    started_at = time.monotonic()
    created_at = datetime.now(timezone.utc)

    agent = get_agents_collection().find_one({"agent_id": request.input.agent_id})
    if agent is None:
        raise HTTPException(
            status_code=404, detail=f"Agent not found: {request.input.agent_id}"
        )

    full_input = GenerationInput(
        agent_id=agent["agent_id"],
        display_name=agent["display_name"],
        description=agent["description"],
        persona=agent["persona"],
        content_type=agent["content_type"],
        audience=agent["audience"],
        tone=agent["tone"],
        language=agent["language"],
        visual_style=agent["visual_style"],
        topic=request.input.topic,
        instructions=request.input.instructions,
        is_regenerate=request.input.is_regenerate,
        regenerate_query=request.input.regenerate_query,
    )

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
        draft = generate_content_draft(full_input, previous_content)
        quality_score = score_content_quality(full_input, draft)
        image_url = generate_image(request.generation_id, full_input, draft)
    except Exception:
        logger.exception("Generation failed (generation_id=%s)", request.generation_id)
        raise

    completed_at = datetime.now(timezone.utc)

    result = GenerationResult(
        source=request.source,
        generation_id=request.generation_id,
        status="COMPLETED",
        input=full_input,
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
