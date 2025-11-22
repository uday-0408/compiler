import http.client
import json
import time
import base64
from dotenv import load_dotenv  # type: ignore
import os

load_dotenv()
API_KEY = "e0f508d109mshd80507861f478a1p1dde1bjsn599150ef2022"

API_HOST = "judge0-ce.p.rapidapi.com"

headers = {
    "content-type": "application/json",
    "x-rapidapi-key": API_KEY,
    "x-rapidapi-host": API_HOST,
}

LANGUAGE_ID_MAP = {
    "python": 71,
    "cpp": 54,
    "c": 50,
    "java": 62,
    "javascript": 63,
    "go": 60,
    "rust": 73,
    "typescript": 74,
}


def get_language_id(language):
    if isinstance(language, int):
        return language
    return LANGUAGE_ID_MAP.get(language.lower(), 71)


def send_code_submission(code, language="python", input_data=""):
    language_id = get_language_id(language)
    encoded_code = base64.b64encode(code.encode()).decode()
    encoded_input = base64.b64encode(input_data.encode()).decode()
    payload = json.dumps(
        {
            "language_id": language_id,
            "source_code": encoded_code,
            "stdin": encoded_input,
        }
    )
    conn = http.client.HTTPSConnection(API_HOST)
    conn.request(
        "POST",
        "/submissions?base64_encoded=true&wait=false",
        body=payload,
        headers=headers,
    )
    res = conn.getresponse()
    data = res.read()
    conn.close()
    return json.loads(data)["token"]


def get_submission_result(token):
    """Retrieve the result of code execution."""
    conn = http.client.HTTPSConnection(API_HOST)
    conn.request("GET", f"/submissions/{token}?base64_encoded=false", headers=headers)
    res = conn.getresponse()
    result = res.read()
    conn.close()
    return json.loads(result)


def execute_code(code, language="python", input_data=""):
    """Execute code and return the result output or error."""
    try:
        print(code)
        token = send_code_submission(code, language, input_data)
        time.sleep(2)  # Wait before fetching result

        result = get_submission_result(token)
        if result.get("stdout"):
            return result["stdout"]
        elif result.get("stderr"):
            return "Error:\n" + result["stderr"]
        elif result.get("compile_output"):
            return "Compilation Error:\n" + result["compile_output"]
        else:
            return "Unknown Error: " + str(result)
    except Exception as e:
        return f"Exception occurred: {str(e)}"
