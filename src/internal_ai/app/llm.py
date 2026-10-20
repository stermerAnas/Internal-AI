import httpx
from google import genai
from google.genai import errors, types
from pydantic import BaseModel, Field

from internal_ai.app.config import Settings
from internal_ai.app.database import Conversation, Users
from internal_ai.app.synthesizer import synthesize


class LLMServiceError(Exception):
    pass


class LLMRateLimitError(Exception):
    def __init__(self, retry_after=None):
        self.retry_after = retry_after
        super().__init__("Gemini rate limit exceeded.")


class RAGToolRequest(BaseModel):
    query: str = Field(
        min_length=1, max_length=4000, description="The user's query for the RAG tool."
    )


settings = Settings()
client = genai.Client(
    api_key=settings.api_key,
    http_options=types.HttpOptions(
        timeout=30_000,
        retry_options=types.HttpRetryOptions(
            attempts=5,
            initial_delay=1.0,
            exp_base=2.0,
            max_delay=60.0,
            jitter=1.0,
        ),
    ),
)


def create_rag(user: Users):
    def rag(query: str):
        """Search the company's internal knowledge base for information relevant to the user's question."""

        if user.roles != "user":
            raise PermissionError("User does not have permission to use the RAG tool.")

        validate_query = RAGToolRequest.model_validate({"query": query})

        response = synthesize(validate_query.query)

        return {
            "answer": response.response,
            "sources": response.get_formatted_sources(),
        }

    return rag


def ask(query: str, user: Users, conversation: Conversation):
    try:
        conversation_history = [
            types.Content(
                role="model" if message.role == "assistant" else "user",
                parts=[types.Part(text=message.content)],
            )
            for message in conversation.messages
        ]

        rag_tool = create_rag(user)

        response = client.chats.create(
            model="gemini-3.6-flash",
            history=conversation_history,
            config=types.GenerateContentConfig(
                tools=[rag_tool],
            ),
        )

        result = response.send_message(message=query)
        return result.text

    except PermissionError:
        raise

    except errors.APIError as exc:
        print(f"Gemini error: {exc.code} - {exc.message}")

        if exc.code == 429:
            retry_after = None

            for detail in exc.details.get("error", {}).get("details", []):
                if detail.get("@type") == ("type.googleapis.com/google.rpc.RetryInfo"):
                    retry_after = detail.get("retryDelay")
                    break

            print(f"Rate limit exceeded. Retry after: {retry_after} seconds.")

            raise LLMRateLimitError(retry_after=retry_after) from exc

        if exc.code == 503:
            raise LLMServiceError(
                "Service unavailable while processing the request."
            ) from exc

        if exc.code == 504:
            raise LLMServiceError(
                "Gateway timeout while processing the request."
            ) from exc

        raise LLMServiceError("Gemini API request failed.") from exc

    except (httpx.TimeoutException, httpx.ConnectError) as exc:
        raise LLMServiceError(
            f"Network error while processing the request: {exc}"
        ) from exc

    except Exception as exc:
        raise LLMServiceError(f"An unexpected error occurred: {exc}") from exc
