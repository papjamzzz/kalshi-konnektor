# ──────────────────────────────────────────────────────────────
#  ⚡ Kalshi Edge Detector — Developer Commands
#  Usage:  make setup   → first-time install
#          make run     → start the server
#          make clean   → remove cache files
#          make zip     → create distributable zip
# ──────────────────────────────────────────────────────────────

.PHONY: setup run clean zip

setup:
	@python3 -m venv venv
	@. venv/bin/activate && pip install -r requirements.txt -q
	@echo "✓ Setup complete. Run: make run"

run:
	@. venv/bin/activate && python3 app.py

clean:
	@find . -name "*.pyc" -delete
	@find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
	@echo "✓ Cleaned"

zip:
	@cd .. && zip -r kalshi-edge-$$(date +%Y%m%d).zip kalshi-edge \
		--exclude "*.git*" \
		--exclude "*/venv/*" \
		--exclude "*/data/*" \
		--exclude "*/__pycache__/*" \
		--exclude "*/.env" \
		--exclude "*.pyc"
	@echo "✓ Zipped → ../kalshi-edge-$$(date +%Y%m%d).zip"
