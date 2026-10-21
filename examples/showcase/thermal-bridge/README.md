# Control-board heat bridge / 控制板导热支座

**A four-part CAD assembly, one selected solid analysis, two design revisions.**
The assembly contains a mount, heat bridge, heater envelope and cover. The Agent
does not mesh every part: the question is whether the bridge can conduct 5 W to
an ideal 20°C cold end while staying below 40°C.

The parts were created with SimpleCADAPI. Editable notebooks and STEP exports
are included; the CAE run only needs the STEP files and the SimpleCAE environment.
Rebuilding the CAD notebooks additionally requires SimpleCADAPI 2.2.4 and its
documented `sca run` workflow.

| Revision | Allowed change | Recorded maximum temperature | Scoped outcome |
|---|---|---:|---|
| r1 | Initial 2 mm bridge | 49.94012°C | Temperature criterion fails |
| r2 | Bridge thickness 4 mm | 34.97006°C | Temperature criterion passes |

Both retain 5 W, conductivity 167 W/(m·K), a 20°C cold end, other faces insulated,
the 40°C limit and the original mesh/energy checks. The independent resistance
estimate is \(T_h=20+5L/(kA)\): it explains *why* increasing the conducting
section is a sensible CAD hypothesis. A result does not prove the real heatsink
can hold 20°C or that the assembly's contact resistance is negligible.

![Revised CAD assembly](r2/product.png)

## Try it

From the repository root, use `simplecae` in the configured environment (or the
environment's Python followed by `scripts/simplecae_cli.py`):

```text
simplecae task start examples/showcase/thermal-bridge/r1/task.json --out outputs/bridge-r1 --run temperature --brief
simplecae task start examples/showcase/thermal-bridge/r2/task.json --out outputs/bridge-r2 --viewer-session outputs/bridge-r1/viewer --run temperature --brief
simplecae view --session outputs/bridge-r1/viewer --serve --open
```

Use fresh output names when repeating. `network` and `warmup` are additional
declared calculation checks: run them explicitly through `task run` when the
steady resistance or lumped warm-up question matters. They do not run merely
because they appear in the assembly's task inventory.

Example Agent request:

> This is a robot controller mount with a 5 W heat source. Keep the cold end at
> the stated 20°C screening condition and the hot end below 40°C. Check the heat
> path first, explain the limiting section, then change only the bridge geometry.
> Keep contact resistance and real cooling as explicit unknowns. Show both
> revisions in the Viewer and do not infer hot strength from temperature.

The task still lists geometry and real-interface follow-ups separately.
Temperature acceptance is not whole-product acceptance, touch safety, hot
strength, fatigue/creep or independently qualified pointwise heat flux.

## 中文使用说明

这是一个由安装座、导热桥、热源包络和罩壳组成的四部件模型。需求是把 **5 W**
热量通过桥传到假设的 **20°C** 冷端，桥上最高温度不超过 **40°C**。
Agent 先选导热路径检查，再只对关键导热桥做实体分析，无须把四个零件全部求解。

原 2 mm 桥算得约 **49.94°C**，不满足要求；将桥加厚到 4 mm 后约 **34.97°C**，
通过这一温度判据。热阻估算与实体计算提供同方向证据，载荷和判据没有改变。
上面的三条命令可重现两版任务并打开同一个 Viewer。

可直接对 Agent 说：

> 这是机器人控制板的导热支座，热源5W。请在原20°C理想冷端和40°C上限下，
> 判断需要检查哪些部件，先估算热阻，再核查桥上的温度；仅修改导热桥截面，
> 在Viewer展示改型前后的结果。实际热接触、冷端散热和高温强度单独保留，
> 不要把温度通过当成产品通过。

`network` 和 `warmup` 分别是任务中声明的稳态热阻、集总升温检查，需要时再选择运行。
CAD 文件、模型假设和任务记录均可查看；数值参考不代替真实接口与材料数据。
