.PHONY: test build package publish

test:
	python -m pytest

build: test
	rm -rf dist
	python -m build

package: build
	@echo "Package built successfully"

publish: package
	python -m twine upload dist/*