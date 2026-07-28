# 通用数据集 PR 流程

这套流程把“数据发布”和“评测注册”分开。大文件只放 Hugging Face，GitHub PR
只提交不可变版本、清单和配置。必须先上传数据，再提正式注册 PR；否则云端校验
无法读取该版本，PR 会失败。

## 1. 准备数据

推荐直接使用 `native` adapter。Hugging Face Dataset 中至少包含：

```text
manifests/all.txt
manifests/train.txt
manifests/test.txt
manifests/summary.json
<case>/converted/injection.json
<case>/converted/...
```

三个 txt 每行一个 case 相对路径，不能重复或包含 `..`。train/test 必须无交集，
且并集严格等于 all。`summary.json` 格式为：

```json
{
  "manifest_sha256": "manifests/all.txt 的 64 位小写 SHA256",
  "total": 1000,
  "train": 800,
  "test": 200
}
```

`manifest_sha256` 是 `manifests/all.txt` 原始文件字节的 SHA256，可用
`sha256sum manifests/all.txt` 生成；配置和 `summary.json` 中必须完全一致。

每个 `injection.json` 的 `ground_truth.service` 必须包含至少一个非空 service。
不符合 native 目录结构的数据，先单独提“adapter + 单元测试”PR。adapter 必须作为
仓库内置的固定实现加入；数据集 JSON 不能声明 shell 命令、模块路径或任意脚本。

## 2. 上传并固定 Hugging Face commit

上传完成后读取真正的 commit SHA，不要使用 `main`、branch 或可移动 tag：

```bash
python - <<'PY'
from huggingface_hub import HfApi
print(HfApi().dataset_info("OWNER/DATASET").sha)
PY
```

私有数据集在本机设置 `HF_TOKEN`。Token 只能放 GitHub Secret 或环境变量，不能写入
PR、配置、日志或截图。数据仓库的许可证必须允许当前上传和评测方式。

## 3. 提交注册 PR

从 `config/ops-lite.json` 复制一个配置，例如 `config/my-dataset.json`，修改：

```json
{
  "schema_version": 1,
  "algorithm_registry": "algorithms.json",
  "benchmark": {
    "id": "my-dataset-fault-service-seed42",
    "title": "My Dataset",
    "primary_metric": "mrr",
    "deduplicate_services": true
  },
  "dataset": {
    "repo_id": "OWNER/DATASET",
    "repo_type": "dataset",
    "revision": "40-character-hugging-face-commit-sha",
    "manifest_sha256": "64-character-lowercase-sha256",
    "data_dir": ".",
    "manifests": {
      "all": "manifests/all.txt",
      "train": "manifests/train.txt",
      "test": "manifests/test.txt"
    },
    "expected_cases": {"all": 1000, "train": 800, "test": 200}
  }
}
```

然后登记到 `config/datasets.json`：

```json
"my-dataset": {
  "config": "my-dataset.json",
  "adapter": "native",
  "watch": true,
  "update_adapter": "native"
}
```

本地检查：

```bash
python -m pip install -e '.[dev]'
rcabench-leaderboard validate-registry
pytest -q
```

提交 PR 时选择 Dataset submission 模板并填写许可证、规模、fault/service 字段和
划分方法。新版本使用同样流程，只改为新的 commit SHA 和对应清单信息。可以额外
在 HF 上打 `v1.1.0` 等便于阅读的 tag，但配置仍必须填写其 40 位 commit SHA。

## 4. 自动化会做什么

```text
数据集 PR
  -> GitHub 云端读取固定 HF revision、三个 manifest 和少量 case
  -> 校验数量、去重、train/test 完整划分、摘要和 ground_truth.service
  -> 可信同仓库分支进入 self-hosted Runner
  -> 自动展开为“新数据集 × 所有已注册算法”
  -> 完整下载、内置 adapter、断点评测、统一指标校验
  -> 指标写回 PR、自动 squash merge
  -> main 的 leaderboard.json 和 Pages 自动更新
```

任一算法失败、case 缺失或指标不完整时，正式排行榜不会被覆盖，PR 也不会自动
合并。服务器缓存、checkpoint 和已有 `result.json` 会被复用。

## 5. 外部贡献者与学校服务器

fork PR 只做无密钥云端校验，绝不会取得 `HF_TOKEN`，也不会运行在学校服务器。
维护者审查通过后，把精确 commit 提升到本仓库分支，再触发完整评测。这样既允许
任何人提交新数据集，又不会让任意 fork 代码在 self-hosted Runner 上执行。

每日 watcher 只跟踪已经进入 `config/datasets.json` 的受信任 HF 仓库。发现新
revision 后会固定新 commit、更新清单信息并创建评测 PR；未登记的数据集不会自动
获得服务器权限。
