import os
import json

ACTIVE_TOKENS_FILE = "/srv/profitlab_quantum/active_tokens.json"

def load_active_tokens():
    defaults = ["BTC-USDT"] # Default to BTC only for safety
    if os.path.exists(ACTIVE_TOKENS_FILE):
        try:
            with open(ACTIVE_TOKENS_FILE, "r") as f:
                data = json.load(f)
                tokens = data.get("active_tokens", defaults)
                # Handle both list of strings and list of objects
                if tokens and isinstance(tokens[0], dict):
                    return [t["symbol"] for t in tokens]
                return tokens
        except Exception as e:
            print(f"Error loading active_tokens.json: {e}")
            return defaults
    else:
        print("File not found")
    return defaults

tokens = load_active_tokens()
print("Tokens:", tokens)
print("Count:", len(tokens))
