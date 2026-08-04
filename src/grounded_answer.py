"""
The minimal retrieval-grounded generation call the eval suite scores.

pitch.py's real generation produces a full 10-pitch JSON tied to one
specific footage manifest -- excellent for making pitches, a poor
target for a stable golden-set eval, since manifest-dependent output
can't be scored against a fixed golden answer from one run to the
next. generate_grounded_answer isolates the one thing actually under
test: given retrieved reference chunks and a question, does the model
answer using only what's in those chunks? That's the same
retrieval -> generation contract pitch.py and shootgen.py depend on,
just without a footage manifest tangled into it.
"""
import os

from google import genai

from .gemini_utils import generate_with_retry, strip_fences

MODEL = "gemini-3-flash-preview"

PROMPT_TEMPLATE = """You are answering a question about a video production brief, using ONLY \
the reference notes below. Do not invent facts that aren't in the notes. If the notes don't \
answer the question, say so plainly instead of guessing.

Reference notes:
{context}

Question: {query}

Answer in 1-3 sentences, grounded strictly in the reference notes above."""


def build_prompt(query: str, retrieval_context: list) -> str:
    context_block = "\n".join(f"- {chunk}" for chunk in retrieval_context)
    return PROMPT_TEMPLATE.format(context=context_block, query=query)


def generate_grounded_answer(query: str, retrieval_context: list,
                              client=None, model: str = MODEL) -> str:
    if client is None:
        api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
        client = genai.Client(api_key=api_key)
    return strip_fences(generate_with_retry(client, model, build_prompt(query, retrieval_context)))
