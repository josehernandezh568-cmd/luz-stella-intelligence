name: RADAR X V4.2 - PREPARE

on:
  workflow_dispatch: {}

permissions:
  contents: read

concurrency:
  group: radar-x-v4.2-prepare
  cancel-in-progress: false

jobs:
  prepare:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - name: Checkout del repositorio (solo lectura)
        uses: actions/checkout@v4
        with:
          persist-credentials: false

      - name: Configurar Python 3.11
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Preparar directorio de salida limpio
        shell: bash
        run: |
          set -euo pipefail
          rm -rf work/prepare
          mkdir -p work/prepare

      - name: Ejecutar PREPARE
        shell: bash
        run: |
          set -euo pipefail
          python3 scripts/x_prepare_analysis.py \
            --inbox data/x_inbox.json \
            --historico data/x_historico.json \
            --radar data/x_radar.json \
            --outdir work/prepare

      - name: Validar que PREPARE produjo los archivos esperados
        shell: bash
        run: |
          set -euo pipefail
          if [ ! -f "work/prepare/radar_x_input_bundle.json" ]; then
            echo "ERROR: falta work/prepare/radar_x_input_bundle.json" >&2
            exit 1
          fi
          if [ ! -f "work/prepare/prepare_report.json" ]; then
            echo "ERROR: falta work/prepare/prepare_report.json" >&2
            exit 1
          fi
          echo "OK: ambos archivos esperados existen."

      - name: Subir artifact radar-x-v4.2-prepare
        uses: actions/upload-artifact@v4
        with:
          name: radar-x-v4.2-prepare
          path: work/prepare/
          if-no-files-found: error
          retention-days: 7
