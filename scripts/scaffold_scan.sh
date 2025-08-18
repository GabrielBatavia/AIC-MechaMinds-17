#!/usr/bin/env bash
set -euo pipefail
mkdir -p app/{application,domain,infra/{pipelines,vision,ocr,regex,streaming},presentation/routes} config models/yolo tests/{unit,integration}
for f in app/application/scan_use_case.py app/domain/{scan_entities.py,validators.py} app/infra/pipelines/scan_pipeline.py app/infra/vision/yolo_detector.py app/infra/ocr/paddle_adapter.py app/infra/regex/bpom_validator.py app/presentation/routes/scan.py; do
  test -f "$f" || printf "# TODO: see scaffold doc for content\n" > "$f"; done
for f in app/presentation/routers.py app/presentation/schemas.py; do test -f "$f" || touch "$f"; done
printf "allow_prefix: []\npatterns: []\nblacklist: []\n" > config/regex.yaml