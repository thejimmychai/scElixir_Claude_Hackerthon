# External inputs

Large files that the pipeline reads but does not ship go here, in a folder per organ:

    data/external/<organ>/<layer>_subatlas.h5ad      integrated sub-atlas (Stage B, C, D)
    data/external/<organ>/<layer>_multiome.h5mu      matched multiome (SCENIC+ route)

`GET /compute/status` and every not-computed response list which of these are missing.
Nothing in this folder is committed (see .gitignore).
