"""Check for emoji characters in project files."""
import os, sys

def find_emojis(text):
    emojis = []
    for ch in text:
        if ord(ch) > 0x3000 and ord(ch) not in range(0x4E00, 0x9FFF) and ord(ch) not in range(0x3040, 0x3100):
            emojis.append(ch)
    return set(emojis)

root = sys.argv[1] if len(sys.argv) > 1 else "."
files = ["cloudops.py", "app/tui.py", "app/exec.py"]

for f in files:
    path = os.path.join(root, f)
    if not os.path.exists(path):
        continue
    text = open(path).read()
    emojis = find_emojis(text)
    if emojis:
        print(f"{f}: {emojis}")
    else:
        print(f"{f}: CLEAN")
