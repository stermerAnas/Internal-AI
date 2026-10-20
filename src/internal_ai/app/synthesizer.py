import httpx
from google.genai.errors import APIError
from llama_index.core import get_response_synthesizer
from llama_index.core.schema import NodeWithScore, TextNode
from llama_index.llms.google_genai import GoogleGenAI

from internal_ai.app.config import Settings
from internal_ai.app.retrieval import retrieve

settings = Settings()
llms = GoogleGenAI(
    model="gemini-3.7-flash", api_key=settings.api_key, max_retries=5, timeout=30
)
synthesizer = get_response_synthesizer(streaming=False, llm=llms)


class SynthesizeError(Exception):
    pass


def synthesize(query: str):

    chunks = retrieve(query)

    try:
        retrieved_nodes = [
            NodeWithScore(
                node=TextNode(
                    text=chunk.text,
                    metadata=chunk.meta_data,
                )
            )
            for chunk in chunks
        ]
        return synthesizer.synthesize(
            query,
            nodes=retrieved_nodes,
        )

    except APIError as e:
        if e.code == 429:
            raise SynthesizeError(
                "Rate limit exceeded while synthesizing response."
            ) from e
        elif e.code == 503:
            raise SynthesizeError(
                "Service unavailable while synthesizing response."
            ) from e

        elif e.code == 504:
            raise SynthesizeError("Gateway timeout while synthesizing response.") from e
        else:
            raise SynthesizeError(
                f"Error synthesizing response: {e.code} - {e.message}"
            ) from e
    except (httpx.TimeoutException, httpx.ConnectError) as e:
        raise SynthesizeError(f"Network error while synthesizing response: {e}") from e
    except Exception as exc:
        raise SynthesizeError(f"Error synthesizing response: {exc}") from exc
