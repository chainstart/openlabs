# Inspect the isolated Bioconductor environment and run a synthetic software smoke.
# Run with Rscript --vanilla under the OpenLabs CPU resource guard.
packages <- c("GenomeInfoDbData", "GEOquery", "limma", "DESeq2", "edgeR",
              "SummarizedExperiment", "jsonlite", "renv")
ready <- vapply(packages, requireNamespace, logical(1), quietly = TRUE)
if (!all(ready)) {
  stop(paste("Missing packages:", paste(packages[!ready], collapse = ", ")))
}
set.seed(0)
counts <- matrix(rnbinom(600, mu = 50, size = 10), nrow = 100, ncol = 6)
rownames(counts) <- paste0("synthetic_gene_", seq_len(nrow(counts)))
colnames(counts) <- paste0("synthetic_sample_", seq_len(ncol(counts)))
metadata <- data.frame(condition = factor(rep(c("A", "B"), each = 3)),
                       row.names = colnames(counts))
dds <- DESeq2::DESeqDataSetFromMatrix(counts, metadata, design = ~condition)
dds <- DESeq2::estimateSizeFactors(dds)
stopifnot(all(is.finite(DESeq2::sizeFactors(dds))))
design <- model.matrix(~condition, metadata)
fit <- limma::eBayes(limma::lmFit(log2(counts + 1), design))
stopifnot(all(is.finite(fit$coefficients)))
report <- list(
  schema_version = "openlabs.biomed_r_environment.v1",
  valid = TRUE,
  r_version = as.character(getRversion()),
  packages = setNames(lapply(packages, function(name) as.character(packageVersion(name))), packages),
  synthetic_software_smoke = list(genes = 100L, samples = 6L,
                                  deseq2_size_factors = TRUE, limma_fit = TRUE),
  scientific_result = FALSE,
  gpu_workload_executed = FALSE
)
arguments <- commandArgs(trailingOnly = TRUE)
text <- jsonlite::toJSON(report, auto_unbox = TRUE, pretty = TRUE)
if (length(arguments) == 1L) {
  dir.create(dirname(arguments[[1L]]), showWarnings = FALSE, recursive = TRUE)
  temporary <- tempfile(pattern = ".r-environment-", tmpdir = dirname(arguments[[1L]]))
  writeLines(text, temporary)
  stopifnot(file.rename(temporary, arguments[[1L]]))
}
cat(text, "\n")
