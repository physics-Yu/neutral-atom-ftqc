# 中性原子容错量子计算运行时与数字孪生：完整项目说明

## 1. 项目定位

本项目是一个面向研究与演示的中性原子容错量子计算软件原型。它的重点不是只计算一个抽象量子线路的末态，而是展示逻辑程序怎样逐层变成实验平台能够执行的物理动作，并在有限硬件资源、移动路径、测量反馈和原子损失条件下完成调度、执行、恢复与回放。

当前实现覆盖 M0–M8，端到端数据流为：

```text
LogicalCircuitIR
  -> QECProtocolIR / surface-code layout
  -> PhysicalTaskGraph（Physical ISA v0.1）
  -> RESST-style scheduler
  -> TimedSchedule
  -> DigitalTwinExecutor / MachineState
  -> ObservationBatch + ExecutionTrace + NoiseReport
  -> Decoder / LossManager / RuntimeController
  -> Pauli-frame update 或 DagMutation
  -> partial rescheduling
  -> standalone HTML/JSON visualization
```

首个工作负载使用四个表面码逻辑量子比特制备逻辑 GHZ：

```text
L0 = |+_L>, L1 = |0_L>, L2 = |0_L>, L3 = |0_L>

第 1 层：CNOT_L(L0, L1)
第 2 层：CNOT_L(L0, L2) || CNOT_L(L1, L3)
```

目标态是 `(|0000>_L + |1111>_L) / sqrt(2)`。这里第二层在逻辑上并行，但最终是否能物理并行，由 Rydberg 控制资源、区域容量、运输通道和几何冲突共同决定。

## 2. 关键设计原则

1. **逻辑层和物理层严格分离。** `LOGICAL_CNOT`、syndrome round 等只是编译器宏，不能进入调度器或数字孪生执行器。
2. **RESST 只调度物理工作。** 调度器只理解 DAG、时长、资源、区域容量、条件和优先级，不理解 GHZ、稳定子或 decoder 语义。
3. **机器状态显式演化。** 原子和逻辑块必须沿配置轨迹移动，不能跨区域瞬移；每一步都检查 atom/site 双射、区域容量、位置和 erasure 不变量。
4. **数据原子补位不等于恢复量子信息。** loss 后的新原子只恢复物理占位；数据位点必须保持 known erasure，直到后续 QEC 与 decoder 明确报告恢复。
5. **所有边界使用可序列化契约。** 图、计划、观察、轨迹、噪声和恢复决定均携带稳定 ID、版本及 provenance，便于复现和可视化关联。
6. **物理假设必须显式。** 时长、容量、路径和误差率来自配置；示例数值不得被解释为实验标定。
7. **distance 参数化。** 主演示使用 `d=3`，同一接口和测试也覆盖 `d=5`。

## 3. 代码目录与职责

| 路径 | 主要职责 |
| --- | --- |
| `src/compiler/` | Logical/QEC IR、Physical IR，以及逻辑/QEC 意图到物理任务 DAG 的 lowering |
| `src/qec/` | 旋转平面表面码布局、逻辑块、逻辑与稀疏物理 Pauli frame |
| `src/hardware/` | 原子、位点、区域、轨迹、资源配置和可变 MachineState |
| `src/scheduler/` | RESST 风格的确定性非抢占调度、资源日历、条件与部分重调度 |
| `src/simulator/` | 物理计划执行、状态转换、观察、trace、噪声模型和 ensemble benchmark |
| `src/decoder/` | syndrome history、单错误参考 decoder 和理想 erasure-aware decoder |
| `src/loss/` | loss 事件解释、有限 reservoir 分配与物理 refill 任务构造 |
| `src/runtime/` | decoder 反馈、Pauli frame 更新、DAG mutation 和恢复流程协调 |
| `src/visualization/` | 将图、计划、trace、观察和恢复事件投影成离线 HTML/JSON |
| `examples/` | 四逻辑比特 GHZ 端到端入口与低/高资源、理想/非零噪声配置 |
| `tests/` | 契约、编译、调度、执行、QEC、loss、runtime、噪声和端到端测试 |
| `docs/` | 架构、ISA、调度、数字孪生、QEC、loss、噪声及物理简化说明 |

