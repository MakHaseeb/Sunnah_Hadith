"""
Letter-pattern matching, to survive misspellings and transliteration.

WHY
---
Arabic terms reach an English search box spelled many different ways.
A real user typed "Tahajjut" and got nothing: that spelling appears in
ZERO hadith, while "Tahajjud" appears in 30. The correct answer was never
retrieved, so the relevance check never even saw it. Retyped correctly a
moment later, the app answered perfectly.

Word matching cannot help here -- "Tahajjut" and "Tahajjud" are simply
different words. Meaning-matching cannot either, because the embedding
model has no idea what either token is.

Matching on overlapping 3-5 LETTER pieces does: "Tahajjut" and
"Tahajjud" share "tahajju", so one finds the other.

USED AS A THIRD OPINION, NOT A REPLACEMENT
------------------------------------------
On its own this signal is noisy -- "zakah how much" matched "See how much
I am in debt to others", because "how much" is a long shared letter run
and "zakah" is short. So it joins the existing word- and meaning-matching
as a third vote, where it can rescue a misspelled rare term without
being able to dominate an ordinary query on its own.
"""
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import linear_kernel

from tfidf_store import _corpus_text


class CharStore:
    def __init__(self, chunks):
        self.chunks = chunks
        corpus = [_corpus_text(c) for c in chunks]
        # char_wb keeps n-grams inside word boundaries, so it compares
        # words to words rather than sliding across the whole sentence.
        self.vectorizer = TfidfVectorizer(
            analyzer="char_wb", ngram_range=(3, 5),
            min_df=2, max_features=300000, sublinear_tf=True,
        )
        self.matrix = self.vectorizer.fit_transform(corpus)

    def retrieve(self, query, k=None):
        k = k or len(self.chunks)
        scores = linear_kernel(self.vectorizer.transform([query]), self.matrix)[0]
        ranked = sorted(zip(self.chunks, scores), key=lambda p: p[1], reverse=True)
        return ranked[:k]
