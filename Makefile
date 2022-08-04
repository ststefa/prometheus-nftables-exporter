# Buildfile for both
# - Local development
# - ALM pipeline (prefixed with "alm_")

# phony targets are executed unconditionally, see https://docs.w3cub.com/gnu_make/phony-targets#Phony-Targets

# Run this if no explicit target is specified
.DEFAULT_GOAL := help

# Name of resulting executable
EXEC_NAME := nftables-exporter

# Docker hub user, only required for my_multiarch_image
ME := ststefa

help:   ## Show this help
	@grep -h "##" $(MAKEFILE_LIST) | grep -v grep | sed 's/:.*##/:/'

test:  ## Run tests
	#pytest...

.venv:
	python3 -m venv .venv
	pip3 install -r requirements.txt

_active_venv: .venv
	source .venv/bin/activate

compile: _active_venv ## Create build artifacts in dist/ directory
	pyinstaller --onefile nftables_exporter.py

.PHONY: image
image:  ## Create docker image
	docker build --tag $(EXEC_NAME) .

.PHONY: my_multiarch_image
my_multiarch_image:   ## Create multi-arch docker image and push it to docker hub (dev workaround, only usable for $ME). Note that multi-arch builds require additional docker setup!
	docker buildx build --platform linux/amd64,linux/arm64/v8,linux/arm/v7 --tag $(ME)/$(EXEC_NAME) --push .

.PHONY: image_test
image_test:  ## Test the docker image
	docker run --rm $(EXEC_NAME)

.PHONY: clean
clean: ## Remove build directory
	rm -vfr build dist
