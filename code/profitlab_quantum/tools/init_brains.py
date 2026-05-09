import os
import shutil
from pathlib import Path
import torch

# Configuration
TOKENS = ["BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "BNB-USDT"]
ARTIFACTS_DIR = Path("/srv/profitlab_quantum/artifacts")
PPO_DIR = ARTIFACTS_DIR / "ppo"
BY_SYMBOL_DIR = PPO_DIR / "by_symbol"
BASE_MODEL_PATH = PPO_DIR / "ppo.pt"

def init_brains():
    print("🧠 Initializing Quantum Brains...")
    
    # Ensure base directories exist
    BY_SYMBOL_DIR.mkdir(parents=True, exist_ok=True)
    
    # Check for base model
    if not BASE_MODEL_PATH.exists():
        print(f"⚠️ Base model not found at {BASE_MODEL_PATH}. Checking for BTC model...")
        btc_model = BY_SYMBOL_DIR / "BTC-USDT" / "ppo.pt"
        if btc_model.exists():
            print(f"✅ Found BTC model. Using it as new base.")
            shutil.copy(btc_model, BASE_MODEL_PATH)
        else:
            print("❌ No models found. Cannot initialize. Run the bot to generate a base model first or check paths.")
            return

    print(f"📂 Base model source: {BASE_MODEL_PATH}")

    for token in TOKENS:
        token_dir = BY_SYMBOL_DIR / token
        token_model_path = token_dir / "ppo.pt"
        
        token_dir.mkdir(parents=True, exist_ok=True)
        
        if token_model_path.exists():
            print(f"✅ {token}: Brain already exists.")
        else:
            print(f"🌱 {token}: Creating new brain from base...")
            shutil.copy(BASE_MODEL_PATH, token_model_path)
            print(f"   ✨ Created {token_model_path}")

    print("\n🎉 All brains initialized and persistent.")

if __name__ == "__main__":
    init_brains()
