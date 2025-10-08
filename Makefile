CMACH ?= ../mach-c/bin/cmach
CC    ?= cc

STD_SRC_DIR ?= ../mach-std/src
MODULE_FLAGS := -I $(STD_SRC_DIR) -M std=$(STD_SRC_DIR)

OUT_DIR := out
BIN_DIR := $(OUT_DIR)/bin
OBJ_DIR := $(OUT_DIR)/obj

SRC := src/main.mach
OBJ := $(OBJ_DIR)/main.o
EXE := $(BIN_DIR)/mach-lsp

.PHONY: all run clean print

all: $(EXE)

$(EXE): $(OBJ) | $(BIN_DIR)
	@echo exe = $@
	@OBJS="$$(find $(OBJ_DIR) -type f -name '*.o' -print 2>/dev/null)"; $(CC) -pie -o $@ $$OBJS

$(OBJ): $(SRC) | $(OBJ_DIR)
	@$(CMACH) build $< $(MODULE_FLAGS) --emit-obj --no-link -o $@

$(BIN_DIR):
	@mkdir -p $(BIN_DIR)

$(OBJ_DIR):
	@mkdir -p $(OBJ_DIR)

run: $(EXE)
	@$(EXE)

clean:
	rm -rf $(OUT_DIR)

print:
	@echo cmach = $(CMACH)
	@echo exe   = $(EXE)
