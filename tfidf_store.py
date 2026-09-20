"""
The original TF-IDF retriever, pulled out into its own file now that
embed_and_retrieve.py holds the neural version -- both are needed
together for hybrid retrieval.
"""
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


def _corpus_text(chunk):
    narrator = chunk.get("narrator")
    return f"{narrator}: {chunk['chunk_text']}" if narrator else chunk["chunk_text"]


class TfidfStore:
    def __init__(self, chunks):
        self.chunks = chunks
        # narrator is None for ~2% of records; f-string would otherwise
        # embed the literal text "None: ..." into the searchable corpus.
        corpus = [_corpus_text(c) for c in chunks]
        self.vectorizer = TfidfVectorizer(stop_words="english")
        self.matrix = self.vectorizer.fit_transform(corpus)

    def retrieve(self, query, k=None):
        k = k or len(self.chunks)
        query_vec = self.vectorizer.transform([query])
        scores = cosine_similarity(query_vec, self.matrix)[0]
        ranked = sorted(zip(self.chunks, scores), key=lambda p: p[1], reverse=True)
        return ranked[:k]
