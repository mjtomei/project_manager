TEX = pdflatex
FLAGS = -interaction=nonstopmode

all: open-lab.pdf

open-lab.pdf: open-lab.tex
	$(TEX) $(FLAGS) open-lab.tex
	$(TEX) $(FLAGS) open-lab.tex

clean:
	rm -f *.aux *.log *.out *.toc *.hst *.ver

.PHONY: all clean
