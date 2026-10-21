# 三种结果和一次几何迭代

在完整 skill 目录完成 bootstrap 后，先运行一个实际 STEP 分析：

```powershell
.\.venv\Scripts\python.exe scripts/simplecae_cli.py quickstart --out outputs/first-001
```

打开命令输出的 `pass/report.html`。随后一次运行全部示例：

```powershell
.\.venv\Scripts\python.exe scripts/simplecae_cli.py quickstart --example all --out outputs/examples-001
```

输出目录必须不存在；再次运行换一个名字。生成的 `quickstart.json` 表示示例是否产生预期行为；失败示例得到失败，才是示例测试成功。原始求解、场、网格、输入快照及 `signal.json` 保存在各子目录。

| 输入 | 条件与预期 | 应采取的行动 |
|---|---|---|
| `pass.case.json` | 100×10×10 mm 悬臂，100 N 端面力；强度及 0.3 mm 位移要求在声明模型下通过 | 查看受力和报告中的未知条件，再用于相同假设下的设计筛选 |
| `fail.case.json` | 同一零件，200 N；判据保持不变，位移超限 | 修改几何或重新讨论实际需求；保留失败记录 |
| `indeterminate.case.json` | 100 N，未提供强度值和适用失效准则；弹性位移仍可计算 | 补充材料强度证据；不要从位移通过推断整体通过或承重 |
| `iteration.case.json` | 保持失败案例的 200 N、材料、约束、0.3 mm 和质量门槛，只把宽度从 10 改成 20 mm | 对照 `candidate-comparison.json`；此例不放宽判据 |

E=200000 MPa、ν=0.3、屈服参考值 200 MPa、安全系数 2，均为数学演示参数。梁的解析端部挠度参考为 FL³/(3EI)：100 N 原梁约 0.2 mm，200 N 原梁约 0.4 mm，加宽梁在 200 N 下约 0.2 mm。有限元还包含剪切与夹持端效应，不要求与梁公式逐位相等。

所有实物核实标记保持 false，示例不输出产品额定承重。未评估螺钉/墙体、真实夹持柔度、自重、屈曲、疲劳、冲击、制造差异。`indeterminate` 是合法任务的证据不足，区别于单位、几何或约束错误导致的 `invalid`。

这些 STEP、输入和生成脚本由 SimpleCAE 编写，按项目 GPL-3.0-or-later 提供。可用 `python examples/preview/generate.py` 重新生成；STEP 时间戳可能改变哈希，生成后需重新验证。无需 SimpleCADAPI 或 text-to-cad 即可运行。
