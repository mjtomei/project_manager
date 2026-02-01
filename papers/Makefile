TEX = pdflatex
FLAGS = -interaction=nonstopmode

all: open-lab.pdf

open-lab.pdf: open-lab.tex
	$(TEX) $(FLAGS) open-lab.tex
	$(TEX) $(FLAGS) open-lab.tex

REVIEW_ROUND ?= 3
REVIEW_OUT = reviews/review-round-$(REVIEW_ROUND).md

review: open-lab.pdf
	@echo "Generating review round $(REVIEW_ROUND)..."
	@cat review-prompt.md open-lab.tex | claude -p "You are given a review prompt followed by a LaTeX whitepaper. Produce the review. Output markdown only." > $(REVIEW_OUT)
	@echo "Review written to $(REVIEW_OUT)"

clean:
	rm -f *.aux *.log *.out *.toc *.hst *.ver

.PHONY: all clean review
