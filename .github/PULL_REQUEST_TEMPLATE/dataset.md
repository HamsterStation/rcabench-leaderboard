## Dataset submission

### Registration

- Dataset key (`config/datasets.json`):
- Hugging Face repository (`owner/name`):
- Immutable Hugging Face commit SHA (40 characters):
- Adapter (`native` or an existing built-in adapter):
- Public dataset, or maintainer-confirmed private access:

### Data contract

- All/train/test case counts:
- Fault-type field and service ground-truth field:
- Split method (include fault × service balancing details):
- License and redistribution terms:

### Checklist

- [ ] The complete dataset is already uploaded to Hugging Face.
- [ ] The config pins a commit SHA, not `main`, a branch, or a movable tag.
- [ ] `train.txt` and `test.txt` are disjoint and exactly partition `all.txt`.
- [ ] Every sampled case has valid `ground_truth.service` in `injection.json`.
- [ ] No token, password, raw private data, checkpoint, or generated result is committed.
- [ ] I understand fork PRs receive cloud validation only; a maintainer must promote the
      reviewed commit to a same-repository branch before the school runner can execute it.

<!--
If the source is not already in native RCABench layout, submit the built-in adapter and its
tests as a separate PR first. Registry JSON may never contain shell commands or dynamic code paths.
-->
