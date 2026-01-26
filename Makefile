
### `Makefile` (opcional en Windows)
```powershell

.PHONY: venv install run test

venv:
	python -m venv .venv

install:
	pip install -r requirements.txt

run:
	python -m slotting

test:
	pytest
