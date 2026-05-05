args <- commandArgs(trailingOnly = TRUE)

if (!requireNamespace("styler", quietly = TRUE)) {
  stop("styler is required for R formatting: install.packages('styler')")
}

styler::style_file(args)
