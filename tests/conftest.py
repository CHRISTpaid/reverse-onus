import os
import tempfile

# One work directory for the whole run, set before suno_clone is imported (the server mounts it).
os.environ["SUNO_CLONE_WORKDIR"] = tempfile.mkdtemp(prefix="suno-clone-test-")
os.environ["SUNO_CLONE_BACKEND"] = "mock"
os.environ["SUNO_CLONE_FORMAT"] = "mp3"
