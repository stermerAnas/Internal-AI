import time

import requests

url = "http://localhost:8000/conversations/3/messages"
token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI1IiwiZXhwIjoxNzg4NTI5ODQzfQ.w4-EQ7ZBuT6_LfNfLYbdSEGCKTjsPIhucwsDT3gsd2k"

headers = {
    "Authorization": f"Bearer {token}",
}

payload = {
    "message": "It also has a chat history. Quick question, What's our company's vacation policy?"
}

started_at = time.perf_counter()

try:
    response = requests.post(
        url,
        headers=headers,
        json=payload,

    )
    elapsed_seconds = time.perf_counter() - started_at

    print("Status:", response.status_code)
    print(f"Response time: {elapsed_seconds:.3f} seconds")

    try:
        print(response.json())
    except requests.exceptions.JSONDecodeError:
        print(response.text)
except requests.exceptions.Timeout:
    elapsed_seconds = time.perf_counter() - started_at
    print(f"Request timed out after {elapsed_seconds:.3f} seconds")
except requests.exceptions.RequestException as exc:
    elapsed_seconds = time.perf_counter() - started_at
    print(f"Request failed after {elapsed_seconds:.3f} seconds")
    print(exc)