## 4. 机器模型

参考机器包含四个区域：

- **Storage**：保存空闲的表面码逻辑块。
- **Entangling**：执行原子对齐与 Rydberg 两比特门。
- **Readout**：执行数据/ancilla 测量、存在性成像和允许的 reset。
- **Reservoir**：保存用于补位的有限备用原子。

`MachineConfig` 是不可变的设备/校准配置；`MachineState` 是执行过程中变化的时间、原子、位点、块位置、区域占用、reservoir 库存、已知 erasure 和 Pauli 错误状态。调度器检查活动区间的资源容量，执行器再次独立验证计划，并检查跨指令持续存在的机器状态。

轨迹由整数微米 waypoint、持续时间、冲突组、最小间距假设和最大平均路径速度描述。M8 会检查路径线段交叉：如果两条路径相交或重叠，却没有共享有限容量的冲突组，机器几何配置会被拒绝。该机制是保守的走廊级避冲突模型，不是连续多原子动力学或 AOD 波形仿真。

## 5. Physical ISA v0.1

数字孪生只执行以下 12 种物理操作：

| Opcode | 含义 |
| --- | --- |
| `MOVE_ATOMS` | 沿已配置路径移动指定原子 |
| `MOVE_BLOCK` | 沿已配置路径移动逻辑块 |
| `ALIGN_ATOMS` | 登记后续 Rydberg 门需要的原子配对 |
| `APPLY_1Q_PULSE` | 施加 H、X 或 `Ry(pi/2)` 等已支持的单比特脉冲 |
| `APPLY_2Q_RYDBERG_GATE` | 对已对齐原子对施加物理 CZ |
| `IMAGE_ATOMS` | 成像检查原子是否存在，并在缺失时报告 loss |
| `MEASURE_ATOMS` | 在 Readout 区进行 X/Z 基测量 |
| `RESET_ATOMS` | 对物理允许的原子执行 reset；不会恢复数据 erasure |
| `LOAD_RESERVOIR_ATOM` | 使用有限 reservoir 装载能力创建备用原子 |
| `PLACE_ATOM` | 将 replacement atom 放入空缺位点 |
| `WAIT` | 显式等待，不隐式省略时间成本 |
| `EMIT_SYNC` | 产生硬件/经典反馈同步边界 |

依赖屏障通过 DAG edge 表达，条件执行通过 `ConditionRef` 与运行时图变更表达。逻辑 opcode 或 QEC 宏一旦越过物理边界，会被契约、调度器或执行器拒绝。

## 6. M0–M8 实现内容

### M0：契约与验证骨架

建立带 schema 版本的 Logical IR、Physical IR、MachineConfig 与 Observation 契约；实现 canonical JSON、ID/单位/枚举校验、物理 DAG 无环及依赖完整性检查，并拒绝逻辑宏进入物理层。

### M1：表面码和 GHZ 逻辑/QEC IR

实现 distance 参数化的旋转平面表面码布局、逻辑块与 Pauli frame。构造四块 GHZ 逻辑图和 transversal CNOT 的 `d^2` 原子配对；第二逻辑层不添加虚假的串行依赖。

### M2：物理 ISA 与中性原子 lowering

把逻辑初始化和 transversal CNOT 展开为移动、对齐、单比特门、逐对 Rydberg CZ 与返回移动。每个物理任务携带资源、区域、时长、前驱和逻辑/QEC provenance。基础 GHZ 图在 `d=3` 与 `d=5` 下都保持 29 个任务，但每个批量任务的物理原子宽度由 distance 推导。

### M3：RESST 风格静态调度

