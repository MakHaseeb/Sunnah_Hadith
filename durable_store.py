"""
Append-only storage that survives a container restart.

THE PROBLEM THIS FIXES
----------------------
Feedback and visitor counts were written to files inside the container.
Hugging Face wipes container disk on every restart, so every report anyone
sent was thrown away -- silently, with the app still appearing to work. For
an app whose entire trial exists to collect "this answer looks wrong", that
is the worst possible thing to lose quietly.

HOW IT WORKS
------------
The local file stays exactly as it was: written synchronously, read
synchronously, fast. Nothing in a web request waits for the network. A
background thread mirrors that file to a private Hugging Face dataset repo,
and on startup the file is restored from there.

So the local file is the working copy and the dataset is the durable copy.
On a plain server with a real disk -- the likely destination later -- leave
HADITH_DATA_REPO unset and this is just a local file again, no HF involved.

WHY THE WHOLE FILE, NOT ONE RECORD AT A TIME
--------------------------------------------
Uploading each record as its own file avoids read-modify-write races but
needs a listing plus N downloads to reconstruct history. These files are
small -- feedback is a few hundred bytes per report -- so re-uploading the
whole file is cheaper than the bookkeeping, and history comes back in a
single download. Writes are debounced so a burst of reports produces one
upload rather than ten.

WHY FAILURES ARE LOUD
---------------------
If the mirror cannot write, the local copy still has everything, but the
durability promise is broken. That state is reported through status() and
surfaced in /api/health, because this project's worst bugs have all been
the ones that kept working while being wrong.
"""
import json
import os
import threading
import time


class DurableStore:
    def __init__(self, local_path, repo=None, token=None, filename=None,
                 interval=5.0, name=""):
        self.local_path = local_path
        self.repo = repo or None
        self.token = token or None
        self.filename = filename or os.path.basename(local_path)
        self.interval = interval
        self.name = name or self.filename
        self._lock = threading.Lock()
        self._dirty = False
        self._last_ok = None
        self._last_error = None
        self._api = None
        self._started = False

        if self.repo and self.token:
            try:
                from huggingface_hub import HfApi
                self._api = HfApi(token=self.token)
            except Exception as e:                      # library missing
                self._last_error = f"huggingface_hub unavailable: {e}"

    # ---- lifecycle -------------------------------------------------------

    def restore(self):
        """
        Pull the durable copy down at startup. Only ever used to fill an
        EMPTY local file: if the container already has data, overwriting it
        with a remote copy could discard records written since the last
        mirror.
        """
        if not self._api:
            return 0
        if os.path.exists(self.local_path) and os.path.getsize(self.local_path) > 0:
            return 0
        try:
            from huggingface_hub import hf_hub_download
            path = hf_hub_download(repo_id=self.repo, repo_type="dataset",
                                   filename=self.filename, token=self.token)
            os.makedirs(os.path.dirname(self.local_path), exist_ok=True)
            with open(path) as src, open(self.local_path, "w") as dst:
                data = src.read()
                dst.write(data)
            n = sum(1 for line in data.splitlines() if line.strip())
            self._last_ok = time.time()
            return n
        except Exception as e:
            # A repo with nothing in it yet is the normal first-run case,
            # not a failure worth alarming about.
            if "404" not in str(e) and "EntryNotFound" not in type(e).__name__:
                self._last_error = f"restore failed: {str(e)[:160]}"
            return 0

    def start(self):
        if self._api and not self._started:
            self._started = True
            t = threading.Thread(target=self._worker, daemon=True,
                                 name=f"mirror-{self.name}")
            t.start()

    # ---- writing ---------------------------------------------------------

    def append(self, record):
        line = json.dumps(record, ensure_ascii=False)
        with self._lock:
            os.makedirs(os.path.dirname(self.local_path), exist_ok=True)
            with open(self.local_path, "a") as f:
                f.write(line + "\n")
                f.flush()
            self._dirty = True
        return True

    def read_all(self):
        if not os.path.exists(self.local_path):
            return []
        rows = []
        with open(self.local_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return rows

    # ---- mirroring -------------------------------------------------------

    def _worker(self):
        while True:
            time.sleep(self.interval)
            try:
                self.flush()
            except Exception:
                pass          # _upload already recorded why

    def flush(self):
        with self._lock:
            if not self._dirty or not self._api:
                return False
            self._dirty = False
        self._upload()
        return True

    def _upload(self):
        try:
            self._api.upload_file(
                path_or_fileobj=self.local_path,
                path_in_repo=self.filename,
                repo_id=self.repo,
                repo_type="dataset",
            )
            self._last_ok = time.time()
            self._last_error = None
        except Exception as e:
            self._last_error = f"{type(e).__name__}: {str(e)[:200]}"
            with self._lock:
                self._dirty = True        # try again next tick

    # ---- reporting -------------------------------------------------------

    def status(self):
        return {
            "durable": bool(self._api),
            "repo": self.repo,
            "rows": len(self.read_all()),
            "pending": self._dirty,
            "last_saved": (time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                         time.gmtime(self._last_ok))
                           if self._last_ok else None),
            "error": self._last_error,
        }


def ensure_repo(repo, token):
    """Create the private dataset if it does not exist. Safe to call twice."""
    if not (repo and token):
        return False
    try:
        from huggingface_hub import HfApi
        HfApi(token=token).create_repo(repo, repo_type="dataset",
                                       private=True, exist_ok=True)
        return True
    except Exception:
        return False
