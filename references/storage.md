# 文件保留

日常 CLI、design-check、analyze_case 默认 compact，求解结束后无损压缩原生文本。底层 workflow.analyze 供求解内部和验证使用，保持 full，避免在机器人传递、接触阶段或缓存写入前清理。收尾压缩在 design-check 求解预算之外。

保留 result/signal/review/report、输入 deck、每级 mesh.npz/fields.npz、固定／预紧／锁定场、屈曲数据、日志、诊断与来源哈希。只 gzip deck 旁的 DAT／FRD 和 mesh.npz 旁的 mesh.msh。storage.json 记录原始／压缩 SHA-256；解压逐字节相同，不抽样数值、不裁剪热点。Viewer 与比较使用完整 NPZ／JSON。

磁盘或校验出错时保留原文件并记录错误，不把失败改成通过。不遍历目录链接，不触碰源模型或其他任务，不定时淘汰历史。失败／超时诊断同样保留。下次运行选 --storage full 可保留原生文本，或用常规 gzip 解压工具读取现有文件。

普通迭代不必启用 --cache／--reuse-levels；显式缓存会额外复制完整证据，本版不自动淘汰。紧凑输出不能代替缓存完整性验证。数学验证脚本显式 full，以独立检查原生文件。

项目仍随保留的修订增长。确认不再需要时，关闭相关求解和 Viewer 服务，自行删除旧输出／会话；保留重要输入、CAD 源码和打印文件。Viewer 引用被删除的结果会显示证据不可用，不能伪装成仍可复查。
