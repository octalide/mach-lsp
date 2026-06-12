.PHONY: build test clean

# build: compile the language server.
build:
	mach build

# test: build, then drive the server through the stdio test suite.
test: build
	python3 test/run.py

# clean: remove build output.
clean:
	rm -rf out
