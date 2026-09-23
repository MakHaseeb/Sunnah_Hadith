"""
Publish the prebuilt search index, so the container never computes it.

WHY THIS EXISTS
---------------
The Dockerfile used to download the collections, assemble the corpus and
embed all 184,557 chunks *during the image build*. That is the heaviest CPU
work in the project -- 6.4 minutes on a developer laptop with eight cores,
and long enough on a free Space's two shared cores to look like the free
tier simply cannot run this app. It could, and can; it was being asked to
redo work that had already been done.

So the index is built ONCE, here, and shipped as a pinned artifact. The
container downloads it and starts. Two things follow from that:

  * The Space runs on free hardware, because the build no longer needs
    real CPU -- only a download.
  * Updating the corpus stops meaning "rebuild everything on the server"
    and starts meaning "publish a new artifact", which is the first half
    of being able to update with no downtime.

WHY THE CORPUS SHIPS TOO, NOT JUST THE VECTORS
----------------------------------------------
The embedding cache is keyed on a hash of the model name and every chunk's
text (see embed_and_retrieve.py). The old Dockerfile rebuilt the corpus from
a community CDN on every build, so if that source changed by a single
character the hash would change, the cache would miss, and the container
would silently spend an hour re-embedding -- or quietly serve a corpus
nobody had reviewed. Pinning the corpus alongside its vectors makes the
deployed text exactly the text that was tested here. (v1 reached the same
conclusion: frozen snapshots plus a SHA-256 manifest.)

WHY THE REPOSITORY IS PRIVATE
-----------------------------
The English translations are the widely-distributed Khan and Siddiqui texts,
but their redistribution licence is not settled -- an open question recorded
in CLAUDE.md, and one v1 was explicit about. An app showing a few hadith in
answer to a question is a different act from publishing the whole corpus as
a downloadable file. Until that is cleared, the artifact stays private and
the Space authenticates to fetch it.
"""
import hashlib
import json
import os
import sys
import time

REPO = os.environ.get("HADITH_INDEX_REPO", "haseebahmed0806/hadith-index")
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
CACHE = os.path.join(DATA, "cache")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def live_embedding_name():
    """
    Recompute the cache key the way HadithVectorStore does, so we publish the
    file the app will actually look for -- not whichever .npy is newest.
    Stale caches from earlier corpus versions sit in the same directory.
    """
    sys.path.insert(0, HERE)
    from chunking import chunk_hadiths
    from expansion import expansion_chunks, load_expansions
    from stub_filter import split_indexable
    from embed_and_retrieve import MODEL_NAME, _corpus_text

    corpus = json.load(open(os.path.join(DATA, "corpus.json")))
    indexable, _ = split_indexable(corpus)
    chunks = chunk_hadiths(indexable) + expansion_chunks(indexable, load_expansions())
    digest = hashlib.sha256(
        (MODEL_NAME + "\x00" + "\x00".join(_corpus_text(c) for c in chunks))
        .encode("utf-8")
    ).hexdigest()[:16]
    return f"emb_{digest}.npy", len(chunks), MODEL_NAME, len(indexable)


def build_manifest():
    name, n_chunks, model, n_hadith = live_embedding_name()
    emb = os.path.join(CACHE, name)
    corpus = os.path.join(DATA, "corpus.json")
    if not os.path.exists(emb):
        raise SystemExit(
            f"No embedding cache for the current corpus.\n"
            f"Expected {emb}\n"
            f"Build it first, then re-run this."
        )
    return {
        "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "model": model,
        "hadith": n_hadith,
        "chunks": n_chunks,
        "corpus_file": "corpus.json",
        "corpus_sha256": sha256_file(corpus),
        "corpus_bytes": os.path.getsize(corpus),
        "embedding_file": name,
        "embedding_sha256": sha256_file(emb),
        "embedding_bytes": os.path.getsize(emb),
    }, emb, corpus


def main():
    manifest, emb, corpus = build_manifest()
    print(json.dumps(manifest, indent=2))

    manifest_path = os.path.join(DATA, "index_manifest.json")
    with open(manifest_path, "w") as fh:
        json.dump(manifest, fh, indent=2)

    if "--dry-run" in sys.argv:
        print(f"\ndry run -- wrote {manifest_path}, uploaded nothing")
        return

    token = os.environ.get("HF_TOKEN")
    if not token:
        raise SystemExit("HF_TOKEN is not set. Export a WRITE token and re-run.")

    from huggingface_hub import HfApi
    api = HfApi(token=token)
    api.create_repo(REPO, repo_type="dataset", private=True, exist_ok=True)
    print(f"\nrepo ready: {REPO} (private dataset)")

    total = manifest["corpus_bytes"] + manifest["embedding_bytes"]
    print(f"uploading {total/1e6:.0f} MB ...")
    for path in (manifest_path, corpus, emb):
        api.upload_file(
            path_or_fileobj=path,
            path_in_repo=os.path.basename(path),
            repo_id=REPO,
            repo_type="dataset",
        )
        print(f"  uploaded {os.path.basename(path)}")
    print(f"\ndone: https://huggingface.co/datasets/{REPO}")


if __name__ == "__main__":
    main()