实现确定性非抢占列表调度。它支持 DAG 依赖、release time、deadline、horizon、exclusive/shared 资源、区域容量、固定维护区间、消息 keep/consume、优先级和稳定 tie-break，并为每个等待或不可调度决定生成结构化诊断。

低资源与高资源配置使用同一物理 DAG。带最终测量的 `d=3` 41-task 基线，在参考配置中分别为：

- low：`1,266,400 ns`，第二层冲突操作被串行化；
- high：`466,400 ns`，容量允许的工作发生重叠。

这些数值是软件参考模型结果，不是实验性能数据。

### M4：数字孪生和可重放执行

实现事件驱动的 `DigitalTwinExecutor`。移动包含 start 时进入 `in_transit` 和 completion 时到达目标区两个阶段；门、成像、测量、reset、装载和补位更新机器状态或产生观察。执行器独立复核 graph/revision、任务覆盖、时长、依赖、资源、区域、轨迹和同一原子并发访问。

输出包括：

- `ExecutionTrace`：计划/实际时间、opcode、task ID、资源、区域、轨迹、provenance 和状态摘要；
- `MachineSnapshot`：原子/块位置、区域计数、符号态、reservoir、erasure 和对齐状态；
- `ObservationBatch`：measurement、syndrome、atom presence 和 atom loss；
- `final_state`：执行后的独立机器状态副本。

### M5：离线三视图可视化

生成无需网络的独立 HTML 和可审计 JSON sidecar。三种视图共用同一个纳秒时间游标：

1. 空间视图：显示 Storage、Entangling、Readout、Reservoir 和沿 waypoint 的移动；
2. Gantt：显示任务对每条硬件/走廊资源的占用、等待原因和 blocker；
3. 事件流：显示任务开始/结束、观察、loss、恢复、decoder 和噪声事件。

低/高资源结果可以放在同一 artifact 中切换比较；viewer 是只读回放，不修改原计划或机器状态。

### M6：syndrome、decoder 与 Pauli frame

将 surface-code syndrome round 降低为 reset、脉冲、移动、对齐、CZ、测量和同步等物理任务。观察被整理为 `SyndromeHistory` 并通过显式 `DecoderInput` 交给 decoder；decoder 返回 `DecoderResult` 和 `PauliFrameDelta`，不会直接修改调度器。

参考 decoder 支持理想 syndrome 与单 Pauli 错误查找。runtime 组合 logical/physical Pauli frame，并在 decoder latency 到达且条件消息满足后释放物理 continuation。`d=3` 的四块单轮 syndrome 图包含 133 个物理任务。

### M7：确定性 loss、补位和动态重调度

在指定 imaging 边界注入 atom loss。成像先报告 `atom_presence=false`，再产生 typed `atom_loss`；`LossManager` 登记 erasure，并从有限 reservoir 幂等地分配 replacement atom。

恢复链路为：

```text
loss detection
  -> erasure registration
  -> reservoir allocation
  -> PLACE_ATOM / RESET_ATOMS / verification image
  -> DagMutation revision
  -> partial RESST rescheduling
  -> physical syndrome round
  -> erasure-aware decoder
  -> erasure resolution
```

对于数据原子，补位、reset 和验证完成后 erasure 仍然存在，只有后续 decoder 返回 `recovered` 才能清除。ancilla loss 可采用较窄的重新制备策略。实现也覆盖 reservoir 耗尽、重复事件幂等、完成历史不可修改和受影响未来任务取消/替换。

### M8：固定种子噪声、几何保真度和扩展验证

`NoiseConfig` 显式记录 config ID、参数来源及单比特门、两比特门、reset、measurement、syndrome、成像 loss 和 Rydberg 串扰概率。`SeededNoiseModel` 使用 seed、配置、channel、task 与目标 identity 的稳定 SHA-256 派生值采样，因此结果不依赖 Python 容器或循环顺序。

