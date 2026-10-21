# 文件保留

日常 CLI、design-check、analyze_case 默认 compact，求解结束后无损压缩原生文本。底层 workflow.analyze 供求解内部和验证使用，保持 full，避免在机器人传递、接触阶段或缓存写入前清理。收尾压缩在 design-check 求解预算之外。

保留 result/signal/review/report、输入 deck、每级 mesh.npz/fields.npz、固定／预紧／锁定场、屈曲数据、日志、诊断与来源哈希。只 gzip deck 旁的 DAT／FRD 和 mesh.npz 旁的 mesh.msh。storage.json 记录原始／压缩 SHA-256；解压逐字节相同，不抽样数值、不裁剪热点。Viewer 与比较使用完整 NPZ／JSON。

磁盘或校验出错时保留原文件并记录错误，不把失败改成通过。不遍历目录链接，不触碰源模型或其他任务，不定时淘汰历史。失败／超时诊断同样保留。下次运行选 --storage full 可保留原生文本，或用常规 gzip 解压工具读取现有文件。

普通迭代不必启用 --cache／--reuse-levels；显式缓存会额外复制完整证据，本版不自动淘汰。紧凑输出不能代替缓存完整性验证。数学验证脚本显式 full，以独立检查原生文件。

项目仍随保留的修订增长。对独立的 `--cache` 或 `--reuse-levels` 缓存目录，可以显式预览、归档和恢复：

```powershell
python scripts/simplecae_cli.py cache plan CACHE --references TASK_WORKSPACE VIEWER_SESSION --out cache-plan.json
python scripts/simplecae_cli.py cache archive cache-plan.json --out cache.zip
python scripts/simplecae_cli.py cache restore cache.zip --out FRESH_CACHE
```

预览列出文件、字节数、哈希，以及显式提供的任务／Viewer JSON 对缓存的引用；扫描范围之外的引用仍未知。归档前后检查源内容不变，并核对压缩包每个文件；恢复先验证全部条目、路径与哈希，再写入全新目录并复核。现有输出、模型和任务账本不能冒充缓存目录。缓存恢复不恢复通过结论，后续调用仍执行普通缓存校验。

这些命令均不删除原件、不自动清理、不同步云端。用户要求保留缓存时保留全部；之后确需释放空间，先确认所有读写进程停止、所有引用根均检查且归档已验证，再取得相应清理授权。模型源码、测试结果、审计报告和 `execution-budget.json` 不是可丢弃缓存。Viewer 引用被删除的结果必须显示证据不可用。
