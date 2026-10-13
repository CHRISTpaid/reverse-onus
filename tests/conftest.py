import os
import tempfile

# One work directory for the whole run, set before reverse_onus is imported (the server mounts it).
os.environ["REVERSE_ONUS_WORKDIR"] = tempfile.mkdtemp(prefix="reverse-onus-test-")
os.environ["REVERSE_ONUS_BACKEND"] = "mock"
os.environ["REVERSE_ONUS_FORMAT"] = "mp3"