实现的噪声效果包括：

- 单/双比特门和 reset 后的 X/Y/Z Pauli fault；
- X/Z 标记经过 H 和 CZ 的受支持 Clifford 传播；
- measurement 与 syndrome 结果翻转；
- 在显式 `IMAGE_ATOMS` 边界采样累计 atom loss；
- 按时间上重叠的其他 Rydberg 任务数量增加两比特串扰概率；
- `NoiseReport`、trace 噪声元数据和可视化 noise event；
- 多 seed shot 的 `ExperimentSummary` 及 JSON 往返。

M8 GHZ workload 包含一轮 syndrome、逻辑测量和最终 surveillance image；其 `d=5` 版本有 146 个物理任务。零概率配置与默认执行逐事件一致，不改变 M0–M7 的确定性语义。

## 7. 安装与测试

要求 Python 3.11 或更高版本。项目运行时没有第三方依赖；测试使用 pytest。

```powershell
cd C:\Users\86136\Desktop\实验线路编译GHZdemo\neutral-atom-ftqc
python -m pip install -e ".[dev]"
pytest
```

也可以不安装包，直接设置源码路径：

```powershell
$env:PYTHONPATH = "src;."
python examples\ghz_surface_code.py --help
```

M8 完成时的完整回归结果为 `112 passed`。

## 8. 常用演示命令

### 理想 GHZ 编译、调度、执行和测量

```powershell
$env:PYTHONPATH = "src;."
python examples\ghz_surface_code.py --distance 3 --execute --measure
```

### 比较资源竞争并生成三视图

```powershell
$env:PYTHONPATH = "src;."
python examples\ghz_surface_code.py --distance 3 --visualize artifacts\ghz-d3.html --compare-resources
```

输出 `artifacts\ghz-d3.html` 和 `artifacts\ghz-d3.json`。

### 执行 syndrome 与 decoder 反馈

```powershell
$env:PYTHONPATH = "src;."
python examples\ghz_surface_code.py --distance 3 --syndrome-rounds 1 --decode
```

### 演示确定性数据原子 loss 恢复

```powershell
$env:PYTHONPATH = "src;."
python examples\ghz_surface_code.py --distance 3 --inject-loss --visualize artifacts\ghz-loss-d3.html
```

### 执行 M8 seeded-noise ensemble

```powershell
$env:PYTHONPATH = "src;."
python examples\ghz_surface_code.py `
  --distance 3 `
  --profile low `
  --noise-config examples\config\noise-illustrative.json `
  --shots 16 `
  --seed 100 `
  --noise-summary artifacts\noise-d3.json `
  --visualize artifacts\noise-d3.html
