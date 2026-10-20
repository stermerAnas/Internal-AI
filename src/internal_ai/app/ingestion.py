from huggingface_hub.errors import (
    BadRequestError,
    HfHubHTTPError,
    RemoteEntryNotFoundError,
    RepositoryNotFoundError,
    RevisionNotFoundError,
    RevisionResolutionError,
)
from llama_index.core import SimpleDirectoryReader
from llama_index.core.node_parser import SentenceSplitter
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from sqlalchemy.exc import SQLAlchemyError

from internal_ai.app.database import Document_chunk, SessionLocal


class IngestionError(Exception):
    pass


def ingest_documents():
    try:
        model = HuggingFaceEmbedding(model_name="BAAI/bge-small-en-v1.5")

        documents = SimpleDirectoryReader("documents").load_data()

        splitter = SentenceSplitter(
            chunk_size=512,
            chunk_overlap=50,
        )

        nodes = splitter.get_nodes_from_documents(documents)

        texts = [node.text for node in nodes]

        embeddings = model.get_text_embedding_batch(texts)

        with SessionLocal() as session:
            for node, embedding in zip(nodes, embeddings):
                values = Document_chunk(
                    text=node.text,
                    meta_data=node.metadata,
                    embedding=embedding,
                )

                session.add(values)

            session.commit()

    except BadRequestError as exc:
        raise IngestionError(
            f"Invalid request while generating embeddings: {exc}"
        ) from exc

    except RemoteEntryNotFoundError as exc:
        raise IngestionError(f"Model entry not found: {exc}") from exc

    except RepositoryNotFoundError as exc:
        raise IngestionError(f"Hugging Face repository not found: {exc}") from exc

    except RevisionNotFoundError as exc:
        raise IngestionError(f"Hugging Face model revision not found: {exc}") from exc

    except RevisionResolutionError as exc:
        raise IngestionError(
            f"Could not resolve the Hugging Face model: {exc}"
        ) from exc

    except HfHubHTTPError as exc:
        if exc.response.status_code == 429:
            raise IngestionError(
                "Hugging Face rate limit exceeded while generating embeddings."
            ) from exc

        raise IngestionError(f"Hugging Face request failed: {exc}") from exc

    except SQLAlchemyError as exc:
        session.rollback()
        raise IngestionError(
            f"Database error while storing document chunks: {exc}"
        ) from exc

    except Exception as exc:
        raise IngestionError(
            f"Unexpected error during document ingestion: {exc}"
        ) from exc


ingest_documents()
