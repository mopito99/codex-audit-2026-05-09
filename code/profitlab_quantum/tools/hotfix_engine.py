import re

file_path = '/srv/profitlab_quantum/app/engine.py'
with open(file_path, 'r') as f:
    text = f.read()

# Fix RSI
text = re.sub(r'"rsi": float\(row\.get\("rsi_14".*$', '"rsi": float(row.get("rsi", 50)),', text, flags=re.MULTILINE)
text = re.sub(r'"rsi_oversold": float\(row\.get\("rsi_14".*$', '"rsi_oversold": float(row.get("rsi", 50)),', text, flags=re.MULTILINE)
text = re.sub(r'"rsi_deep_os": float\(row\.get\("rsi_14".*$', '"rsi_deep_os": float(row.get("rsi", 50)),', text, flags=re.MULTILINE)

# Fix ADX
text = re.sub(r'"adx": float\(row\.get\("adx_normalized", 0\) or 0\) \* 50,.*$', '"adx": float(row.get("adx", 0) or 0),', text, flags=re.MULTILINE)
text = re.sub(r'"adx_trending": float\(row\.get\("adx_normalized", 0\) or 0\) \* 50,.*$', '"adx_trending": float(row.get("adx", 0) or 0),', text, flags=re.MULTILINE)

with open(file_path, 'w') as f:
    f.write(text)

print('Engine mapping fixed!')
