#!/usr/bin/env bash
# No database changes or deployment secrets are needed during the build.
set -euo pipefail
cd "$(dirname "$0")/.."
python -m pip install -r requirements.runtime.lock
npm ci --include=dev
npm run build
DJANGO_SETTINGS_MODULE=config.settings.build python manage.py collectstatic --noinput
# Verify Render's native libraries can produce real invoice PDFs before release.
python -c "from weasyprint import HTML; assert HTML(string='<p>Invoice runtime check</p>').write_pdf().startswith(b'%PDF')"
