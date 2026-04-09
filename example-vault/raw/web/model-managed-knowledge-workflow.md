# Model-Managed Knowledge Workflow

One practical way to use language models for knowledge work is to keep a machine-maintained zone separate from a human-authored zone. The distinction between [[Machine-Maintained Zone]] and [[Human Notes]] is central.

The machine-maintained zone is good at:

- cleaning up raw notes
- extracting structure
- generating indexes
- proposing cross-links
- answering questions over already compiled material

The human-authored zone is still where judgment, synthesis, and final writing should happen.

This separation reduces anxiety about letting automation touch the same files that contain your real thinking.

A useful implementation detail is to compile from `raw/` into `wiki/`, then query the `wiki/` folder with local retrieval instead of sending the whole vault directly to a model every time. This also turns [[Local Retrieval]] and [[Incremental Compilation]] into reusable concepts.
