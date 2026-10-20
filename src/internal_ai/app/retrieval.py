from huggingface_hub.errors import (
    BadRequestError,
    HfHubHTTPError,
    RemoteEntryNotFoundError,
    RepositoryNotFoundError,
    RevisionNotFoundError,
    RevisionResolutionError,
)
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from internal_ai.app.database import Document_chunk, SessionLocal


class RetrieveError(Exception):
    pass


def retrieve(query: str, limit: int = 1):
    try:
        model = HuggingFaceEmbedding(model_name="BAAI/bge-small-en-v1.5")
        embedded = model.get_query_embedding(query)
        with SessionLocal() as s:
            stmt = (
                select(Document_chunk)
                .order_by(Document_chunk.embedding.cosine_distance(embedded))
                .limit(limit)
            )

            return s.scalars(stmt).all()
    except BadRequestError as e:
        raise RetrieveError(f"Error retrieving document chunks: {e}") from e
    except RemoteEntryNotFoundError as e:
        raise RetrieveError(f"Entry not found: {e}") from e
    except RepositoryNotFoundError as e:
        raise RetrieveError(f"Repo not found: {e}") from e
    except RevisionNotFoundError as e:
        raise RetrieveError(f"Revision not found: {e}") from e
    except RevisionResolutionError as e:
        raise RetrieveError(f"No internet connection: {e}") from e
    except SQLAlchemyError as e:
        raise RetrieveError(f"Database retrieval error: {e}") from e
    except HfHubHTTPError as e:
        if e.response.status_code == 429:
            raise RetrieveError(
                "Rate limit exceeded while retrieving document chunks."
            ) from e
        else:
            raise RetrieveError(
                f"Error retrieving document chunks: {e.response.status_code} - {e.response.text}"
            ) from e
    except Exception as exc:
        raise RetrieveError(f"Error retrieving document chunks: {exc}") from exc
