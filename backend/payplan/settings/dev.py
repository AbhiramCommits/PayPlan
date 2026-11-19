from .base import *  # noqa: F401,F403

DEBUG = env_bool("DEBUG", True)  # noqa: F405

ALLOWED_HOSTS = [
    h.strip()
    for h in os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1,web,api,0.0.0.0").split(",")
    if h.strip()
]

# In local development the fake gateway is the default so no keys are needed.
PAYMENT_GATEWAY = os.environ.get("PAYMENT_GATEWAY", "fake")
