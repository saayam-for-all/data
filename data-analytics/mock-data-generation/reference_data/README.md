# Reference lookup snapshot

These five non-personal lookup CSVs were copied without modification from
`saayam-for-all/data` commit `a9a14a18aaac012f425b946ae4639e0535f7efce`,
under `database/lookup_tables/`, on 2026-09-08.

Source: https://github.com/saayam-for-all/data/tree/a9a14a18aaac012f425b946ae4639e0535f7efce/database/lookup_tables

They make generation reproducible on `dev`, which does not currently contain the
shared lookup directory. To refresh, replace all five files with a consistent
reference snapshot, verify city anchor identities, regenerate the output CSVs,
and run validation and regression tests. Use `--lookup-dir` to test another
snapshot without replacing these files.
