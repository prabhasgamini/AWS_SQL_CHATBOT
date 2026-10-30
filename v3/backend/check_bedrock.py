"""
Quick test of your Bedrock settings, without starting the whole app.

    python check_bedrock.py

It reads backend/.env, sends one tiny message to your model and says what to fix if it fails.
Your API key is never printed.
"""

import sys

import config
from agent import build_llm, explain_llm_error


def main():
    print(f"Settings file : {config.ENV_PATH} ({'found' if config.ENV_PATH.exists() else 'NOT FOUND'})")
    print(f"Provider      : {config.LLM_PROVIDER}")
    if config.LLM_PROVIDER == "bedrock":
        print(f"Region        : {config.AWS_REGION}")
        print(f"Model ID      : {config.BEDROCK_MODEL_ID or '(NOT SET)'}")
        print(f"API key       : {'present' if config.BEARER_TOKEN_SET else 'MISSING (AWS_BEARER_TOKEN_BEDROCK)'}")
    print()

    try:
        llm = build_llm()
        print("Sending a test message...")
        reply = llm.invoke("Reply with the single word: ready")
        text = reply.content if isinstance(reply.content, str) else str(reply.content)
        print(f"Model replied : {text.strip()[:200]}")
        usage = getattr(reply, "usage_metadata", None)
        if usage:
            print(f"Tokens        : {usage}")
        print("\nOK. The backend can use this model.")
        return 0
    except Exception as exc:
        print("\nFAILED")
        print(explain_llm_error(exc) if not isinstance(exc, ValueError) else str(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
