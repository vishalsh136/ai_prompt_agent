#!/usr/bin/env python
"""Fix deprecated use_container_width parameter in Streamlit"""
import re

# Read the file
with open("app.py", "r", encoding="utf-8") as f:
    content = f.read()

# Count matches before
before_count = content.count("use_container_width")

# Replace use_container_width=True with width='stretch'
content = re.sub(
    r'use_container_width\s*=\s*True',
    "width='stretch'",
    content
)

# Replace use_container_width=False with width='content'
content = re.sub(
    r'use_container_width\s*=\s*False',
    "width='content'",
    content
)

# Write the file back
with open("app.py", "w", encoding="utf-8") as f:
    f.write(content)

after_count = content.count("use_container_width")
print(f"✅ Replaced {before_count - after_count} occurrences of use_container_width")
print(f"Remaining: {after_count}")
