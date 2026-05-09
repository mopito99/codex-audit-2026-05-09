#!/usr/bin/env python3
"""
Reset PPO weights to foundation and force fresh training with recent data.
"""
import os
import sys
import shutil
from datetime import datetime
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

ARTIFACTS_DIR = Path("/srv/profitlab_quantum/artifacts")
PPO_BY_SYMBOL = ARTIFACTS_DIR / "ppo" / "by_symbol"
FOUNDATION = ARTIFACTS_DIR / "ppo_foundation_v1.pt"
BACKUP_DIR = ARTIFACTS_DIR / f"backup_before_reset_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

SYMBOLS = ["BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "BNB-USDT", "ADA-USDT", "DOGE-USDT", "TRX-USDT", "AVAX-USDT"]

def main():
    print("=" * 60)
    print("QUANTUM PPO RESET & RETRAIN TOOL")
    print("=" * 60)
    
    # 1. Backup current weights
    print(f"\n1. Backing up current weights to {BACKUP_DIR}")
    if PPO_BY_SYMBOL.exists():
        shutil.copytree(PPO_BY_SYMBOL, BACKUP_DIR)
        print(f"   ✓ Backup created")
    else:
        print(f"   ⚠ No existing weights to backup")
    
    # 2. Check foundation exists
    if not FOUNDATION.exists():
        print(f"\n❌ Foundation weights not found at {FOUNDATION}")
        print("   Cannot proceed without foundation weights.")
        return 1
    
    print(f"\n2. Foundation weights found: {FOUNDATION}")
    
    # 3. Reset each symbol to foundation
    print(f"\n3. Resetting {len(SYMBOLS)} symbols to foundation weights...")
    for sym in SYMBOLS:
        sym_dir = PPO_BY_SYMBOL / sym
        sym_dir.mkdir(parents=True, exist_ok=True)
        target = sym_dir / "ppo.pt"
        shutil.copy2(FOUNDATION, target)
        print(f"   ✓ {sym}: reset to foundation")
    
    print("\n" + "=" * 60)
    print("RESET COMPLETE")
    print("=" * 60)
    print("\nNext steps:")
    print("1. Restart the quantum bot: systemctl restart profitlab_quantum_bot")
    print("2. The agent will start learning from scratch with fresh foundation weights")
    print("3. Monitor progress in journalctl -fu profitlab_quantum_bot")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
