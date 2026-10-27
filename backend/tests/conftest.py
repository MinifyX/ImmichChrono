import os
import tempfile

# Settings are read at import time – point them at a throwaway directory first.
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="chrono-test-")
os.environ["IMMICH_URL"] = "http://immich.test"
os.environ["DEFAULT_TZ"] = "Europe/Berlin"
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ.pop("OLLAMA_URL", None)
