#!/usr/bin/env python
"""Remove deprecated use_container_width parameter from Streamlit - CORRECTED VERSION"""
import re

# Read the file
with open("app.py", "r", encoding="utf-8") as f:
    content = f.read()

# Count before
before = content.count("use_container_width")
print(f"Before: {before} occurrences of 'use_container_width'")

# Remove use_container_width parameter completely
# Pattern handles: ,use_container_width=True, or use_container_width=False, etc
content = re.sub(r',?\s*use_container_width\s*=\s*(True|False)\s*,?\s*', ', ', content)

# Clean up any double commas
content = re.sub(r',\s*,', ',', content)

# Remove trailing commas before closing parentheses
content = re.sub(r',\s*\)', ')', content)

# Count after
after = content.count("use_container_width")
print(f"After: {after} occurrences of 'use_container_width'")
print(f"✅ Removed {before - after} deprecated parameters")

# Write back
with open("app.py", "w", encoding="utf-8") as f:
    f.write(content)
