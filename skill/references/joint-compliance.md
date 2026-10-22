# 等效关节柔度＋连杆柔度

用于固定基座、明确姿态、静定开链的小变形末端偏移估计。沿用现有连杆 FEM 和截面平移／转角传递；每个声明的独立转动关节增加一个扭转弹簧，移动关节增加一个轴向弹簧。无需新求解器、新依赖或新命令框架。

完整连续体／关节／控制耦合还需要多方向刚度、接口相容、间隙、驱动保持状态和受变形影响的载荷重新分配。这些并非每个日常静力任务都能提供。先使用这一层可控的近似；只有任务确实受未建模机制控制时，再升级模型。

## 最少增加哪些输入

在现有 `elastic_transfer` 中加入：

```json
"joint_compliance": {
  "elbow": {
    "rotational_stiffness_n_m_rad": 100,
    "reference": "数学参考常数，仅用于软件测试；实物应填写测试/手册来源、输出轴侧、通电保持或制动状态、载荷与温度范围",
    "verified": false
  }
},
"rigid_joints": ["mount"]
```

所有 URDF 关节必须恰好归入 `joint_compliance` 或 `rigid_joints`，包括固定安装关节。不得遗漏后自动按刚性处理。一个关节不能出现在两边。`joints_locked_verified` 仅表示显式刚性关节的锁定假设是否已确认；每个弹簧的 `verified` 单独表示刚度及其适用状态是否核实。未核实不阻止条件数值计算，但不能建立已验证物理条件。

- revolute/continuous：`rotational_stiffness_n_m_rad`，单位 **N·m/rad**。
- prismatic：改为 `linear_stiffness_n_m`，单位 **N/m**，每个关节只填一种。
- 刚度必须有限且大于零。不能用 URDF effort 上限、摩擦、阻尼、减速比或外观推算刚度；不设置经验默认值。
- 输入为关节输出坐标侧的等效刚度，包含哪些减速器／轴承／结构柔度须说明，避免重复计入已经纳入连杆 FEM 的同一柔度。禁止把电机轴侧刚度直接当作输出侧。

关节模型采用 `delta = Q_external / k`。转动关节的 Q 是外部子树力矩在实际关节轴上的投影，方向与保持力矩相反；移动关节采用轴向力。将相对位移、转角及其 `theta × lever_arm` 沿实际姿态传递，叠加连杆截面与自身材料场。固定重力、固定外载和完整载荷分别计算，不能把固定重量一起缩放。数学依据为静力虚功／Jacobian 转置关系，见 [Modern Robotics 第五章](https://modernrobotics.northwestern.edu/nu-gm-book-resource/velocity-kinematics-and-statics/)。

输入姿态是弹簧零变形的参考保持姿态，本模型把声明自重和外载全部作用于该参考。若输入已经是带载实测姿态，或控制器存在重力补偿、预偏置、主动纠偏，不能直接把同一载荷再计入 `Q/k`；应先建立相应的等效静态参考和刚度，无法说明时保留证据缺口。这里没有自动识别或仿真控制器。

## 直接使用

```powershell
.\.venv\Scripts\python.exe scripts/simplecae_cli.py check examples/robots/compliant-arm.robot.json
.\.venv\Scripts\python.exe scripts/simplecae_cli.py preview examples/robots/compliant-arm.robot.json --out outputs/compliant-preview-001
.\.venv\Scripts\python.exe scripts/simplecae_cli.py analyze examples/robots/compliant-arm.robot.json --out outputs/compliant-001
.\.venv\Scripts\python.exe scripts/simplecae_cli.py validate --suite joint-compliance --out outputs/joint-validation-001
```

同目录的 `compliant-arm-failure.robot.json` 设定更严格的末端任务，展示连杆独立通过而合成末端位移失败；`compliant-arm-large-motion.robot.json` 使用很软的关节，触发适用范围筛查并保持证据不足。这是数学测试，不是产品或实测机器人。

报告显示关节的广义力、弹性偏移、来源核实状态，以及测点的连杆／关节／总位移向量。**向量相加可能抵消，不能把两个模长相加当成总偏移**。相对测点先分别完成树传递再相减。`measurement_scope=first_order_link_and_joint_compliance`；完整连续体位移可用性仍为 false。

## 成立条件与拒绝边界

沿用 [连杆截面要求](contact-and-transfer.md#urdf-first-order-section-frame-transfer)：所有 link 显式 FEM 或刚性、每个 FEM 上游一个完整夹紧面、每个子关节一个平面材料端口、材料／质量／坐标／载荷映射检查及至少三档网格。末端总位移和传递帧仍须连续两次网格收敛。

现有转角与截面翘曲判据保持不变。每个关节转角及合成传递转角均不超过声明的 `max_rotation_rad`，该上限不得大于 0.05 rad。移动关节位移及包含移动关节的累计关节原点平移不超过机器人参考跨度的 1%；跨度取已声明的 link 原点、质心、载荷点和载荷质心的各点最大间距（不随世界坐标旋转改变），最小 1 mm，输出中保留该数值。1% 是适用性启发式筛查，不是高阶误差证明。超限保持 `indeterminate`，没有有利评估信号。

拒绝接触基座、闭合驱动反力路径、mimic／耦合驱动坐标，以及为固定关节指定轴向弹簧。未实现六自由度刚度矩阵、轴承侧向／倾斜柔度、柔性安装座、间隙／齿隙、摩擦迟滞、负载相关刚度、有限转动、P-delta 受力重分配、动力学和闭环控制响应。不支持自动整链承重外推；改变载荷重新计算。理想刚性方向不构成其刚度或强度的验证。

连杆应力仍来自原姿态静力载荷；关节柔度不会在这一阶模型中重新分配连杆应力。数值收敛不能证明关节刚度标定正确，也不能替代实物末端位移测试。关节轴／轴承／齿轮寿命和整机产品验收保持未评估。
