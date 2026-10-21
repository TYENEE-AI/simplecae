# Engineering decision examples / 工程决策案例

These are authored CAD assemblies and explicit analysis inputs, not product
certifications. Rebuilding CAD uses optional SimpleCADAPI; exported geometry
can be analyzed with SimpleCAE alone.

| Example | Decision | Expected scope |
|---|---|---|
| [Thermal bridge](thermal-bridge/README.md) | Failing 2 mm section motivates a 4 mm revision at unchanged heat input and limit | Temperature fail → pass; real cooling unknown |
| [Inspection arm](inspection-arm/README.md) | Separate drive demand, joint and link flexibility; avoid unjustified thickness multipliers | Held-pose transfer applicability unresolved |
| [Sensor mast](sensor-mast/README.md) | Retain bolt/contact stages and local root checks after a fillet change | Service can pass while preload/locked convergence remains incomplete |

Use fresh output folders for repeats. Correctly reporting a failed or incomplete
design demonstrates the tool's decision boundary, not a passing mechanical design.

三例分别展示“有依据地改截面”“先查柔度来源与适用性”“保留安装阶段热点”。
失败或证据不足不会因为是演示而变成通过。源码、载荷、材料、条件和判据可检查；
输出在本地生成，不随源码携带私人历史。
