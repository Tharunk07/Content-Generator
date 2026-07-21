import logging

from google import genai
from google.cloud import storage
from google.oauth2 import service_account

from app.config import GCS_BUCKET_NAME, GCS_CREDENTIALS_PATH, GEMINI_IMAGE_MODEL
from app.schemas import ContentDraft, GenerationInput

logger = logging.getLogger(__name__)

_client = genai.Client()

_gcs_credentials = service_account.Credentials.from_service_account_file(GCS_CREDENTIALS_PATH)
_storage_client = storage.Client(project=_gcs_credentials.project_id, credentials=_gcs_credentials)
_bucket = _storage_client.bucket(GCS_BUCKET_NAME)


def _build_prompt(input_data: GenerationInput, draft: ContentDraft) -> str:
    return (
        f"Create a {input_data.visual_style} marketing visual to accompany a "
        f"{input_data.content_type} for {input_data.audience} about "
        f'"{input_data.topic}". The visual should evoke the theme: "{draft.title}". '
        "No text or words rendered in the image."
    )


def _upload_to_gcs(generation_id: str, image_bytes: bytes, mime_type: str) -> str:
    blob = _bucket.blob(f"{generation_id}.png")

    logger.info("Uploading image to GCS (bucket=%s, blob=%s)", GCS_BUCKET_NAME, blob.name)
    blob.upload_from_string(image_bytes, content_type=mime_type)

    try:
        blob.make_public()
    except Exception:
        logger.warning(
            "Could not set object ACL to public (bucket likely uses uniform "
            "bucket-level access) - ensure allUsers has objectViewer on the "
            "bucket for %s to be reachable",
            blob.public_url,
        )

    logger.info("Image uploaded to GCS (generation_id=%s, url=%s)", generation_id, blob.public_url)
    return blob.public_url


def generate_image(generation_id: str, input_data: GenerationInput, draft: ContentDraft) -> str:
    prompt = _build_prompt(input_data, draft)
    logger.info(
        "Generating image (generation_id=%s, model=%s, visual_style=%r)",
        generation_id,
        GEMINI_IMAGE_MODEL,
        input_data.visual_style,
    )

    try:
        response = _client.models.generate_content(
            model=GEMINI_IMAGE_MODEL,
            contents=prompt,
        )
    except Exception:
        logger.exception(
            "Gemini image generation call failed (generation_id=%s, model=%s)",
            generation_id,
            GEMINI_IMAGE_MODEL,
        )
        raise

    image_bytes = None
    mime_type = "image/png"
    for part in response.candidates[0].content.parts:
        if part.inline_data is not None:
            image_bytes = part.inline_data.data
            mime_type = part.inline_data.mime_type or mime_type
            break

    if image_bytes is None:
        logger.error("Gemini returned no image data (generation_id=%s)", generation_id)
        raise RuntimeError("Gemini did not return an image for this prompt")

    return _upload_to_gcs(generation_id, image_bytes, mime_type)
