import re
from parse_bukhari import extract_pages, clean_and_split, PDF
import os

print(f"Looking for PDF at: {PDF}")
print(f"PDF exists: {os.path.exists(PDF)}\n")

raw = extract_pages(1, 15)
print("=== RAW TEXT: first 1500 chars ===")
print(repr(raw[:1500]))

marker = re.compile(r"Volume (\d+), Book (\d+), Number (\d+):")
matches = marker.findall(raw)
print(f"\nFound {len(matches)} 'Volume X, Book Y, Number Z:' markers")
print(matches[:5])

hadiths = clean_and_split(raw)
print(f"\nclean_and_split result: {len(hadiths)} hadiths")
