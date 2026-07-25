# 部署与维护

## 1. 第一次部署

### GitHub 设置

仓库需要以下 Actions 权限：

- Actions → General → Workflow permissions：`Read and write permissions`
- Pages → Build and deployment → Source：`GitHub Actions`
- Packages：允许 Actions 读取和写入 GHCR

Pages 启用后，在 `Settings → Secrets and variables → Actions → Variables`
增加 `PAGES_ENABLED=true`。当前 GitHub Free 不支持私有仓库 Pages；可以将仅含
代码和指标的仓库公开，或把 `site/` 发布到单独的公开仓库。Hugging Face 数据
仓库仍然可以保持 private。

在 `Settings → Secrets and variables → Actions` 添加：

| Secret | 用途 |
|---|---|
| `HF_TOKEN` | 读取私有 Hugging Face Dataset；使用 read token 即可 |

不要将 Hugging Face Token、SSH 密码或 GitHub Token 写入配置文件。

### 上传数据到 Hugging Face

首先确认原始数据许可证允许当前使用方式。建议第一次保持 private：

```bash
export HF_TOKEN=hf_xxx
python scripts/publish_dataset.py \
  --data-root /mnt/jfs-fixed/rcabench_dataset \
  --manifests /home/nn/fse_reproduction/manifests_fault_service_seed42 \
  --license-id other \
  --license-acknowledged
```

脚本会执行以下检查后才上传：

- all/train/test 数量分别为 1422/1126/296；
- train 与 test 没有交集；
- 每个 case 都存在 `converted` 数据；
- manifest SHA256 与配置一致；
- 上传完成后创建不可变的 `v1.0.0` tag。

只检查、不上传：

```bash
python scripts/publish_dataset.py \
  --data-root /mnt/jfs-fixed/rcabench_dataset \
  --manifests /home/nn/fse_reproduction/manifests_fault_service_seed42 \
  --license-id other --dry-run
```

### 在服务器安装 self-hosted runner

Runner 使用普通用户 `nn` 运行，该用户必须能执行 Docker：

```bash
docker info
```

在 GitHub 仓库中打开：

`Settings → Actions → Runners → New self-hosted runner → Linux → x64`

按页面命令在服务器安装，配置命令必须加入标签：

```bash
./config.sh \
  --url https://github.com/HamsterStation/rcabench-leaderboard \
  --token '<GitHub 页面生成的一次性 token>' \
  --name fse-10.26.1.187 \
  --labels rcabench \
  --work _work \
  --unattended --replace
```

然后注册服务：

```bash
sudo ./svc.sh install nn
sudo ./svc.sh start
sudo ./svc.sh status
```

GitHub 页面显示 runner 为 `Idle` 后，执行一次 `Full benchmark` workflow。

## 2. 数据更新

新数据必须使用新的不可变版本，例如 `v1.1.0`：

1. 重新生成 train/test manifests 和 `summary.json`；
2. 修改 `config/benchmark.json` 中的 revision、manifest SHA256 和数量；
3. 用上传脚本发布新版本并创建 tag；
4. 提交配置 PR；
5. 合并后触发全量评测。

数据版本改变后，ART/Eadro 必须重新训练；BARO/CausalRCA 不训练。训练
checkpoint 缓存在服务器 `$HOME/.cache/rcabench/assets/`，不用提交到 Git。

如果通过外部数据发布服务触发评测，可发送 repository dispatch：

```bash
gh api --method POST \
  repos/HamsterStation/rcabench-leaderboard/dispatches \
  -f event_type=dataset-updated
```

## 3. 算法更新

`Watch algorithm upstreams` 每天读取四个上游仓库的默认分支 HEAD。发现
更新时只创建 PR，不直接替换基准版本。合并 PR 后：

1. 构建新 commit 对应的不可变 GHCR 镜像；
2. `Build algorithm images` 成功后自动排队执行全量评测；
3. 结果验证通过后更新排行榜和 GitHub Pages。

这种方式避免上游一次错误提交直接污染正式排行榜。

## 4. 失败恢复

- 每个 case 的结果独立保存在 `$HOME/rcabench-runs/<run-id>/`；
- 同一个目录重新运行会跳过已有 `result.json`；
- `progress.json` 记录完成、失败、当前 case 和更新时间；
- ART 最多允许两个已知的空排名异常，仍计入 296 个测试样本的分母；
- 其他算法默认不允许 case 异常；
- 指标或完整性校验失败时不会更新正式排行榜。

若 GitHub workflow 被取消，可在服务器使用相同输出目录手动重跑，然后从
Actions 页面重新执行 workflow。不要删除已有 case 结果和训练 cache。

## 5. 增加新算法

新增算法需要：

1. 在 `config/benchmark.json` 增加 source、commit、image、scope 和资源限制；
2. 在 `containers/run_algorithm.py` 注册上游 Algorithm 类；
3. 如需训练，在 `prepare.py` 增加可缓存的训练适配器；
4. 增加最小单元测试；
5. 将算法名加入 `benchmark.yml` matrix。

所有算法最终必须输出统一的 service 级别排名，评估和网页部分无需单独修改。
