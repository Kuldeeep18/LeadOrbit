#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT_DIR/backend/.env"

if [ -f "$ENV_FILE" ]; then
  echo "$ENV_FILE already exists; leaving it unchanged."
  exit 0
fi

python - <<'PY' "$ENV_FILE"
import os
import sys
from pathlib import Path
from django.core.management.utils import get_random_secret_key

env_path = Path(sys.argv[1])
env_path.write_text(
    f"DEBUG=True\nSECRET_KEY={get_random_secret_key()}\nBACKEND_BASE_URL=http://127.0.0.1:8000\nFRONTEND_BASE_URL=http://127.0.0.1:8080\n\nCELERY_TASK_ALWAYS_EAGER=true\nCELERY_BROKER_URL=redis://localhost:6379/0\nENABLE_AUTO_REPLY_DETECTION=false\nLAUNCH_IMMEDIATE_PASSES=1\n\nOPENROUTER_API_KEY=\nOPENROUTER_MODEL=mistralai/mistral-nemo\nOPENROUTER_APP_URL=http://127.0.0.1:8080\nOPENROUTER_APP_NAME=LeadOrbit Campaign Builder\n\nGEMINI_API_KEY=\n\nGOOGLE_CLIENT_ID=\nGOOGLE_CLIENT_SECRET=\nGOOGLE_REDIRECT_URI=http://127.0.0.1:8000/api/v1/auth/google/callback\n\nTWILIO_ACCOUNT_SID=\nTWILIO_AUTH_TOKEN=\nTWILIO_PHONE_NUMBER=\n",
    encoding='utf-8',
)
print(f"Created {env_path}")
PY
