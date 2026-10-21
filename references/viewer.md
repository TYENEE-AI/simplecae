# 本地 Viewer

固定布局：中央模型、右侧证据与输入、底部版本记录。参考工程工具的模型视窗与属性栏，未增加第二套聊天系统。不联网加载字体、脚本或模型，无自动上传，无浏览器执行 CAD/求解命令。

## 首次打开示例

完成 bootstrap 后双击根目录 `打开Viewer.cmd`（部分发行目录名为 `Open_Viewer.cmd`）。已有 `outputs/first-001/pass/result.json` 时复用，否则直接创建空会话，等待 Agent 添加实际分析结果，不会自动启动求解。默认会话目录若残留未完成文件，会另建新会话并保留旧文件。关闭命令行窗口停止本机服务。也可运行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start_viewer.ps1
```

可选运行 quickstart 后导入真实参考结果；空会话没有分析结论。示例结果不是实物产品认证。

## 连接 Agent 的实际迭代

```powershell
# 1. 建立空会话；服务仅监听 127.0.0.1。保持此终端运行。
.\.venv\Scripts\python.exe scripts/simplecae_cli.py view --out outputs/my-review --serve --open
# 2. Agent 在另一个终端运行真实分析；输出目录仍须全新。
.\.venv\Scripts\python.exe scripts/simplecae_cli.py analyze case.json --out outputs/design-v1 --viewer-session outputs/my-review --label V1 --change-note '初版，检查端部刚度'
# 3. Agent 修改 CAD，再分析 V2；保留原记录。
# 4. 停止服务后，随时重新打开已有会话。
.\.venv\Scripts\python.exe scripts/simplecae_cli.py view --session outputs/my-review --serve --open
```

导入已有结果：`view V1/result.json V2/result.json --out outputs/review-existing --serve`。向已有会话增加结果：`view V3/result.json --session outputs/review-existing`。重复导入会保留独立记录，建议仅添加新结果。

## 能看与能操作什么

- 拖动旋转，Shift 拖动平移，滚轮缩放，适配视图。应力、强度利用率、位移模长、约束与载荷面切换；显示网格、明确的变形倍率和原形。
- 点击版本回看；同任务、完整有效证据才提供数值变化、共享色标与局部原形叠加。改变载荷、材料、约束或判据即停止比较。叠加使用记录中的分析坐标，不做猜测式配准。
- 点击显示三角形，定位面 ID、相邻体单元、三角形中心坐标；可保存区域或整版批注。中心是显示区域定位，不是新建材料测点或载荷面。
- `analyze --viewer-session` 保存真实阶段，页面每 3 秒查看新记录；没有虚构的完成百分比。骤停的记录保留“尚未完成”，不能证明进程仍在运行。
- `design-check --plan PLAN --check-id ID` 增加“本次使用体验”：实际使用方式、希望达到的表现、本轮对象、使用影响、本项范围内的结论和下一步。缺少指定任务判据时显示证据不足；其他必检项仍列出。仅在相同使用计划与选中检查下比较，不把一次本体结果当成使用目标全部完成。
- 输入条件只读。批注写到 `SESSION/feedback/*.json`，绑定结果哈希与区域，供 Agent 读取并与用户澄清。不会直接启动求解，也不代表 Agent 已执行修改。

## 边界与证据

使用现有 `design_signal` / `compare_results` 判据，不修改任何物理或数值门槛。全局任务判定与局部场分开；机器人显示组件局部坐标下的有限元场，末端总位移另读任务测点；不把局部连杆场画成整机耦合变形。

应力颜色是相邻体单元积分点的峰值映射，位移颜色是显示三角形节点模长最大值；不裁剪热点。最大读数来自完整求解摘要。变形倍率仅改变显示。当前仅显示最终网格的服务阶段；接触/预紧各阶段、屈曲模态与详细接触场请查原报告，不能从此图判断滑移、锁定或稳定性。

注册时绑定 `result.json`、最终 `mesh.npz` 与 `fields.npz` 的 SHA-256；重新载入时检测改变即撤下模型及有利判定。场文件必须在该结果目录内。原 CAD 等输入的求解时绑定仍由原结果负责；Viewer 的绑定只证明记录载入一致，不证明其物理真实性。

`index.html`、`workbench.js`、`workbench.css` 可一起离线打开，离线仅反映导出时快照，不能检查原文件后续变化。离线批注下载为 JSON；实时保存与阶段同步需要本机服务。会话里含本机路径和模型数据，分享前自行检查。每个证据文件上限 128 MiB，显示预算 30 万节点 / 40 万三角形，超限明确提示，不自动降采样或改变分析。

Windows 启动器使用所在技能目录的 `.venv`。这是本地开发版，全局安装版本以该环境的安装元数据为准；先前的公开预览 ZIP 保持独立。

Task workspaces add a small mixed-method completion section to this same Viewer. It rechecks task sources and evidence hashes; external recorded outcomes stay labeled. CAD revisions can share a Viewer using `task start --viewer-session`, while keeping fresh task workspaces and unchanged comparison gates.
