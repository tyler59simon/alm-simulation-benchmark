The first run of scenario v2, the realistic rewrite: short prompts in the engineer's voice, a tracker, wiki and Slack outside the repo with business colleagues played by Haiku, natural traps (a commit-message hook and CI-only lint rules), facts that change twice, 3 working days per sprint, and 9 work probes in sprint 4.

This arm had no memory at all. It ran in parallel with A1 (started 20 seconds apart), on the same scenario files and harness. CI went red twice during the run and was red at the end.

It has the highest probe mean of seed 1, but with one run per arm a single probe flipping moves the mean by about 0.11, so that ordering is not evidence. See the [scenario v2 analysis](../analysis/v2.md).
