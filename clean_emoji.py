"""Remove all emoji characters from project files."""
import os, re, sys

# Emoji chars and variation selectors to remove
EMOJI_PATTERN = re.compile(
    '[\U0001F300-\U0001F9FF'  # Misc symbols and pictographs
    '\U0001FA00-\U0001FA6F'   # Chess symbols
    '\U0001FA70-\U0001FAFF'   # Symbols and pictographs extended-A
    '\u2600-\u27BF'           # Misc symbols, dingbats
    '\uFE00-\uFE0F'           # Variation selectors
    '\u200D'                  # Zero width joiner
    '\u23F0-\u23FF'           # Misc technical
    '\u2934-\u2935'
    '\u2B05-\u2B07'
    '\u2B1B-\u2B1C'
    '\u3030\u303D'
    '\u3297\u3299'
    ']',
    re.UNICODE
)

# Specific replacements
REPLACE = {
    "☁": "*",
    "📝": ">",
    "🤖": "=>",
    "❌": "X",
    "✅": "OK",
    "⏳": "...",
    "⏭": "..",
    "🛑": "Stop",
    "🗑": "Delete",
    "🔄": "Refresh",
    "💡": "Tip",
    "⚠": "Warning",
    "🖥": "[EC2]",
    "🗄": "[RDS]",
    "⚡": ">",
}

def clean(text):
    for old, new in REPLACE.items():
        text = text.replace(old, new)
    text = EMOJI_PATTERN.sub("", text)
    return text

files = ["cloudops.py", "app/tui.py", "app/exec.py", "app/api.py", "scripts/mcp_server.py"]
root = sys.argv[1] if len(sys.argv) > 1 else "/home/conta/fine_tuning_model"

for f in files:
    path = os.path.join(root, f)
    if not os.path.exists(path):
        print(f"{f}: not found")
        continue
    text = open(path, encoding="utf-8").read()
    cleaned = clean(text)
    if cleaned != text:
        open(path, "w", encoding="utf-8").write(cleaned)
        print(f"{f}: CLEANED")
    else:
        print(f"{f}: clean already")
