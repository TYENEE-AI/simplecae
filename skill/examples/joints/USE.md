# 预紧锁定与平面摩擦：数学参考和失败场景

在 SimpleCAE 文件夹运行，输出目录必须是新目录：

```powershell
.\.venv\Scripts\python.exe scripts/simplecae_cli.py preview examples/joints/bolt-friction-combined.case.json --out outputs/joint-preview-001
.\.venv\Scripts\python.exe scripts/simplecae_cli.py analyze examples/joints/bolt-friction-combined.case.json --out outputs/joint-001
# 独立解析参考和所有不利场景（包含预期失败，通常需要数分钟）
.\.venv\Scripts\python.exe scripts/simplecae_cli.py validate --suite bolt-friction --out outputs/joint-validation-001
```

这些是自建的理想试验夹具，两块 50×10×10 mm 数学参考实体，E=200000 MPa、泊松比为零。参数和确认项是算例定义，不是实物材料、螺栓或产品认证。完整成立条件见[接触与预紧说明](../../references/contact-and-transfer.md)。

| 输入 | 预期模型结论／检查重点 |
|---|---|
| `bolt-locked.case.json` | 通过；1000 N 预紧后锁定调整量，外载 200 N 时螺栓约 1067.55 N，压紧力约 867.55 N |
| `bolt-preload-only.case.json` | 通过；无使用载荷，锁定后的轴力保持 1000 N |
| `bolt-different-stiffness.case.json` | 通过；另一组显式刚度／预紧／外载，使用相同计算路径 |
| `bolt-world-frame.case.json` | 通过；模型改名、旋转和平移后物理结果保持一致 |
| `bolt-overload.case.json` | 失败；本体通过，螺栓轴力超出预先声明的 1050 N 许用值 |
| `bolt-preload-overload.case.json` | 失败；使用阶段已卸载到允许值内，仍保留预紧和锁定超限 |
| `bolt-separated.case.json` | 通过；接头张开，无拉伸接触压力，螺栓单独承担显式外力；只检查已列判据 |
| `friction-stick.case.json` | 通过；控制接触面相对移动 0.00005 mm，剪应力约 0.5 MPa，低于摩擦上限 |
| `friction-motion-failure.case.json` | 失败；本体通过，滑动至 0.002 mm 超过预定 0.001 mm 任务限值；剪应力约 2 MPa |
| `friction-different-law-failure.case.json` | 失败；另一组摩擦系数和切向刚度，按相同判据计算 |
| `friction-force-controlled.case.json` | 证据不足；真实切向力经摩擦传递，使用阶段已收敛，但这组三层网格的预加载微小剪应力峰值未收敛，不能据此通过 |
| `bolt-friction-combined.case.json` | 通过；同一三阶段分析中结合锁定预紧和小幅切向位移 |

这里的“通过”均不授予产品承重。连接位移受控的夹具直接约束接触面切向位移，法向自由，目的是独立核对摩擦定律；实际产品不可照搬虚构夹具。

解析参考写在 `reference.json`：`kc = 1/(L/(EA) + 1/(kn*A))`，`C = kb/(kb+kc)`，锁定后 `Fbolt=P0+C*P`、`Fclamp=P0-(1-C)*P`（尚未分离时），`q0=P0/kb+P0/kc`。分离后使用单独的力平衡参考。摩擦夹具参考为 `p=P/A`、`tau=min(kt*delta,mu*p)`。比较容限在验证代码中预先规定，没有根据结果放宽。

验证套件还生成缺少摩擦来源、负螺栓刚度、轴线不对齐和超出小滑动范围的场景。前三种必须无效；超范围情况必须保留证据不足或无效，没有有利裕量。软件守卫另查缺少锁定阶段、锁定量改变、接触输出缺失、剪应力未收敛等情况。套件成功表示这些不利结论也符合预期，并非所有设计通过。