```

### 验证 d=5 扩展路径

```powershell
$env:PYTHONPATH = "src;."
python examples\ghz_surface_code.py --distance 5 --profile high --noise-config examples\config\noise-ideal.json --shots 2 --seed 0
```

## 9. 配置说明

- `examples/config/resources-low.json`：限制 AOD、单比特控制、Rydberg 和关键运输走廊容量，用于展示物理串行化。
- `examples/config/resources-high.json`：提高相应容量，用于展示合法并行。
- `examples/config/noise-ideal.json`：所有噪声概率为零，用于确定性回归。
- `examples/config/noise-illustrative.json`：非零合成参数，用于验证事件、统计和可视化管线。

修改配置时必须保留明确的 `machine_config_id` 或 `config_id`。噪声配置的 `parameter_source` 必须说明来源；如果未来接入实验数据，应记录设备、标定时间、数据版本、单位和适用条件。

## 10. 输出如何解读

- task count 表示物理 DAG 节点数，不等于逐原子门数；一个 task 可以携带随 distance 增长的 atom/pair batch。
- makespan 是参考配置下的调度时间，不含未建模的控制器上传、网络或设备启动延迟。
- `NoiseReport` 记录采样事件，不直接等价于 logical error rate。
- measurement/syndrome observation 是执行接口输出；当前 symbolic backend 不提供完整 Born sampling。
- decoder 的 `recovered` 是参考控制流模型的决定，不是任意相关噪声下的容错证明。
- HTML 中看到的原子块和路径是解释性投影，不是按比例绘制的光场或每颗原子轨迹。

## 11. 已验证的不变量

测试覆盖以下关键性质：

- IR JSON 往返、稳定 ID、schema、DAG 无环和未知依赖拒绝；
- logical/QEC 宏不能进入 Physical ISA、RESST 或 executor；
- `d=3`/`d=5` layout、稳定子与 transversal pairing 参数化；
- 依赖顺序、资源/区域容量、互斥与 shared claim、条件和稳定 tie-break；
- 轨迹绑定、同一 atom 并发、持久区域占用及机器状态不变量；
- measurement、syndrome、loss observation 与 trace 可重放；
- refill 后数据 erasure 仍存在，只有 QEC/decoder 可以完成逻辑恢复；
- graph revision、完成历史不变与部分 rescheduling；
- 固定 seed 复现、概率分布 sanity check、零噪声兼容；
- 交叉路径必须声明共享冲突组，超速轨迹被拒绝；
- 并行 Rydberg 串扰敏感性和 `d=5` 规模运行。

## 12. 当前模型明确不证明的内容

本项目目前是可复现的软件执行栈原型，不是经实验验证的容错性能模拟器。它没有证明：

- 逻辑 GHZ fidelity 或 surface-code threshold；
- 参考 transversal CNOT 对某台真实设备边界和朝向完全成立；
- 完整 stabilizer/amplitude 波函数动力学和 Born statistics；
- 泄漏、相干误差、空间/时间相关噪声、pulse shape、激光漂移和 loss 误检；
- 连续多原子最小间距、加速度、转弯和 AOD/SLM 波形可实现性；
- 理想 erasure-aware decoder 在任意 erasure 几何和相关错误下都能恢复；
- 示例时长、容量和误差率代表实验平台标定值。

因此，非零噪声 ensemble 的正确用途是验证 seed 复现、故障传播接口、资源并行敏感性、事件可审计性和 d=5 软件规模，而不是发表硬件保真度结论。

## 13. 后续扩展建议

1. 接入经过版本化的真实设备标定和不确定度，而不是直接修改示例 synthetic config。
2. 在现有 `StateBackend` 接口后增加 stabilizer 或张量网络后端，独立验证 logical GHZ 与 QEC 效果。
3. 用 MWPM、union-find 或其他真实 decoder 替换参考 oracle，并联合处理 Pauli 与 erasure。
4. 扩展到重复 noisy syndrome rounds、measurement error history、leakage 和 correlated loss。
5. 引入连续轨迹规划、blockade radius、AOD lane/waveform、加速度和热运动约束。
6. 让调度策略可以优化预期错误风险、deadline 和吞吐量，而不只优化最早可行开始时间。
7. 接入真实控制后端时保留 Physical ISA、schedule、observation 和 replay contract，不绕过现有层次边界。

## 14. 进一步阅读

- `docs/architecture_and_implementation_plan.md`：原始架构审计、IR 设计、M0–M8 验收标准和未决问题。
- `docs/instruction_set.md`：Physical ISA v0.1 的详细语义。
- `docs/physical_lowering.md`：GHZ/QEC 到中性原子物理任务的 lowering。
- `docs/scheduling.md`：RESST 调度契约与策略。
- `docs/digital_twin.md`：机器状态和执行器边界。
- `docs/visualization.md`：三视图 artifact 格式。
- `docs/qec_runtime.md`：syndrome、decoder 与 Pauli-frame feedback。
- `docs/loss_recovery.md`：known-erasure、reservoir 和动态重调度。
- `docs/noise_and_scaling.md`：M8 噪声、几何和扩展性假设。

