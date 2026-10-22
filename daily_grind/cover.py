"""Make the daily cover image with Google's Nano Banana (Gemini image model)."""

import base64
import io
import os

from google import genai
from PIL import Image

MODEL = "gemini-nano-banana-2.1"

# Same look every day, so the covers feel like one family.
STYLE = (
    "Warm editorial illustration for the cover of a morning AI newsletter called "
    "The AI Daily Grind. Modern, clean, slightly playful flat illustration with soft grain. "
    "Colour palette: cream, caramel, espresso brown, with one small accent of teal. "
    "Soft morning light. A small coffee element somewhere in the scene. "
    "Wide 16:9 composition with calm space. "
    "No text, no letters, no logos, no brand marks, no real people's faces."
)


def make_cover(scene: str, out_path) -> None:
    """Generate one cover image for `scene` and save it as a JPEG at `out_path`."""
    client = genai.Client(
        api_key=os.environ["GEMINI_API_KEY"],
        http_options={"timeout": 120_000},  # milliseconds; never hang the daily run
    )
    interaction = client.interactions.create(
        model=MODEL,
        input=f"{STYLE}\n\nScene: {scene}",
        response_format={
            "type": "image",
            "mime_type": "image/jpeg",
            "aspect_ratio": "16:9",
            "image_size": "1K",
        },
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.open(io.BytesIO(base64.b64decode(interaction.output_image.data)))
    # Smaller file so the page loads fast on a phone
    image.convert("RGB").save(out_path, "JPEG", quality=80, optimize=True, progressive=True)
