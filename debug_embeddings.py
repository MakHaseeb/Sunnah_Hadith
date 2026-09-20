import json
import numpy as np
from embed_and_retrieve import HadithVectorStore

with open("hadiths_p1_15.json") as f:
    hadiths = json.load(f)

store = HadithVectorStore(hadiths)

print("Embeddings shape:", store.embeddings.shape)
print("Any NaN in embeddings:", bool(np.isnan(store.embeddings).any()))
print("Any Inf in embeddings:", bool(np.isinf(store.embeddings).any()))

print("\nPer-hadith embedding norm (should all be ~1.0 after normalization):")
norms = np.linalg.norm(store.embeddings, axis=1)
for h, n in zip(hadiths, norms):
    flag = "  <-- NOT NORMALIZED / BAD" if abs(n - 1.0) > 0.01 else ""
    print(f"  Number {h['number']:3d}  norm={n:.4f}{flag}")

print("\nApprox token counts (model max_seq_length = 256):")
tokenizer = store.model.tokenizer
max_len = store.model.max_seq_length
print(f"  Model max_seq_length: {max_len}")
for h in hadiths:
    n_tokens = len(tokenizer(h["text"])["input_ids"])
    flag = "  <-- LIKELY TRUNCATED" if n_tokens > max_len else ""
    print(f"  Number {h['number']:3d}  {n_tokens} tokens{flag}")

query = "actions are judged by intentions"
print(f"\nFULL ranking for: {query!r}")
results = store.retrieve(query, k=len(hadiths))
for h, score in results:
    print(f"  score={score:.4f}  Number {h['number']:3d}")
