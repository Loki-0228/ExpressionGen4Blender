# 表情计算规则

JSON 与本表同名；JSON 保留完整数值、曲线、依赖和参数，可在插件中重新导入。内置公式由指定求解器执行，不执行文件中的脚本。

## まばたき

| 顺序 | 阶段 | 计算准则 | 条件 | 数值路径 | 实现 |
| --- | --- | --- | --- | --- | --- |
| 1 | 对称策略 | 允许强制左右对称；正侧完成约束后直接镜像最终坐标到负侧，不再两侧平均。独立眼眉在相关顶点可配对时只计算正侧，不要求三角面划分相同。跨中线口型保留整体求解；活动顶点无法配对则跳过。镜像后的翻折数量写入报告 | 生成时开启强制对称 | can_symmetrize / special / relation | procedural_symmetry |
| 2 | 输入 | 按当前标记读取；已删除必要曲线所依赖的表情跳过 | 存在对应分区时执行 | recipe | procedural_rig.checkpoint |
| 3 | 眼部目标 | 按眼宽和眼高归一化；普通闭眼反射当前上眼缘曲率，笑闭眼保留上拱 | 存在对应分区时执行 | recipe | procedural_atoms.character_arc |
| 4 | 眼缘拟合 | 上下缘共用闭眼接缝；上缘向下、水平下缘不下降且上移上限 30%，笑眼弧顶额外 10%。闭眼内眼角允许下降，但不低于原始下眼睑横向主体，并略微上提。笑眼保持上拱，なごみ保持直线；边界冲突则跳过并说明原因 | 存在对应分区时执行 | recipe | procedural_atoms.solve |
| 5 | 皮肤求解 | 固定眼口控制点，沿 Face 邻接平滑传播 | 存在对应分区时执行 | recipe | procedural_skin.EyelidSkin.deform |
| 6 | 防破面 | 保持轮廓约束，限制局部修正，残余冲突写入报告 | 存在对应分区时执行 | recipe | procedural_constraints.finalize_skin |
| 7 | 眼部接触 | 沿用原始预设的眼层依次避让。高光、瞳孔、眼白依次执行整体深度位移，保留原始间距和形状；检查 Basis 到终点的 16 个权重。位移上限保留闭眼眼宽 24%、睁眼 35%，Basis 不变。整片睫毛向内贴合、向外避让，保留原始嵌入。未消除的接触与覆盖问题写入报告 | 存在对应分区时执行 | recipe | procedural_constraints.closed_eye_stack / procedural_lashes.lower_owned_upper_sections |
| 8 | 睫毛 | 拟合原始截面中心，沿最终 XYZ 闭眼曲线统一平移和旋转截面，保留厚度；眼尾连续延伸，不截断修正斜率。单根睫毛、双眼皮等共用最终截面变换，眉毛独立。竖向眼角平滑进入弯折区，之后执行贴脸与避让，并复查最终闭合线覆盖。まばたき下凹、笑い上拱且弧度延续到眼尾、なごみ优先水平平直；闭眼接合和下眼睑限幅更强。单根只读取已有标记 | 存在对应分区时执行 | recipe | procedural_lashes.style_band / fold_vertical_sections / finish_upper_sweep / deform / audit_closed_band |
| 9 | 风格设置 | 下眼睑参与量在可行闭合范围中选择接合位置，不改变下眼睑 30% 上移及笑眼弧顶额外 10% 的硬上限。笑眼弧度与形态保持调整曲线偏好，闭合、接触和厚度优先。组合、曲线写回沿用生成时保存的风格设置 | 存在对应分区时执行 | recipe | procedural_ui.generation_options / procedural_binding.styled_closure |
| 10 | 闭眼层次 | 下睫毛随实际下眼眶的连续位移和旋转运动。闭眼时将整条下睫毛的上下缘收在上睫毛投影内，再求解前后层次。Face 接触后复查并修正遮盖，最终悬空和覆盖不足单独报告 | 存在对应分区时执行 | recipe | procedural_lashes.follow_lower_rim / cover_lower_band / finish_closed_order |
| 11 | 眼角弯折 | 跟随下眼眶的强度随切线倾角连续增加，垂直达到 1，继续内斜仍保持 1。按原曲线弧长定位截面，避免竖向长度展开成内眼角横向拉长。普通闭眼保留内眼角跨度约束，なごみ和笑闭眼保持整条中心线的横向长度；单眼表情继承对应约束 | 存在对应分区时执行 | recipe | procedural_lashes.slope_follow_weight / finish_upper_sweep |
| 12 | 计算设备 | Windows NVIDIA CUDA 可用时，以双精度 GPU 内核求解三角面投影接触。小任务、缺少运行库、显存或调用失败时使用 CPU。两种设备共用几何规则、容差和可移动条件，报告设备、调用数与回退原因 | 存在对应分区时执行 | recipe | procedural_gpu.try_depth |
| 13 | 口腔 | 口内边界固定到实际唇缘，内部连续变形；强制镜像后重新贴合 Face 与 Mouth，避免两次表面插值产生小接缝 | 存在对应分区时执行 | recipe | procedural_cavity.deform |
| 14 | 牙齿 | 内置口型按 Original 张口时牙片的一致运动校准上下排，再按嘴宽适配各自位移与旋转，不重复叠加竖向随唇浮动。原参考静止的牙齿保持原位；目标有小间隙时，下牙整组上移至首次接触，最多嘴宽的 30%，缺少独立上下牙则跳过。未校准的自定义或下颌动作保留有界随唇处理。接触可先收回校准动作中的前移，再按牙弓与嘴宽的较大值取 6.5% 额度整排后移，保留牙弓及上下行程；未校准动作仍采用 2.5% 共同后移及 4% 局部后移。检查局部修正是否引入新的三角面翻折；额度不足记录穿插，不向外推 Face，不缩放牙弓，不改变 Basis | 存在对应分区时执行 | recipe | procedural_constraints.close_dental_contact / procedural_contacts.oral_face |
| 15 | 口内接触 | 按唇缘相连拓扑选择 Face 接触面，包含斜面及内翻唇面；牙齿及口腔退回面部内侧，口腔唇缘固定。取消舌头随整排牙齿最前点后退；牙齿与舌头的接触只由实际三角面交叉触发。舌头上表面避开下口腔，Basis 同样检查；接触位移上限取舌长 12% 和口宽 8% 的较小值，同次修正反复检查共用额度；超出额度报告冲突 | 存在对应分区时执行 | recipe | procedural_contacts.finish / tongue_teeth / tongue_side |
| 16 | 写入 | 表情形态键、口腔联动和最终变形曲线一起保存 | 存在对应分区时执行 | recipe | procedural_generate.generate |
| 17 | 眼部数值 | 位移采样 × 当前眼宽；Z 再乘当前眼高与参考高宽比修正；17 个 XYZ 采样保存在 JSON | 按当前曲线与分区计算 | recipe.eyes.-1.upper | procedural_atoms.sampled |
| 18 | 眼部数值 | 位移采样 × 当前眼宽；Z 再乘当前眼高与参考高宽比修正；17 个 XYZ 采样保存在 JSON | 按当前曲线与分区计算 | recipe.eyes.-1.lower | procedural_atoms.sampled |
| 19 | 闭合规则 | 闭合=1；下眼参与=0.237818；笑眼=0；平直=0。上缘不升、水平下缘不降且限幅；竖向眼角以转折为下降边界。笑眼上拱、なごみ平直，冲突不回退为相反曲率。 | 按当前曲线与分区计算 | recipe.eyes.-1 | procedural_atoms.solve |
| 20 | 眼部数值 | 位移采样 × 当前眼宽；Z 再乘当前眼高与参考高宽比修正；17 个 XYZ 采样保存在 JSON | 按当前曲线与分区计算 | recipe.eyes.1.upper | procedural_atoms.sampled |
| 21 | 眼部数值 | 位移采样 × 当前眼宽；Z 再乘当前眼高与参考高宽比修正；17 个 XYZ 采样保存在 JSON | 按当前曲线与分区计算 | recipe.eyes.1.lower | procedural_atoms.sampled |
| 22 | 闭合规则 | 闭合=1；下眼参与=0.237818；笑眼=0；平直=0。上缘不升、水平下缘不降且限幅；竖向眼角以转折为下降边界。笑眼上拱、なごみ平直，冲突不回退为相反曲率。 | 按当前曲线与分区计算 | recipe.eyes.1 | procedural_atoms.solve |

数值定义：JSON 中 `expressions` 的同名项。

## 笑い

| 顺序 | 阶段 | 计算准则 | 条件 | 数值路径 | 实现 |
| --- | --- | --- | --- | --- | --- |
| 1 | 对称策略 | 允许强制左右对称；正侧完成约束后直接镜像最终坐标到负侧，不再两侧平均。独立眼眉在相关顶点可配对时只计算正侧，不要求三角面划分相同。跨中线口型保留整体求解；活动顶点无法配对则跳过。镜像后的翻折数量写入报告 | 生成时开启强制对称 | can_symmetrize / special / relation | procedural_symmetry |
| 2 | 输入 | 按当前标记读取；已删除必要曲线所依赖的表情跳过 | 存在对应分区时执行 | recipe | procedural_rig.checkpoint |
| 3 | 眼部目标 | 按眼宽和眼高归一化；普通闭眼反射当前上眼缘曲率，笑闭眼保留上拱 | 存在对应分区时执行 | recipe | procedural_atoms.character_arc |
| 4 | 眼缘拟合 | 上下缘共用闭眼接缝；上缘向下、水平下缘不下降且上移上限 30%，笑眼弧顶额外 10%。闭眼内眼角允许下降，但不低于原始下眼睑横向主体，并略微上提。笑眼保持上拱，なごみ保持直线；边界冲突则跳过并说明原因 | 存在对应分区时执行 | recipe | procedural_atoms.solve |
| 5 | 皮肤求解 | 固定眼口控制点，沿 Face 邻接平滑传播 | 存在对应分区时执行 | recipe | procedural_skin.EyelidSkin.deform |
| 6 | 防破面 | 保持轮廓约束，限制局部修正，残余冲突写入报告 | 存在对应分区时执行 | recipe | procedural_constraints.finalize_skin |
| 7 | 眼部接触 | 沿用原始预设的眼层依次避让。高光、瞳孔、眼白依次执行整体深度位移，保留原始间距和形状；检查 Basis 到终点的 16 个权重。位移上限保留闭眼眼宽 24%、睁眼 35%，Basis 不变。整片睫毛向内贴合、向外避让，保留原始嵌入。未消除的接触与覆盖问题写入报告 | 存在对应分区时执行 | recipe | procedural_constraints.closed_eye_stack / procedural_lashes.lower_owned_upper_sections |
| 8 | 睫毛 | 拟合原始截面中心，沿最终 XYZ 闭眼曲线统一平移和旋转截面，保留厚度；眼尾连续延伸，不截断修正斜率。单根睫毛、双眼皮等共用最终截面变换，眉毛独立。竖向眼角平滑进入弯折区，之后执行贴脸与避让，并复查最终闭合线覆盖。まばたき下凹、笑い上拱且弧度延续到眼尾、なごみ优先水平平直；闭眼接合和下眼睑限幅更强。单根只读取已有标记 | 存在对应分区时执行 | recipe | procedural_lashes.style_band / fold_vertical_sections / finish_upper_sweep / deform / audit_closed_band |
| 9 | 风格设置 | 下眼睑参与量在可行闭合范围中选择接合位置，不改变下眼睑 30% 上移及笑眼弧顶额外 10% 的硬上限。笑眼弧度与形态保持调整曲线偏好，闭合、接触和厚度优先。组合、曲线写回沿用生成时保存的风格设置 | 存在对应分区时执行 | recipe | procedural_ui.generation_options / procedural_binding.styled_closure |
| 10 | 闭眼层次 | 下睫毛随实际下眼眶的连续位移和旋转运动。闭眼时将整条下睫毛的上下缘收在上睫毛投影内，再求解前后层次。Face 接触后复查并修正遮盖，最终悬空和覆盖不足单独报告 | 存在对应分区时执行 | recipe | procedural_lashes.follow_lower_rim / cover_lower_band / finish_closed_order |
| 11 | 眼角弯折 | 跟随下眼眶的强度随切线倾角连续增加，垂直达到 1，继续内斜仍保持 1。按原曲线弧长定位截面，避免竖向长度展开成内眼角横向拉长。普通闭眼保留内眼角跨度约束，なごみ和笑闭眼保持整条中心线的横向长度；单眼表情继承对应约束 | 存在对应分区时执行 | recipe | procedural_lashes.slope_follow_weight / finish_upper_sweep |
| 12 | 计算设备 | Windows NVIDIA CUDA 可用时，以双精度 GPU 内核求解三角面投影接触。小任务、缺少运行库、显存或调用失败时使用 CPU。两种设备共用几何规则、容差和可移动条件，报告设备、调用数与回退原因 | 存在对应分区时执行 | recipe | procedural_gpu.try_depth |
| 13 | 口腔 | 口内边界固定到实际唇缘，内部连续变形；强制镜像后重新贴合 Face 与 Mouth，避免两次表面插值产生小接缝 | 存在对应分区时执行 | recipe | procedural_cavity.deform |
| 14 | 牙齿 | 内置口型按 Original 张口时牙片的一致运动校准上下排，再按嘴宽适配各自位移与旋转，不重复叠加竖向随唇浮动。原参考静止的牙齿保持原位；目标有小间隙时，下牙整组上移至首次接触，最多嘴宽的 30%，缺少独立上下牙则跳过。未校准的自定义或下颌动作保留有界随唇处理。接触可先收回校准动作中的前移，再按牙弓与嘴宽的较大值取 6.5% 额度整排后移，保留牙弓及上下行程；未校准动作仍采用 2.5% 共同后移及 4% 局部后移。检查局部修正是否引入新的三角面翻折；额度不足记录穿插，不向外推 Face，不缩放牙弓，不改变 Basis | 存在对应分区时执行 | recipe | procedural_constraints.close_dental_contact / procedural_contacts.oral_face |
| 15 | 口内接触 | 按唇缘相连拓扑选择 Face 接触面，包含斜面及内翻唇面；牙齿及口腔退回面部内侧，口腔唇缘固定。取消舌头随整排牙齿最前点后退；牙齿与舌头的接触只由实际三角面交叉触发。舌头上表面避开下口腔，Basis 同样检查；接触位移上限取舌长 12% 和口宽 8% 的较小值，同次修正反复检查共用额度；超出额度报告冲突 | 存在对应分区时执行 | recipe | procedural_contacts.finish / tongue_teeth / tongue_side |
| 16 | 写入 | 表情形态键、口腔联动和最终变形曲线一起保存 | 存在对应分区时执行 | recipe | procedural_generate.generate |
| 17 | 眼部数值 | 位移采样 × 当前眼宽；Z 再乘当前眼高与参考高宽比修正；17 个 XYZ 采样保存在 JSON | 按当前曲线与分区计算 | recipe.eyes.-1.upper | procedural_atoms.sampled |
| 18 | 眼部数值 | 位移采样 × 当前眼宽；Z 再乘当前眼高与参考高宽比修正；17 个 XYZ 采样保存在 JSON | 按当前曲线与分区计算 | recipe.eyes.-1.lower | procedural_atoms.sampled |
| 19 | 闭合规则 | 闭合=1；下眼参与=0.372763；笑眼=1；平直=0。上缘不升、水平下缘不降且限幅；竖向眼角以转折为下降边界。笑眼上拱、なごみ平直，冲突不回退为相反曲率。 | 按当前曲线与分区计算 | recipe.eyes.-1 | procedural_atoms.solve |
| 20 | 眼部数值 | 位移采样 × 当前眼宽；Z 再乘当前眼高与参考高宽比修正；17 个 XYZ 采样保存在 JSON | 按当前曲线与分区计算 | recipe.eyes.1.upper | procedural_atoms.sampled |
| 21 | 眼部数值 | 位移采样 × 当前眼宽；Z 再乘当前眼高与参考高宽比修正；17 个 XYZ 采样保存在 JSON | 按当前曲线与分区计算 | recipe.eyes.1.lower | procedural_atoms.sampled |
| 22 | 闭合规则 | 闭合=1；下眼参与=0.372768；笑眼=1；平直=0。上缘不升、水平下缘不降且限幅；竖向眼角以转折为下降边界。笑眼上拱、なごみ平直，冲突不回退为相反曲率。 | 按当前曲线与分区计算 | recipe.eyes.1 | procedural_atoms.solve |

数值定义：JSON 中 `expressions` 的同名项。

## ウィンク

| 顺序 | 阶段 | 计算准则 | 条件 | 数值路径 | 实现 |
| --- | --- | --- | --- | --- | --- |
| 1 | 对称策略 | 不对该表情强制镜像；保留子表情、组合或特殊动作的定义 | 生成时开启强制对称 | can_symmetrize / special / relation | procedural_symmetry |
| 2 | 表情依赖 | 引用来源=笑い；条件在模型归一化坐标及当前分区中计算，边界连续衰减；不参与强制对称 | 来源可生成且依赖无循环 | relation | expression_relations.Solver |
| 3 | 输入 | 按当前标记读取；已删除必要曲线所依赖的表情跳过 | 存在对应分区时执行 | recipe | procedural_rig.checkpoint |
| 4 | 眼部目标 | 按眼宽和眼高归一化；普通闭眼反射当前上眼缘曲率，笑闭眼保留上拱 | 存在对应分区时执行 | recipe | procedural_atoms.character_arc |
| 5 | 眼缘拟合 | 上下缘共用闭眼接缝；上缘向下、水平下缘不下降且上移上限 30%，笑眼弧顶额外 10%。闭眼内眼角允许下降，但不低于原始下眼睑横向主体，并略微上提。笑眼保持上拱，なごみ保持直线；边界冲突则跳过并说明原因 | 存在对应分区时执行 | recipe | procedural_atoms.solve |
| 6 | 皮肤求解 | 固定眼口控制点，沿 Face 邻接平滑传播 | 存在对应分区时执行 | recipe | procedural_skin.EyelidSkin.deform |
| 7 | 防破面 | 保持轮廓约束，限制局部修正，残余冲突写入报告 | 存在对应分区时执行 | recipe | procedural_constraints.finalize_skin |
| 8 | 眼部接触 | 沿用原始预设的眼层依次避让。高光、瞳孔、眼白依次执行整体深度位移，保留原始间距和形状；检查 Basis 到终点的 16 个权重。位移上限保留闭眼眼宽 24%、睁眼 35%，Basis 不变。整片睫毛向内贴合、向外避让，保留原始嵌入。未消除的接触与覆盖问题写入报告 | 存在对应分区时执行 | recipe | procedural_constraints.closed_eye_stack / procedural_lashes.lower_owned_upper_sections |
| 9 | 睫毛 | 拟合原始截面中心，沿最终 XYZ 闭眼曲线统一平移和旋转截面，保留厚度；眼尾连续延伸，不截断修正斜率。单根睫毛、双眼皮等共用最终截面变换，眉毛独立。竖向眼角平滑进入弯折区，之后执行贴脸与避让，并复查最终闭合线覆盖。まばたき下凹、笑い上拱且弧度延续到眼尾、なごみ优先水平平直；闭眼接合和下眼睑限幅更强。单根只读取已有标记 | 存在对应分区时执行 | recipe | procedural_lashes.style_band / fold_vertical_sections / finish_upper_sweep / deform / audit_closed_band |
| 10 | 风格设置 | 下眼睑参与量在可行闭合范围中选择接合位置，不改变下眼睑 30% 上移及笑眼弧顶额外 10% 的硬上限。笑眼弧度与形态保持调整曲线偏好，闭合、接触和厚度优先。组合、曲线写回沿用生成时保存的风格设置 | 存在对应分区时执行 | recipe | procedural_ui.generation_options / procedural_binding.styled_closure |
| 11 | 闭眼层次 | 下睫毛随实际下眼眶的连续位移和旋转运动。闭眼时将整条下睫毛的上下缘收在上睫毛投影内，再求解前后层次。Face 接触后复查并修正遮盖，最终悬空和覆盖不足单独报告 | 存在对应分区时执行 | recipe | procedural_lashes.follow_lower_rim / cover_lower_band / finish_closed_order |
| 12 | 眼角弯折 | 跟随下眼眶的强度随切线倾角连续增加，垂直达到 1，继续内斜仍保持 1。按原曲线弧长定位截面，避免竖向长度展开成内眼角横向拉长。普通闭眼保留内眼角跨度约束，なごみ和笑闭眼保持整条中心线的横向长度；单眼表情继承对应约束 | 存在对应分区时执行 | recipe | procedural_lashes.slope_follow_weight / finish_upper_sweep |
| 13 | 计算设备 | Windows NVIDIA CUDA 可用时，以双精度 GPU 内核求解三角面投影接触。小任务、缺少运行库、显存或调用失败时使用 CPU。两种设备共用几何规则、容差和可移动条件，报告设备、调用数与回退原因 | 存在对应分区时执行 | recipe | procedural_gpu.try_depth |
| 14 | 口腔 | 口内边界固定到实际唇缘，内部连续变形；强制镜像后重新贴合 Face 与 Mouth，避免两次表面插值产生小接缝 | 存在对应分区时执行 | recipe | procedural_cavity.deform |
| 15 | 牙齿 | 内置口型按 Original 张口时牙片的一致运动校准上下排，再按嘴宽适配各自位移与旋转，不重复叠加竖向随唇浮动。原参考静止的牙齿保持原位；目标有小间隙时，下牙整组上移至首次接触，最多嘴宽的 30%，缺少独立上下牙则跳过。未校准的自定义或下颌动作保留有界随唇处理。接触可先收回校准动作中的前移，再按牙弓与嘴宽的较大值取 6.5% 额度整排后移，保留牙弓及上下行程；未校准动作仍采用 2.5% 共同后移及 4% 局部后移。检查局部修正是否引入新的三角面翻折；额度不足记录穿插，不向外推 Face，不缩放牙弓，不改变 Basis | 存在对应分区时执行 | recipe | procedural_constraints.close_dental_contact / procedural_contacts.oral_face |
| 16 | 口内接触 | 按唇缘相连拓扑选择 Face 接触面，包含斜面及内翻唇面；牙齿及口腔退回面部内侧，口腔唇缘固定。取消舌头随整排牙齿最前点后退；牙齿与舌头的接触只由实际三角面交叉触发。舌头上表面避开下口腔，Basis 同样检查；接触位移上限取舌长 12% 和口宽 8% 的较小值，同次修正反复检查共用额度；超出额度报告冲突 | 存在对应分区时执行 | recipe | procedural_contacts.finish / tongue_teeth / tongue_side |
| 17 | 写入 | 表情形态键、口腔联动和最终变形曲线一起保存 | 存在对应分区时执行 | recipe | procedural_generate.generate |
| 18 | 眼部数值 | 位移采样 × 当前眼宽；Z 再乘当前眼高与参考高宽比修正；17 个 XYZ 采样保存在 JSON | 按当前曲线与分区计算 | recipe.eyes.1.upper | procedural_atoms.sampled |
| 19 | 眼部数值 | 位移采样 × 当前眼宽；Z 再乘当前眼高与参考高宽比修正；17 个 XYZ 采样保存在 JSON | 按当前曲线与分区计算 | recipe.eyes.1.lower | procedural_atoms.sampled |
| 20 | 闭合规则 | 闭合=1；下眼参与=0.372768；笑眼=1；平直=0。上缘不升、水平下缘不降且限幅；竖向眼角以转折为下降边界。笑眼上拱、なごみ平直，冲突不回退为相反曲率。 | 按当前曲线与分区计算 | recipe.eyes.1 | procedural_atoms.solve |

数值定义：JSON 中 `expressions` 的同名项。

## ウィンク右

| 顺序 | 阶段 | 计算准则 | 条件 | 数值路径 | 实现 |
| --- | --- | --- | --- | --- | --- |
| 1 | 对称策略 | 不对该表情强制镜像；保留子表情、组合或特殊动作的定义 | 生成时开启强制对称 | can_symmetrize / special / relation | procedural_symmetry |
| 2 | 表情依赖 | 引用来源=笑い；条件在模型归一化坐标及当前分区中计算，边界连续衰减；不参与强制对称 | 来源可生成且依赖无循环 | relation | expression_relations.Solver |
| 3 | 输入 | 按当前标记读取；已删除必要曲线所依赖的表情跳过 | 存在对应分区时执行 | recipe | procedural_rig.checkpoint |
| 4 | 眼部目标 | 按眼宽和眼高归一化；普通闭眼反射当前上眼缘曲率，笑闭眼保留上拱 | 存在对应分区时执行 | recipe | procedural_atoms.character_arc |
| 5 | 眼缘拟合 | 上下缘共用闭眼接缝；上缘向下、水平下缘不下降且上移上限 30%，笑眼弧顶额外 10%。闭眼内眼角允许下降，但不低于原始下眼睑横向主体，并略微上提。笑眼保持上拱，なごみ保持直线；边界冲突则跳过并说明原因 | 存在对应分区时执行 | recipe | procedural_atoms.solve |
| 6 | 皮肤求解 | 固定眼口控制点，沿 Face 邻接平滑传播 | 存在对应分区时执行 | recipe | procedural_skin.EyelidSkin.deform |
| 7 | 防破面 | 保持轮廓约束，限制局部修正，残余冲突写入报告 | 存在对应分区时执行 | recipe | procedural_constraints.finalize_skin |
| 8 | 眼部接触 | 沿用原始预设的眼层依次避让。高光、瞳孔、眼白依次执行整体深度位移，保留原始间距和形状；检查 Basis 到终点的 16 个权重。位移上限保留闭眼眼宽 24%、睁眼 35%，Basis 不变。整片睫毛向内贴合、向外避让，保留原始嵌入。未消除的接触与覆盖问题写入报告 | 存在对应分区时执行 | recipe | procedural_constraints.closed_eye_stack / procedural_lashes.lower_owned_upper_sections |
| 9 | 睫毛 | 拟合原始截面中心，沿最终 XYZ 闭眼曲线统一平移和旋转截面，保留厚度；眼尾连续延伸，不截断修正斜率。单根睫毛、双眼皮等共用最终截面变换，眉毛独立。竖向眼角平滑进入弯折区，之后执行贴脸与避让，并复查最终闭合线覆盖。まばたき下凹、笑い上拱且弧度延续到眼尾、なごみ优先水平平直；闭眼接合和下眼睑限幅更强。单根只读取已有标记 | 存在对应分区时执行 | recipe | procedural_lashes.style_band / fold_vertical_sections / finish_upper_sweep / deform / audit_closed_band |
| 10 | 风格设置 | 下眼睑参与量在可行闭合范围中选择接合位置，不改变下眼睑 30% 上移及笑眼弧顶额外 10% 的硬上限。笑眼弧度与形态保持调整曲线偏好，闭合、接触和厚度优先。组合、曲线写回沿用生成时保存的风格设置 | 存在对应分区时执行 | recipe | procedural_ui.generation_options / procedural_binding.styled_closure |
| 11 | 闭眼层次 | 下睫毛随实际下眼眶的连续位移和旋转运动。闭眼时将整条下睫毛的上下缘收在上睫毛投影内，再求解前后层次。Face 接触后复查并修正遮盖，最终悬空和覆盖不足单独报告 | 存在对应分区时执行 | recipe | procedural_lashes.follow_lower_rim / cover_lower_band / finish_closed_order |
| 12 | 眼角弯折 | 跟随下眼眶的强度随切线倾角连续增加，垂直达到 1，继续内斜仍保持 1。按原曲线弧长定位截面，避免竖向长度展开成内眼角横向拉长。普通闭眼保留内眼角跨度约束，なごみ和笑闭眼保持整条中心线的横向长度；单眼表情继承对应约束 | 存在对应分区时执行 | recipe | procedural_lashes.slope_follow_weight / finish_upper_sweep |
| 13 | 计算设备 | Windows NVIDIA CUDA 可用时，以双精度 GPU 内核求解三角面投影接触。小任务、缺少运行库、显存或调用失败时使用 CPU。两种设备共用几何规则、容差和可移动条件，报告设备、调用数与回退原因 | 存在对应分区时执行 | recipe | procedural_gpu.try_depth |
| 14 | 口腔 | 口内边界固定到实际唇缘，内部连续变形；强制镜像后重新贴合 Face 与 Mouth，避免两次表面插值产生小接缝 | 存在对应分区时执行 | recipe | procedural_cavity.deform |
| 15 | 牙齿 | 内置口型按 Original 张口时牙片的一致运动校准上下排，再按嘴宽适配各自位移与旋转，不重复叠加竖向随唇浮动。原参考静止的牙齿保持原位；目标有小间隙时，下牙整组上移至首次接触，最多嘴宽的 30%，缺少独立上下牙则跳过。未校准的自定义或下颌动作保留有界随唇处理。接触可先收回校准动作中的前移，再按牙弓与嘴宽的较大值取 6.5% 额度整排后移，保留牙弓及上下行程；未校准动作仍采用 2.5% 共同后移及 4% 局部后移。检查局部修正是否引入新的三角面翻折；额度不足记录穿插，不向外推 Face，不缩放牙弓，不改变 Basis | 存在对应分区时执行 | recipe | procedural_constraints.close_dental_contact / procedural_contacts.oral_face |
| 16 | 口内接触 | 按唇缘相连拓扑选择 Face 接触面，包含斜面及内翻唇面；牙齿及口腔退回面部内侧，口腔唇缘固定。取消舌头随整排牙齿最前点后退；牙齿与舌头的接触只由实际三角面交叉触发。舌头上表面避开下口腔，Basis 同样检查；接触位移上限取舌长 12% 和口宽 8% 的较小值，同次修正反复检查共用额度；超出额度报告冲突 | 存在对应分区时执行 | recipe | procedural_contacts.finish / tongue_teeth / tongue_side |
| 17 | 写入 | 表情形态键、口腔联动和最终变形曲线一起保存 | 存在对应分区时执行 | recipe | procedural_generate.generate |
| 18 | 眼部数值 | 位移采样 × 当前眼宽；Z 再乘当前眼高与参考高宽比修正；17 个 XYZ 采样保存在 JSON | 按当前曲线与分区计算 | recipe.eyes.-1.upper | procedural_atoms.sampled |
| 19 | 眼部数值 | 位移采样 × 当前眼宽；Z 再乘当前眼高与参考高宽比修正；17 个 XYZ 采样保存在 JSON | 按当前曲线与分区计算 | recipe.eyes.-1.lower | procedural_atoms.sampled |
| 20 | 闭合规则 | 闭合=1；下眼参与=0.372763；笑眼=1；平直=0。上缘不升、水平下缘不降且限幅；竖向眼角以转折为下降边界。笑眼上拱、なごみ平直，冲突不回退为相反曲率。 | 按当前曲线与分区计算 | recipe.eyes.-1 | procedural_atoms.solve |

数值定义：JSON 中 `expressions` 的同名项。

## ウィンク２

| 顺序 | 阶段 | 计算准则 | 条件 | 数值路径 | 实现 |
| --- | --- | --- | --- | --- | --- |
| 1 | 对称策略 | 不对该表情强制镜像；保留子表情、组合或特殊动作的定义 | 生成时开启强制对称 | can_symmetrize / special / relation | procedural_symmetry |
| 2 | 表情依赖 | 引用来源=まばたき；条件在模型归一化坐标及当前分区中计算，边界连续衰减；不参与强制对称 | 来源可生成且依赖无循环 | relation | expression_relations.Solver |
| 3 | 输入 | 按当前标记读取；已删除必要曲线所依赖的表情跳过 | 存在对应分区时执行 | recipe | procedural_rig.checkpoint |
| 4 | 眼部目标 | 按眼宽和眼高归一化；普通闭眼反射当前上眼缘曲率，笑闭眼保留上拱 | 存在对应分区时执行 | recipe | procedural_atoms.character_arc |
| 5 | 眼缘拟合 | 上下缘共用闭眼接缝；上缘向下、水平下缘不下降且上移上限 30%，笑眼弧顶额外 10%。闭眼内眼角允许下降，但不低于原始下眼睑横向主体，并略微上提。笑眼保持上拱，なごみ保持直线；边界冲突则跳过并说明原因 | 存在对应分区时执行 | recipe | procedural_atoms.solve |
| 6 | 皮肤求解 | 固定眼口控制点，沿 Face 邻接平滑传播 | 存在对应分区时执行 | recipe | procedural_skin.EyelidSkin.deform |
| 7 | 防破面 | 保持轮廓约束，限制局部修正，残余冲突写入报告 | 存在对应分区时执行 | recipe | procedural_constraints.finalize_skin |
| 8 | 眼部接触 | 沿用原始预设的眼层依次避让。高光、瞳孔、眼白依次执行整体深度位移，保留原始间距和形状；检查 Basis 到终点的 16 个权重。位移上限保留闭眼眼宽 24%、睁眼 35%，Basis 不变。整片睫毛向内贴合、向外避让，保留原始嵌入。未消除的接触与覆盖问题写入报告 | 存在对应分区时执行 | recipe | procedural_constraints.closed_eye_stack / procedural_lashes.lower_owned_upper_sections |
| 9 | 睫毛 | 拟合原始截面中心，沿最终 XYZ 闭眼曲线统一平移和旋转截面，保留厚度；眼尾连续延伸，不截断修正斜率。单根睫毛、双眼皮等共用最终截面变换，眉毛独立。竖向眼角平滑进入弯折区，之后执行贴脸与避让，并复查最终闭合线覆盖。まばたき下凹、笑い上拱且弧度延续到眼尾、なごみ优先水平平直；闭眼接合和下眼睑限幅更强。单根只读取已有标记 | 存在对应分区时执行 | recipe | procedural_lashes.style_band / fold_vertical_sections / finish_upper_sweep / deform / audit_closed_band |
| 10 | 风格设置 | 下眼睑参与量在可行闭合范围中选择接合位置，不改变下眼睑 30% 上移及笑眼弧顶额外 10% 的硬上限。笑眼弧度与形态保持调整曲线偏好，闭合、接触和厚度优先。组合、曲线写回沿用生成时保存的风格设置 | 存在对应分区时执行 | recipe | procedural_ui.generation_options / procedural_binding.styled_closure |
| 11 | 闭眼层次 | 下睫毛随实际下眼眶的连续位移和旋转运动。闭眼时将整条下睫毛的上下缘收在上睫毛投影内，再求解前后层次。Face 接触后复查并修正遮盖，最终悬空和覆盖不足单独报告 | 存在对应分区时执行 | recipe | procedural_lashes.follow_lower_rim / cover_lower_band / finish_closed_order |
| 12 | 眼角弯折 | 跟随下眼眶的强度随切线倾角连续增加，垂直达到 1，继续内斜仍保持 1。按原曲线弧长定位截面，避免竖向长度展开成内眼角横向拉长。普通闭眼保留内眼角跨度约束，なごみ和笑闭眼保持整条中心线的横向长度；单眼表情继承对应约束 | 存在对应分区时执行 | recipe | procedural_lashes.slope_follow_weight / finish_upper_sweep |
| 13 | 计算设备 | Windows NVIDIA CUDA 可用时，以双精度 GPU 内核求解三角面投影接触。小任务、缺少运行库、显存或调用失败时使用 CPU。两种设备共用几何规则、容差和可移动条件，报告设备、调用数与回退原因 | 存在对应分区时执行 | recipe | procedural_gpu.try_depth |
| 14 | 口腔 | 口内边界固定到实际唇缘，内部连续变形；强制镜像后重新贴合 Face 与 Mouth，避免两次表面插值产生小接缝 | 存在对应分区时执行 | recipe | procedural_cavity.deform |
| 15 | 牙齿 | 内置口型按 Original 张口时牙片的一致运动校准上下排，再按嘴宽适配各自位移与旋转，不重复叠加竖向随唇浮动。原参考静止的牙齿保持原位；目标有小间隙时，下牙整组上移至首次接触，最多嘴宽的 30%，缺少独立上下牙则跳过。未校准的自定义或下颌动作保留有界随唇处理。接触可先收回校准动作中的前移，再按牙弓与嘴宽的较大值取 6.5% 额度整排后移，保留牙弓及上下行程；未校准动作仍采用 2.5% 共同后移及 4% 局部后移。检查局部修正是否引入新的三角面翻折；额度不足记录穿插，不向外推 Face，不缩放牙弓，不改变 Basis | 存在对应分区时执行 | recipe | procedural_constraints.close_dental_contact / procedural_contacts.oral_face |
| 16 | 口内接触 | 按唇缘相连拓扑选择 Face 接触面，包含斜面及内翻唇面；牙齿及口腔退回面部内侧，口腔唇缘固定。取消舌头随整排牙齿最前点后退；牙齿与舌头的接触只由实际三角面交叉触发。舌头上表面避开下口腔，Basis 同样检查；接触位移上限取舌长 12% 和口宽 8% 的较小值，同次修正反复检查共用额度；超出额度报告冲突 | 存在对应分区时执行 | recipe | procedural_contacts.finish / tongue_teeth / tongue_side |
| 17 | 写入 | 表情形态键、口腔联动和最终变形曲线一起保存 | 存在对应分区时执行 | recipe | procedural_generate.generate |
| 18 | 眼部数值 | 位移采样 × 当前眼宽；Z 再乘当前眼高与参考高宽比修正；17 个 XYZ 采样保存在 JSON | 按当前曲线与分区计算 | recipe.eyes.1.upper | procedural_atoms.sampled |
| 19 | 眼部数值 | 位移采样 × 当前眼宽；Z 再乘当前眼高与参考高宽比修正；17 个 XYZ 采样保存在 JSON | 按当前曲线与分区计算 | recipe.eyes.1.lower | procedural_atoms.sampled |
| 20 | 闭合规则 | 闭合=1；下眼参与=0.237818；笑眼=0；平直=0。上缘不升、水平下缘不降且限幅；竖向眼角以转折为下降边界。笑眼上拱、なごみ平直，冲突不回退为相反曲率。 | 按当前曲线与分区计算 | recipe.eyes.1 | procedural_atoms.solve |

数值定义：JSON 中 `expressions` 的同名项。

## ウィンク２右

| 顺序 | 阶段 | 计算准则 | 条件 | 数值路径 | 实现 |
| --- | --- | --- | --- | --- | --- |
| 1 | 对称策略 | 不对该表情强制镜像；保留子表情、组合或特殊动作的定义 | 生成时开启强制对称 | can_symmetrize / special / relation | procedural_symmetry |
| 2 | 表情依赖 | 引用来源=まばたき；条件在模型归一化坐标及当前分区中计算，边界连续衰减；不参与强制对称 | 来源可生成且依赖无循环 | relation | expression_relations.Solver |
| 3 | 输入 | 按当前标记读取；已删除必要曲线所依赖的表情跳过 | 存在对应分区时执行 | recipe | procedural_rig.checkpoint |
| 4 | 眼部目标 | 按眼宽和眼高归一化；普通闭眼反射当前上眼缘曲率，笑闭眼保留上拱 | 存在对应分区时执行 | recipe | procedural_atoms.character_arc |
| 5 | 眼缘拟合 | 上下缘共用闭眼接缝；上缘向下、水平下缘不下降且上移上限 30%，笑眼弧顶额外 10%。闭眼内眼角允许下降，但不低于原始下眼睑横向主体，并略微上提。笑眼保持上拱，なごみ保持直线；边界冲突则跳过并说明原因 | 存在对应分区时执行 | recipe | procedural_atoms.solve |
| 6 | 皮肤求解 | 固定眼口控制点，沿 Face 邻接平滑传播 | 存在对应分区时执行 | recipe | procedural_skin.EyelidSkin.deform |
| 7 | 防破面 | 保持轮廓约束，限制局部修正，残余冲突写入报告 | 存在对应分区时执行 | recipe | procedural_constraints.finalize_skin |
| 8 | 眼部接触 | 沿用原始预设的眼层依次避让。高光、瞳孔、眼白依次执行整体深度位移，保留原始间距和形状；检查 Basis 到终点的 16 个权重。位移上限保留闭眼眼宽 24%、睁眼 35%，Basis 不变。整片睫毛向内贴合、向外避让，保留原始嵌入。未消除的接触与覆盖问题写入报告 | 存在对应分区时执行 | recipe | procedural_constraints.closed_eye_stack / procedural_lashes.lower_owned_upper_sections |
| 9 | 睫毛 | 拟合原始截面中心，沿最终 XYZ 闭眼曲线统一平移和旋转截面，保留厚度；眼尾连续延伸，不截断修正斜率。单根睫毛、双眼皮等共用最终截面变换，眉毛独立。竖向眼角平滑进入弯折区，之后执行贴脸与避让，并复查最终闭合线覆盖。まばたき下凹、笑い上拱且弧度延续到眼尾、なごみ优先水平平直；闭眼接合和下眼睑限幅更强。单根只读取已有标记 | 存在对应分区时执行 | recipe | procedural_lashes.style_band / fold_vertical_sections / finish_upper_sweep / deform / audit_closed_band |
| 10 | 风格设置 | 下眼睑参与量在可行闭合范围中选择接合位置，不改变下眼睑 30% 上移及笑眼弧顶额外 10% 的硬上限。笑眼弧度与形态保持调整曲线偏好，闭合、接触和厚度优先。组合、曲线写回沿用生成时保存的风格设置 | 存在对应分区时执行 | recipe | procedural_ui.generation_options / procedural_binding.styled_closure |
| 11 | 闭眼层次 | 下睫毛随实际下眼眶的连续位移和旋转运动。闭眼时将整条下睫毛的上下缘收在上睫毛投影内，再求解前后层次。Face 接触后复查并修正遮盖，最终悬空和覆盖不足单独报告 | 存在对应分区时执行 | recipe | procedural_lashes.follow_lower_rim / cover_lower_band / finish_closed_order |
| 12 | 眼角弯折 | 跟随下眼眶的强度随切线倾角连续增加，垂直达到 1，继续内斜仍保持 1。按原曲线弧长定位截面，避免竖向长度展开成内眼角横向拉长。普通闭眼保留内眼角跨度约束，なごみ和笑闭眼保持整条中心线的横向长度；单眼表情继承对应约束 | 存在对应分区时执行 | recipe | procedural_lashes.slope_follow_weight / finish_upper_sweep |
| 13 | 计算设备 | Windows NVIDIA CUDA 可用时，以双精度 GPU 内核求解三角面投影接触。小任务、缺少运行库、显存或调用失败时使用 CPU。两种设备共用几何规则、容差和可移动条件，报告设备、调用数与回退原因 | 存在对应分区时执行 | recipe | procedural_gpu.try_depth |
| 14 | 口腔 | 口内边界固定到实际唇缘，内部连续变形；强制镜像后重新贴合 Face 与 Mouth，避免两次表面插值产生小接缝 | 存在对应分区时执行 | recipe | procedural_cavity.deform |
| 15 | 牙齿 | 内置口型按 Original 张口时牙片的一致运动校准上下排，再按嘴宽适配各自位移与旋转，不重复叠加竖向随唇浮动。原参考静止的牙齿保持原位；目标有小间隙时，下牙整组上移至首次接触，最多嘴宽的 30%，缺少独立上下牙则跳过。未校准的自定义或下颌动作保留有界随唇处理。接触可先收回校准动作中的前移，再按牙弓与嘴宽的较大值取 6.5% 额度整排后移，保留牙弓及上下行程；未校准动作仍采用 2.5% 共同后移及 4% 局部后移。检查局部修正是否引入新的三角面翻折；额度不足记录穿插，不向外推 Face，不缩放牙弓，不改变 Basis | 存在对应分区时执行 | recipe | procedural_constraints.close_dental_contact / procedural_contacts.oral_face |
| 16 | 口内接触 | 按唇缘相连拓扑选择 Face 接触面，包含斜面及内翻唇面；牙齿及口腔退回面部内侧，口腔唇缘固定。取消舌头随整排牙齿最前点后退；牙齿与舌头的接触只由实际三角面交叉触发。舌头上表面避开下口腔，Basis 同样检查；接触位移上限取舌长 12% 和口宽 8% 的较小值，同次修正反复检查共用额度；超出额度报告冲突 | 存在对应分区时执行 | recipe | procedural_contacts.finish / tongue_teeth / tongue_side |
| 17 | 写入 | 表情形态键、口腔联动和最终变形曲线一起保存 | 存在对应分区时执行 | recipe | procedural_generate.generate |
| 18 | 眼部数值 | 位移采样 × 当前眼宽；Z 再乘当前眼高与参考高宽比修正；17 个 XYZ 采样保存在 JSON | 按当前曲线与分区计算 | recipe.eyes.-1.upper | procedural_atoms.sampled |
| 19 | 眼部数值 | 位移采样 × 当前眼宽；Z 再乘当前眼高与参考高宽比修正；17 个 XYZ 采样保存在 JSON | 按当前曲线与分区计算 | recipe.eyes.-1.lower | procedural_atoms.sampled |
| 20 | 闭合规则 | 闭合=1；下眼参与=0.237818；笑眼=0；平直=0。上缘不升、水平下缘不降且限幅；竖向眼角以转折为下降边界。笑眼上拱、なごみ平直，冲突不回退为相反曲率。 | 按当前曲线与分区计算 | recipe.eyes.-1 | procedural_atoms.solve |

数值定义：JSON 中 `expressions` 的同名项。

## なごみ

| 顺序 | 阶段 | 计算准则 | 条件 | 数值路径 | 实现 |
| --- | --- | --- | --- | --- | --- |
| 1 | 对称策略 | 允许强制左右对称；正侧完成约束后直接镜像最终坐标到负侧，不再两侧平均。独立眼眉在相关顶点可配对时只计算正侧，不要求三角面划分相同。跨中线口型保留整体求解；活动顶点无法配对则跳过。镜像后的翻折数量写入报告 | 生成时开启强制对称 | can_symmetrize / special / relation | procedural_symmetry |
| 2 | 输入 | 按当前标记读取；已删除必要曲线所依赖的表情跳过 | 存在对应分区时执行 | recipe | procedural_rig.checkpoint |
| 3 | 眼部目标 | 按眼宽和眼高归一化；普通闭眼反射当前上眼缘曲率，笑闭眼保留上拱 | 存在对应分区时执行 | recipe | procedural_atoms.character_arc |
| 4 | 眼缘拟合 | 上下缘共用闭眼接缝；上缘向下、水平下缘不下降且上移上限 30%，笑眼弧顶额外 10%。闭眼内眼角允许下降，但不低于原始下眼睑横向主体，并略微上提。笑眼保持上拱，なごみ保持直线；边界冲突则跳过并说明原因 | 存在对应分区时执行 | recipe | procedural_atoms.solve |
| 5 | 皮肤求解 | 固定眼口控制点，沿 Face 邻接平滑传播 | 存在对应分区时执行 | recipe | procedural_skin.EyelidSkin.deform |
| 6 | 防破面 | 保持轮廓约束，限制局部修正，残余冲突写入报告 | 存在对应分区时执行 | recipe | procedural_constraints.finalize_skin |
| 7 | 眼部接触 | 沿用原始预设的眼层依次避让。高光、瞳孔、眼白依次执行整体深度位移，保留原始间距和形状；检查 Basis 到终点的 16 个权重。位移上限保留闭眼眼宽 24%、睁眼 35%，Basis 不变。整片睫毛向内贴合、向外避让，保留原始嵌入。未消除的接触与覆盖问题写入报告 | 存在对应分区时执行 | recipe | procedural_constraints.closed_eye_stack / procedural_lashes.lower_owned_upper_sections |
| 8 | 睫毛 | 拟合原始截面中心，沿最终 XYZ 闭眼曲线统一平移和旋转截面，保留厚度；眼尾连续延伸，不截断修正斜率。单根睫毛、双眼皮等共用最终截面变换，眉毛独立。竖向眼角平滑进入弯折区，之后执行贴脸与避让，并复查最终闭合线覆盖。まばたき下凹、笑い上拱且弧度延续到眼尾、なごみ优先水平平直；闭眼接合和下眼睑限幅更强。单根只读取已有标记 | 存在对应分区时执行 | recipe | procedural_lashes.style_band / fold_vertical_sections / finish_upper_sweep / deform / audit_closed_band |
| 9 | 风格设置 | 下眼睑参与量在可行闭合范围中选择接合位置，不改变下眼睑 30% 上移及笑眼弧顶额外 10% 的硬上限。笑眼弧度与形态保持调整曲线偏好，闭合、接触和厚度优先。组合、曲线写回沿用生成时保存的风格设置 | 存在对应分区时执行 | recipe | procedural_ui.generation_options / procedural_binding.styled_closure |
| 10 | 闭眼层次 | 下睫毛随实际下眼眶的连续位移和旋转运动。闭眼时将整条下睫毛的上下缘收在上睫毛投影内，再求解前后层次。Face 接触后复查并修正遮盖，最终悬空和覆盖不足单独报告 | 存在对应分区时执行 | recipe | procedural_lashes.follow_lower_rim / cover_lower_band / finish_closed_order |
| 11 | 眼角弯折 | 跟随下眼眶的强度随切线倾角连续增加，垂直达到 1，继续内斜仍保持 1。按原曲线弧长定位截面，避免竖向长度展开成内眼角横向拉长。普通闭眼保留内眼角跨度约束，なごみ和笑闭眼保持整条中心线的横向长度；单眼表情继承对应约束 | 存在对应分区时执行 | recipe | procedural_lashes.slope_follow_weight / finish_upper_sweep |
| 12 | 计算设备 | Windows NVIDIA CUDA 可用时，以双精度 GPU 内核求解三角面投影接触。小任务、缺少运行库、显存或调用失败时使用 CPU。两种设备共用几何规则、容差和可移动条件，报告设备、调用数与回退原因 | 存在对应分区时执行 | recipe | procedural_gpu.try_depth |
| 13 | 口腔 | 口内边界固定到实际唇缘，内部连续变形；强制镜像后重新贴合 Face 与 Mouth，避免两次表面插值产生小接缝 | 存在对应分区时执行 | recipe | procedural_cavity.deform |
| 14 | 牙齿 | 内置口型按 Original 张口时牙片的一致运动校准上下排，再按嘴宽适配各自位移与旋转，不重复叠加竖向随唇浮动。原参考静止的牙齿保持原位；目标有小间隙时，下牙整组上移至首次接触，最多嘴宽的 30%，缺少独立上下牙则跳过。未校准的自定义或下颌动作保留有界随唇处理。接触可先收回校准动作中的前移，再按牙弓与嘴宽的较大值取 6.5% 额度整排后移，保留牙弓及上下行程；未校准动作仍采用 2.5% 共同后移及 4% 局部后移。检查局部修正是否引入新的三角面翻折；额度不足记录穿插，不向外推 Face，不缩放牙弓，不改变 Basis | 存在对应分区时执行 | recipe | procedural_constraints.close_dental_contact / procedural_contacts.oral_face |
| 15 | 口内接触 | 按唇缘相连拓扑选择 Face 接触面，包含斜面及内翻唇面；牙齿及口腔退回面部内侧，口腔唇缘固定。取消舌头随整排牙齿最前点后退；牙齿与舌头的接触只由实际三角面交叉触发。舌头上表面避开下口腔，Basis 同样检查；接触位移上限取舌长 12% 和口宽 8% 的较小值，同次修正反复检查共用额度；超出额度报告冲突 | 存在对应分区时执行 | recipe | procedural_contacts.finish / tongue_teeth / tongue_side |
| 16 | 写入 | 表情形态键、口腔联动和最终变形曲线一起保存 | 存在对应分区时执行 | recipe | procedural_generate.generate |
| 17 | 眼部数值 | 位移采样 × 当前眼宽；Z 再乘当前眼高与参考高宽比修正；17 个 XYZ 采样保存在 JSON | 按当前曲线与分区计算 | recipe.eyes.-1.upper | procedural_atoms.sampled |
| 18 | 眼部数值 | 位移采样 × 当前眼宽；Z 再乘当前眼高与参考高宽比修正；17 个 XYZ 采样保存在 JSON | 按当前曲线与分区计算 | recipe.eyes.-1.lower | procedural_atoms.sampled |
| 19 | 闭合规则 | 闭合=1；下眼参与=0.247925；笑眼=0；平直=1。上缘不升、水平下缘不降且限幅；竖向眼角以转折为下降边界。笑眼上拱、なごみ平直，冲突不回退为相反曲率。 | 按当前曲线与分区计算 | recipe.eyes.-1 | procedural_atoms.solve |
| 20 | 眼部数值 | 位移采样 × 当前眼宽；Z 再乘当前眼高与参考高宽比修正；17 个 XYZ 采样保存在 JSON | 按当前曲线与分区计算 | recipe.eyes.1.upper | procedural_atoms.sampled |
| 21 | 眼部数值 | 位移采样 × 当前眼宽；Z 再乘当前眼高与参考高宽比修正；17 个 XYZ 采样保存在 JSON | 按当前曲线与分区计算 | recipe.eyes.1.lower | procedural_atoms.sampled |
| 22 | 闭合规则 | 闭合=1；下眼参与=0.247924；笑眼=0；平直=1。上缘不升、水平下缘不降且限幅；竖向眼角以转折为下降边界。笑眼上拱、なごみ平直，冲突不回退为相反曲率。 | 按当前曲线与分区计算 | recipe.eyes.1 | procedural_atoms.solve |

数值定义：JSON 中 `expressions` 的同名项。

## なごみ左

| 顺序 | 阶段 | 计算准则 | 条件 | 数值路径 | 实现 |
| --- | --- | --- | --- | --- | --- |
| 1 | 对称策略 | 不对该表情强制镜像；保留子表情、组合或特殊动作的定义 | 生成时开启强制对称 | can_symmetrize / special / relation | procedural_symmetry |
| 2 | 表情依赖 | 引用来源=なごみ；条件在模型归一化坐标及当前分区中计算，边界连续衰减；不参与强制对称 | 来源可生成且依赖无循环 | relation | expression_relations.Solver |
| 3 | 输入 | 按当前标记读取；已删除必要曲线所依赖的表情跳过 | 存在对应分区时执行 | recipe | procedural_rig.checkpoint |
| 4 | 眼部目标 | 按眼宽和眼高归一化；普通闭眼反射当前上眼缘曲率，笑闭眼保留上拱 | 存在对应分区时执行 | recipe | procedural_atoms.character_arc |
| 5 | 眼缘拟合 | 上下缘共用闭眼接缝；上缘向下、水平下缘不下降且上移上限 30%，笑眼弧顶额外 10%。闭眼内眼角允许下降，但不低于原始下眼睑横向主体，并略微上提。笑眼保持上拱，なごみ保持直线；边界冲突则跳过并说明原因 | 存在对应分区时执行 | recipe | procedural_atoms.solve |
| 6 | 皮肤求解 | 固定眼口控制点，沿 Face 邻接平滑传播 | 存在对应分区时执行 | recipe | procedural_skin.EyelidSkin.deform |
| 7 | 防破面 | 保持轮廓约束，限制局部修正，残余冲突写入报告 | 存在对应分区时执行 | recipe | procedural_constraints.finalize_skin |
| 8 | 眼部接触 | 沿用原始预设的眼层依次避让。高光、瞳孔、眼白依次执行整体深度位移，保留原始间距和形状；检查 Basis 到终点的 16 个权重。位移上限保留闭眼眼宽 24%、睁眼 35%，Basis 不变。整片睫毛向内贴合、向外避让，保留原始嵌入。未消除的接触与覆盖问题写入报告 | 存在对应分区时执行 | recipe | procedural_constraints.closed_eye_stack / procedural_lashes.lower_owned_upper_sections |
| 9 | 睫毛 | 拟合原始截面中心，沿最终 XYZ 闭眼曲线统一平移和旋转截面，保留厚度；眼尾连续延伸，不截断修正斜率。单根睫毛、双眼皮等共用最终截面变换，眉毛独立。竖向眼角平滑进入弯折区，之后执行贴脸与避让，并复查最终闭合线覆盖。まばたき下凹、笑い上拱且弧度延续到眼尾、なごみ优先水平平直；闭眼接合和下眼睑限幅更强。单根只读取已有标记 | 存在对应分区时执行 | recipe | procedural_lashes.style_band / fold_vertical_sections / finish_upper_sweep / deform / audit_closed_band |
| 10 | 风格设置 | 下眼睑参与量在可行闭合范围中选择接合位置，不改变下眼睑 30% 上移及笑眼弧顶额外 10% 的硬上限。笑眼弧度与形态保持调整曲线偏好，闭合、接触和厚度优先。组合、曲线写回沿用生成时保存的风格设置 | 存在对应分区时执行 | recipe | procedural_ui.generation_options / procedural_binding.styled_closure |
| 11 | 闭眼层次 | 下睫毛随实际下眼眶的连续位移和旋转运动。闭眼时将整条下睫毛的上下缘收在上睫毛投影内，再求解前后层次。Face 接触后复查并修正遮盖，最终悬空和覆盖不足单独报告 | 存在对应分区时执行 | recipe | procedural_lashes.follow_lower_rim / cover_lower_band / finish_closed_order |
| 12 | 眼角弯折 | 跟随下眼眶的强度随切线倾角连续增加，垂直达到 1，继续内斜仍保持 1。按原曲线弧长定位截面，避免竖向长度展开成内眼角横向拉长。普通闭眼保留内眼角跨度约束，なごみ和笑闭眼保持整条中心线的横向长度；单眼表情继承对应约束 | 存在对应分区时执行 | recipe | procedural_lashes.slope_follow_weight / finish_upper_sweep |
| 13 | 计算设备 | Windows NVIDIA CUDA 可用时，以双精度 GPU 内核求解三角面投影接触。小任务、缺少运行库、显存或调用失败时使用 CPU。两种设备共用几何规则、容差和可移动条件，报告设备、调用数与回退原因 | 存在对应分区时执行 | recipe | procedural_gpu.try_depth |
| 14 | 口腔 | 口内边界固定到实际唇缘，内部连续变形；强制镜像后重新贴合 Face 与 Mouth，避免两次表面插值产生小接缝 | 存在对应分区时执行 | recipe | procedural_cavity.deform |
| 15 | 牙齿 | 内置口型按 Original 张口时牙片的一致运动校准上下排，再按嘴宽适配各自位移与旋转，不重复叠加竖向随唇浮动。原参考静止的牙齿保持原位；目标有小间隙时，下牙整组上移至首次接触，最多嘴宽的 30%，缺少独立上下牙则跳过。未校准的自定义或下颌动作保留有界随唇处理。接触可先收回校准动作中的前移，再按牙弓与嘴宽的较大值取 6.5% 额度整排后移，保留牙弓及上下行程；未校准动作仍采用 2.5% 共同后移及 4% 局部后移。检查局部修正是否引入新的三角面翻折；额度不足记录穿插，不向外推 Face，不缩放牙弓，不改变 Basis | 存在对应分区时执行 | recipe | procedural_constraints.close_dental_contact / procedural_contacts.oral_face |
| 16 | 口内接触 | 按唇缘相连拓扑选择 Face 接触面，包含斜面及内翻唇面；牙齿及口腔退回面部内侧，口腔唇缘固定。取消舌头随整排牙齿最前点后退；牙齿与舌头的接触只由实际三角面交叉触发。舌头上表面避开下口腔，Basis 同样检查；接触位移上限取舌长 12% 和口宽 8% 的较小值，同次修正反复检查共用额度；超出额度报告冲突 | 存在对应分区时执行 | recipe | procedural_contacts.finish / tongue_teeth / tongue_side |
| 17 | 写入 | 表情形态键、口腔联动和最终变形曲线一起保存 | 存在对应分区时执行 | recipe | procedural_generate.generate |
| 18 | 眼部数值 | 位移采样 × 当前眼宽；Z 再乘当前眼高与参考高宽比修正；17 个 XYZ 采样保存在 JSON | 按当前曲线与分区计算 | recipe.eyes.1.upper | procedural_atoms.sampled |
| 19 | 眼部数值 | 位移采样 × 当前眼宽；Z 再乘当前眼高与参考高宽比修正；17 个 XYZ 采样保存在 JSON | 按当前曲线与分区计算 | recipe.eyes.1.lower | procedural_atoms.sampled |
| 20 | 闭合规则 | 闭合=1；下眼参与=0.247924；笑眼=0；平直=1。上缘不升、水平下缘不降且限幅；竖向眼角以转折为下降边界。笑眼上拱、なごみ平直，冲突不回退为相反曲率。 | 按当前曲线与分区计算 | recipe.eyes.1 | procedural_atoms.solve |

数值定义：JSON 中 `expressions` 的同名项。

## なごみ右

| 顺序 | 阶段 | 计算准则 | 条件 | 数值路径 | 实现 |
| --- | --- | --- | --- | --- | --- |
| 1 | 对称策略 | 不对该表情强制镜像；保留子表情、组合或特殊动作的定义 | 生成时开启强制对称 | can_symmetrize / special / relation | procedural_symmetry |
| 2 | 表情依赖 | 引用来源=なごみ；条件在模型归一化坐标及当前分区中计算，边界连续衰减；不参与强制对称 | 来源可生成且依赖无循环 | relation | expression_relations.Solver |
| 3 | 输入 | 按当前标记读取；已删除必要曲线所依赖的表情跳过 | 存在对应分区时执行 | recipe | procedural_rig.checkpoint |
| 4 | 眼部目标 | 按眼宽和眼高归一化；普通闭眼反射当前上眼缘曲率，笑闭眼保留上拱 | 存在对应分区时执行 | recipe | procedural_atoms.character_arc |
| 5 | 眼缘拟合 | 上下缘共用闭眼接缝；上缘向下、水平下缘不下降且上移上限 30%，笑眼弧顶额外 10%。闭眼内眼角允许下降，但不低于原始下眼睑横向主体，并略微上提。笑眼保持上拱，なごみ保持直线；边界冲突则跳过并说明原因 | 存在对应分区时执行 | recipe | procedural_atoms.solve |
| 6 | 皮肤求解 | 固定眼口控制点，沿 Face 邻接平滑传播 | 存在对应分区时执行 | recipe | procedural_skin.EyelidSkin.deform |
| 7 | 防破面 | 保持轮廓约束，限制局部修正，残余冲突写入报告 | 存在对应分区时执行 | recipe | procedural_constraints.finalize_skin |
| 8 | 眼部接触 | 沿用原始预设的眼层依次避让。高光、瞳孔、眼白依次执行整体深度位移，保留原始间距和形状；检查 Basis 到终点的 16 个权重。位移上限保留闭眼眼宽 24%、睁眼 35%，Basis 不变。整片睫毛向内贴合、向外避让，保留原始嵌入。未消除的接触与覆盖问题写入报告 | 存在对应分区时执行 | recipe | procedural_constraints.closed_eye_stack / procedural_lashes.lower_owned_upper_sections |
| 9 | 睫毛 | 拟合原始截面中心，沿最终 XYZ 闭眼曲线统一平移和旋转截面，保留厚度；眼尾连续延伸，不截断修正斜率。单根睫毛、双眼皮等共用最终截面变换，眉毛独立。竖向眼角平滑进入弯折区，之后执行贴脸与避让，并复查最终闭合线覆盖。まばたき下凹、笑い上拱且弧度延续到眼尾、なごみ优先水平平直；闭眼接合和下眼睑限幅更强。单根只读取已有标记 | 存在对应分区时执行 | recipe | procedural_lashes.style_band / fold_vertical_sections / finish_upper_sweep / deform / audit_closed_band |
| 10 | 风格设置 | 下眼睑参与量在可行闭合范围中选择接合位置，不改变下眼睑 30% 上移及笑眼弧顶额外 10% 的硬上限。笑眼弧度与形态保持调整曲线偏好，闭合、接触和厚度优先。组合、曲线写回沿用生成时保存的风格设置 | 存在对应分区时执行 | recipe | procedural_ui.generation_options / procedural_binding.styled_closure |
| 11 | 闭眼层次 | 下睫毛随实际下眼眶的连续位移和旋转运动。闭眼时将整条下睫毛的上下缘收在上睫毛投影内，再求解前后层次。Face 接触后复查并修正遮盖，最终悬空和覆盖不足单独报告 | 存在对应分区时执行 | recipe | procedural_lashes.follow_lower_rim / cover_lower_band / finish_closed_order |
| 12 | 眼角弯折 | 跟随下眼眶的强度随切线倾角连续增加，垂直达到 1，继续内斜仍保持 1。按原曲线弧长定位截面，避免竖向长度展开成内眼角横向拉长。普通闭眼保留内眼角跨度约束，なごみ和笑闭眼保持整条中心线的横向长度；单眼表情继承对应约束 | 存在对应分区时执行 | recipe | procedural_lashes.slope_follow_weight / finish_upper_sweep |
| 13 | 计算设备 | Windows NVIDIA CUDA 可用时，以双精度 GPU 内核求解三角面投影接触。小任务、缺少运行库、显存或调用失败时使用 CPU。两种设备共用几何规则、容差和可移动条件，报告设备、调用数与回退原因 | 存在对应分区时执行 | recipe | procedural_gpu.try_depth |
| 14 | 口腔 | 口内边界固定到实际唇缘，内部连续变形；强制镜像后重新贴合 Face 与 Mouth，避免两次表面插值产生小接缝 | 存在对应分区时执行 | recipe | procedural_cavity.deform |
| 15 | 牙齿 | 内置口型按 Original 张口时牙片的一致运动校准上下排，再按嘴宽适配各自位移与旋转，不重复叠加竖向随唇浮动。原参考静止的牙齿保持原位；目标有小间隙时，下牙整组上移至首次接触，最多嘴宽的 30%，缺少独立上下牙则跳过。未校准的自定义或下颌动作保留有界随唇处理。接触可先收回校准动作中的前移，再按牙弓与嘴宽的较大值取 6.5% 额度整排后移，保留牙弓及上下行程；未校准动作仍采用 2.5% 共同后移及 4% 局部后移。检查局部修正是否引入新的三角面翻折；额度不足记录穿插，不向外推 Face，不缩放牙弓，不改变 Basis | 存在对应分区时执行 | recipe | procedural_constraints.close_dental_contact / procedural_contacts.oral_face |
| 16 | 口内接触 | 按唇缘相连拓扑选择 Face 接触面，包含斜面及内翻唇面；牙齿及口腔退回面部内侧，口腔唇缘固定。取消舌头随整排牙齿最前点后退；牙齿与舌头的接触只由实际三角面交叉触发。舌头上表面避开下口腔，Basis 同样检查；接触位移上限取舌长 12% 和口宽 8% 的较小值，同次修正反复检查共用额度；超出额度报告冲突 | 存在对应分区时执行 | recipe | procedural_contacts.finish / tongue_teeth / tongue_side |
| 17 | 写入 | 表情形态键、口腔联动和最终变形曲线一起保存 | 存在对应分区时执行 | recipe | procedural_generate.generate |
| 18 | 眼部数值 | 位移采样 × 当前眼宽；Z 再乘当前眼高与参考高宽比修正；17 个 XYZ 采样保存在 JSON | 按当前曲线与分区计算 | recipe.eyes.-1.upper | procedural_atoms.sampled |
| 19 | 眼部数值 | 位移采样 × 当前眼宽；Z 再乘当前眼高与参考高宽比修正；17 个 XYZ 采样保存在 JSON | 按当前曲线与分区计算 | recipe.eyes.-1.lower | procedural_atoms.sampled |
| 20 | 闭合规则 | 闭合=1；下眼参与=0.247925；笑眼=0；平直=1。上缘不升、水平下缘不降且限幅；竖向眼角以转折为下降边界。笑眼上拱、なごみ平直，冲突不回退为相反曲率。 | 按当前曲线与分区计算 | recipe.eyes.-1 | procedural_atoms.solve |

数值定义：JSON 中 `expressions` 的同名项。

## びっくり

| 顺序 | 阶段 | 计算准则 | 条件 | 数值路径 | 实现 |
| --- | --- | --- | --- | --- | --- |
| 1 | 对称策略 | 允许强制左右对称；正侧完成约束后直接镜像最终坐标到负侧，不再两侧平均。独立眼眉在相关顶点可配对时只计算正侧，不要求三角面划分相同。跨中线口型保留整体求解；活动顶点无法配对则跳过。镜像后的翻折数量写入报告 | 生成时开启强制对称 | can_symmetrize / special / relation | procedural_symmetry |
| 2 | 输入 | 按当前标记读取；已删除必要曲线所依赖的表情跳过 | 存在对应分区时执行 | recipe | procedural_rig.checkpoint |
| 3 | 眼部目标 | 按眼宽和眼高归一化；普通闭眼反射当前上眼缘曲率，笑闭眼保留上拱 | 存在对应分区时执行 | recipe | procedural_atoms.character_arc |
| 4 | 眼缘拟合 | 上下缘共用闭眼接缝；上缘向下、水平下缘不下降且上移上限 30%，笑眼弧顶额外 10%。闭眼内眼角允许下降，但不低于原始下眼睑横向主体，并略微上提。笑眼保持上拱，なごみ保持直线；边界冲突则跳过并说明原因 | 存在对应分区时执行 | recipe | procedural_atoms.solve |
| 5 | 皮肤求解 | 固定眼口控制点，沿 Face 邻接平滑传播 | 存在对应分区时执行 | recipe | procedural_skin.EyelidSkin.deform |
| 6 | 防破面 | 保持轮廓约束，限制局部修正，残余冲突写入报告 | 存在对应分区时执行 | recipe | procedural_constraints.finalize_skin |
| 7 | 眼部接触 | 沿用原始预设的眼层依次避让。高光、瞳孔、眼白依次执行整体深度位移，保留原始间距和形状；检查 Basis 到终点的 16 个权重。位移上限保留闭眼眼宽 24%、睁眼 35%，Basis 不变。整片睫毛向内贴合、向外避让，保留原始嵌入。未消除的接触与覆盖问题写入报告 | 存在对应分区时执行 | recipe | procedural_constraints.closed_eye_stack / procedural_lashes.lower_owned_upper_sections |
| 8 | 睫毛 | 拟合原始截面中心，沿最终 XYZ 闭眼曲线统一平移和旋转截面，保留厚度；眼尾连续延伸，不截断修正斜率。单根睫毛、双眼皮等共用最终截面变换，眉毛独立。竖向眼角平滑进入弯折区，之后执行贴脸与避让，并复查最终闭合线覆盖。まばたき下凹、笑い上拱且弧度延续到眼尾、なごみ优先水平平直；闭眼接合和下眼睑限幅更强。单根只读取已有标记 | 存在对应分区时执行 | recipe | procedural_lashes.style_band / fold_vertical_sections / finish_upper_sweep / deform / audit_closed_band |
| 9 | 风格设置 | 下眼睑参与量在可行闭合范围中选择接合位置，不改变下眼睑 30% 上移及笑眼弧顶额外 10% 的硬上限。笑眼弧度与形态保持调整曲线偏好，闭合、接触和厚度优先。组合、曲线写回沿用生成时保存的风格设置 | 存在对应分区时执行 | recipe | procedural_ui.generation_options / procedural_binding.styled_closure |
| 10 | 闭眼层次 | 下睫毛随实际下眼眶的连续位移和旋转运动。闭眼时将整条下睫毛的上下缘收在上睫毛投影内，再求解前后层次。Face 接触后复查并修正遮盖，最终悬空和覆盖不足单独报告 | 存在对应分区时执行 | recipe | procedural_lashes.follow_lower_rim / cover_lower_band / finish_closed_order |
| 11 | 眼角弯折 | 跟随下眼眶的强度随切线倾角连续增加，垂直达到 1，继续内斜仍保持 1。按原曲线弧长定位截面，避免竖向长度展开成内眼角横向拉长。普通闭眼保留内眼角跨度约束，なごみ和笑闭眼保持整条中心线的横向长度；单眼表情继承对应约束 | 存在对应分区时执行 | recipe | procedural_lashes.slope_follow_weight / finish_upper_sweep |
| 12 | 计算设备 | Windows NVIDIA CUDA 可用时，以双精度 GPU 内核求解三角面投影接触。小任务、缺少运行库、显存或调用失败时使用 CPU。两种设备共用几何规则、容差和可移动条件，报告设备、调用数与回退原因 | 存在对应分区时执行 | recipe | procedural_gpu.try_depth |
| 13 | 口腔 | 口内边界固定到实际唇缘，内部连续变形；强制镜像后重新贴合 Face 与 Mouth，避免两次表面插值产生小接缝 | 存在对应分区时执行 | recipe | procedural_cavity.deform |
| 14 | 牙齿 | 内置口型按 Original 张口时牙片的一致运动校准上下排，再按嘴宽适配各自位移与旋转，不重复叠加竖向随唇浮动。原参考静止的牙齿保持原位；目标有小间隙时，下牙整组上移至首次接触，最多嘴宽的 30%，缺少独立上下牙则跳过。未校准的自定义或下颌动作保留有界随唇处理。接触可先收回校准动作中的前移，再按牙弓与嘴宽的较大值取 6.5% 额度整排后移，保留牙弓及上下行程；未校准动作仍采用 2.5% 共同后移及 4% 局部后移。检查局部修正是否引入新的三角面翻折；额度不足记录穿插，不向外推 Face，不缩放牙弓，不改变 Basis | 存在对应分区时执行 | recipe | procedural_constraints.close_dental_contact / procedural_contacts.oral_face |
| 15 | 口内接触 | 按唇缘相连拓扑选择 Face 接触面，包含斜面及内翻唇面；牙齿及口腔退回面部内侧，口腔唇缘固定。取消舌头随整排牙齿最前点后退；牙齿与舌头的接触只由实际三角面交叉触发。舌头上表面避开下口腔，Basis 同样检查；接触位移上限取舌长 12% 和口宽 8% 的较小值，同次修正反复检查共用额度；超出额度报告冲突 | 存在对应分区时执行 | recipe | procedural_contacts.finish / tongue_teeth / tongue_side |
| 16 | 写入 | 表情形态键、口腔联动和最终变形曲线一起保存 | 存在对应分区时执行 | recipe | procedural_generate.generate |
| 17 | 眼部数值 | 位移采样 × 当前眼宽；Z 再乘当前眼高与参考高宽比修正；17 个 XYZ 采样保存在 JSON | 按当前曲线与分区计算 | recipe.eyes.-1.upper | procedural_atoms.sampled |
| 18 | 眼部数值 | 位移采样 × 当前眼宽；Z 再乘当前眼高与参考高宽比修正；17 个 XYZ 采样保存在 JSON | 按当前曲线与分区计算 | recipe.eyes.-1.lower | procedural_atoms.sampled |
| 19 | 闭合规则 | 闭合=0；下眼参与=0.1；笑眼=0；平直=0。上缘不升、水平下缘不降且限幅；竖向眼角以转折为下降边界。笑眼上拱、なごみ平直，冲突不回退为相反曲率。 | 按当前曲线与分区计算 | recipe.eyes.-1 | procedural_atoms.solve |
| 20 | 眼部数值 | 位移采样 × 当前眼宽；Z 再乘当前眼高与参考高宽比修正；17 个 XYZ 采样保存在 JSON | 按当前曲线与分区计算 | recipe.eyes.1.upper | procedural_atoms.sampled |
| 21 | 眼部数值 | 位移采样 × 当前眼宽；Z 再乘当前眼高与参考高宽比修正；17 个 XYZ 采样保存在 JSON | 按当前曲线与分区计算 | recipe.eyes.1.lower | procedural_atoms.sampled |
| 22 | 闭合规则 | 闭合=0；下眼参与=0.1；笑眼=0；平直=0。上缘不升、水平下缘不降且限幅；竖向眼角以转折为下降边界。笑眼上拱、なごみ平直，冲突不回退为相反曲率。 | 按当前曲线与分区计算 | recipe.eyes.1 | procedural_atoms.solve |

数值定义：JSON 中 `expressions` 的同名项。

## じと目

| 顺序 | 阶段 | 计算准则 | 条件 | 数值路径 | 实现 |
| --- | --- | --- | --- | --- | --- |
| 1 | 对称策略 | 允许强制左右对称；正侧完成约束后直接镜像最终坐标到负侧，不再两侧平均。独立眼眉在相关顶点可配对时只计算正侧，不要求三角面划分相同。跨中线口型保留整体求解；活动顶点无法配对则跳过。镜像后的翻折数量写入报告 | 生成时开启强制对称 | can_symmetrize / special / relation | procedural_symmetry |
| 2 | 输入 | 按当前标记读取；已删除必要曲线所依赖的表情跳过 | 存在对应分区时执行 | recipe | procedural_rig.checkpoint |
| 3 | 眼部目标 | 按眼宽和眼高归一化；普通闭眼反射当前上眼缘曲率，笑闭眼保留上拱 | 存在对应分区时执行 | recipe | procedural_atoms.character_arc |
| 4 | 眼缘拟合 | 上下缘共用闭眼接缝；上缘向下、水平下缘不下降且上移上限 30%，笑眼弧顶额外 10%。闭眼内眼角允许下降，但不低于原始下眼睑横向主体，并略微上提。笑眼保持上拱，なごみ保持直线；边界冲突则跳过并说明原因 | 存在对应分区时执行 | recipe | procedural_atoms.solve |
| 5 | 皮肤求解 | 固定眼口控制点，沿 Face 邻接平滑传播 | 存在对应分区时执行 | recipe | procedural_skin.EyelidSkin.deform |
| 6 | 防破面 | 保持轮廓约束，限制局部修正，残余冲突写入报告 | 存在对应分区时执行 | recipe | procedural_constraints.finalize_skin |
| 7 | 眼部接触 | 沿用原始预设的眼层依次避让。高光、瞳孔、眼白依次执行整体深度位移，保留原始间距和形状；检查 Basis 到终点的 16 个权重。位移上限保留闭眼眼宽 24%、睁眼 35%，Basis 不变。整片睫毛向内贴合、向外避让，保留原始嵌入。未消除的接触与覆盖问题写入报告 | 存在对应分区时执行 | recipe | procedural_constraints.closed_eye_stack / procedural_lashes.lower_owned_upper_sections |
| 8 | 睫毛 | 拟合原始截面中心，沿最终 XYZ 闭眼曲线统一平移和旋转截面，保留厚度；眼尾连续延伸，不截断修正斜率。单根睫毛、双眼皮等共用最终截面变换，眉毛独立。竖向眼角平滑进入弯折区，之后执行贴脸与避让，并复查最终闭合线覆盖。まばたき下凹、笑い上拱且弧度延续到眼尾、なごみ优先水平平直；闭眼接合和下眼睑限幅更强。单根只读取已有标记 | 存在对应分区时执行 | recipe | procedural_lashes.style_band / fold_vertical_sections / finish_upper_sweep / deform / audit_closed_band |
| 9 | 风格设置 | 下眼睑参与量在可行闭合范围中选择接合位置，不改变下眼睑 30% 上移及笑眼弧顶额外 10% 的硬上限。笑眼弧度与形态保持调整曲线偏好，闭合、接触和厚度优先。组合、曲线写回沿用生成时保存的风格设置 | 存在对应分区时执行 | recipe | procedural_ui.generation_options / procedural_binding.styled_closure |
| 10 | 闭眼层次 | 下睫毛随实际下眼眶的连续位移和旋转运动。闭眼时将整条下睫毛的上下缘收在上睫毛投影内，再求解前后层次。Face 接触后复查并修正遮盖，最终悬空和覆盖不足单独报告 | 存在对应分区时执行 | recipe | procedural_lashes.follow_lower_rim / cover_lower_band / finish_closed_order |
| 11 | 眼角弯折 | 跟随下眼眶的强度随切线倾角连续增加，垂直达到 1，继续内斜仍保持 1。按原曲线弧长定位截面，避免竖向长度展开成内眼角横向拉长。普通闭眼保留内眼角跨度约束，なごみ和笑闭眼保持整条中心线的横向长度；单眼表情继承对应约束 | 存在对应分区时执行 | recipe | procedural_lashes.slope_follow_weight / finish_upper_sweep |
| 12 | 计算设备 | Windows NVIDIA CUDA 可用时，以双精度 GPU 内核求解三角面投影接触。小任务、缺少运行库、显存或调用失败时使用 CPU。两种设备共用几何规则、容差和可移动条件，报告设备、调用数与回退原因 | 存在对应分区时执行 | recipe | procedural_gpu.try_depth |
| 13 | 口腔 | 口内边界固定到实际唇缘，内部连续变形；强制镜像后重新贴合 Face 与 Mouth，避免两次表面插值产生小接缝 | 存在对应分区时执行 | recipe | procedural_cavity.deform |
| 14 | 牙齿 | 内置口型按 Original 张口时牙片的一致运动校准上下排，再按嘴宽适配各自位移与旋转，不重复叠加竖向随唇浮动。原参考静止的牙齿保持原位；目标有小间隙时，下牙整组上移至首次接触，最多嘴宽的 30%，缺少独立上下牙则跳过。未校准的自定义或下颌动作保留有界随唇处理。接触可先收回校准动作中的前移，再按牙弓与嘴宽的较大值取 6.5% 额度整排后移，保留牙弓及上下行程；未校准动作仍采用 2.5% 共同后移及 4% 局部后移。检查局部修正是否引入新的三角面翻折；额度不足记录穿插，不向外推 Face，不缩放牙弓，不改变 Basis | 存在对应分区时执行 | recipe | procedural_constraints.close_dental_contact / procedural_contacts.oral_face |
| 15 | 口内接触 | 按唇缘相连拓扑选择 Face 接触面，包含斜面及内翻唇面；牙齿及口腔退回面部内侧，口腔唇缘固定。取消舌头随整排牙齿最前点后退；牙齿与舌头的接触只由实际三角面交叉触发。舌头上表面避开下口腔，Basis 同样检查；接触位移上限取舌长 12% 和口宽 8% 的较小值，同次修正反复检查共用额度；超出额度报告冲突 | 存在对应分区时执行 | recipe | procedural_contacts.finish / tongue_teeth / tongue_side |
| 16 | 写入 | 表情形态键、口腔联动和最终变形曲线一起保存 | 存在对应分区时执行 | recipe | procedural_generate.generate |
| 17 | 睁眼动作 | 下眼睑固定；上眼睑小幅下移，趋于平直。 | 按当前曲线与分区计算 | recipe.eyes.-1.open_motion | procedural_atoms.open_lid_rule |
| 18 | 眼部数值 | 位移采样 × 当前眼宽；Z 再乘当前眼高与参考高宽比修正；17 个 XYZ 采样保存在 JSON | 按当前曲线与分区计算 | recipe.eyes.-1.upper | procedural_atoms.sampled |
| 19 | 眼部数值 | 位移采样 × 当前眼宽；Z 再乘当前眼高与参考高宽比修正；17 个 XYZ 采样保存在 JSON | 按当前曲线与分区计算 | recipe.eyes.-1.lower | procedural_atoms.sampled |
| 20 | 闭合规则 | 闭合=0；下眼参与=0.04；笑眼=0；平直=0。上缘不升、水平下缘不降且限幅；竖向眼角以转折为下降边界。笑眼上拱、なごみ平直，冲突不回退为相反曲率。 | 按当前曲线与分区计算 | recipe.eyes.-1 | procedural_atoms.solve |
| 21 | 睁眼动作 | 下眼睑固定；上眼睑小幅下移，趋于平直。 | 按当前曲线与分区计算 | recipe.eyes.1.open_motion | procedural_atoms.open_lid_rule |
| 22 | 眼部数值 | 位移采样 × 当前眼宽；Z 再乘当前眼高与参考高宽比修正；17 个 XYZ 采样保存在 JSON | 按当前曲线与分区计算 | recipe.eyes.1.upper | procedural_atoms.sampled |
| 23 | 眼部数值 | 位移采样 × 当前眼宽；Z 再乘当前眼高与参考高宽比修正；17 个 XYZ 采样保存在 JSON | 按当前曲线与分区计算 | recipe.eyes.1.lower | procedural_atoms.sampled |
| 24 | 闭合规则 | 闭合=0；下眼参与=0.04；笑眼=0；平直=0。上缘不升、水平下缘不降且限幅；竖向眼角以转折为下降边界。笑眼上拱、なごみ平直，冲突不回退为相反曲率。 | 按当前曲线与分区计算 | recipe.eyes.1 | procedural_atoms.solve |

数值定义：JSON 中 `expressions` 的同名项。

## 悲しむ

| 顺序 | 阶段 | 计算准则 | 条件 | 数值路径 | 实现 |
| --- | --- | --- | --- | --- | --- |
| 1 | 对称策略 | 允许强制左右对称；正侧完成约束后直接镜像最终坐标到负侧，不再两侧平均。独立眼眉在相关顶点可配对时只计算正侧，不要求三角面划分相同。跨中线口型保留整体求解；活动顶点无法配对则跳过。镜像后的翻折数量写入报告 | 生成时开启强制对称 | can_symmetrize / special / relation | procedural_symmetry |
| 2 | 输入 | 按当前标记读取；已删除必要曲线所依赖的表情跳过 | 存在对应分区时执行 | recipe | procedural_rig.checkpoint |
| 3 | 眼部目标 | 按眼宽和眼高归一化；普通闭眼反射当前上眼缘曲率，笑闭眼保留上拱 | 存在对应分区时执行 | recipe | procedural_atoms.character_arc |
| 4 | 眼缘拟合 | 上下缘共用闭眼接缝；上缘向下、水平下缘不下降且上移上限 30%，笑眼弧顶额外 10%。闭眼内眼角允许下降，但不低于原始下眼睑横向主体，并略微上提。笑眼保持上拱，なごみ保持直线；边界冲突则跳过并说明原因 | 存在对应分区时执行 | recipe | procedural_atoms.solve |
| 5 | 皮肤求解 | 固定眼口控制点，沿 Face 邻接平滑传播 | 存在对应分区时执行 | recipe | procedural_skin.EyelidSkin.deform |
| 6 | 防破面 | 保持轮廓约束，限制局部修正，残余冲突写入报告 | 存在对应分区时执行 | recipe | procedural_constraints.finalize_skin |
| 7 | 眼部接触 | 沿用原始预设的眼层依次避让。高光、瞳孔、眼白依次执行整体深度位移，保留原始间距和形状；检查 Basis 到终点的 16 个权重。位移上限保留闭眼眼宽 24%、睁眼 35%，Basis 不变。整片睫毛向内贴合、向外避让，保留原始嵌入。未消除的接触与覆盖问题写入报告 | 存在对应分区时执行 | recipe | procedural_constraints.closed_eye_stack / procedural_lashes.lower_owned_upper_sections |
| 8 | 睫毛 | 拟合原始截面中心，沿最终 XYZ 闭眼曲线统一平移和旋转截面，保留厚度；眼尾连续延伸，不截断修正斜率。单根睫毛、双眼皮等共用最终截面变换，眉毛独立。竖向眼角平滑进入弯折区，之后执行贴脸与避让，并复查最终闭合线覆盖。まばたき下凹、笑い上拱且弧度延续到眼尾、なごみ优先水平平直；闭眼接合和下眼睑限幅更强。单根只读取已有标记 | 存在对应分区时执行 | recipe | procedural_lashes.style_band / fold_vertical_sections / finish_upper_sweep / deform / audit_closed_band |
| 9 | 风格设置 | 下眼睑参与量在可行闭合范围中选择接合位置，不改变下眼睑 30% 上移及笑眼弧顶额外 10% 的硬上限。笑眼弧度与形态保持调整曲线偏好，闭合、接触和厚度优先。组合、曲线写回沿用生成时保存的风格设置 | 存在对应分区时执行 | recipe | procedural_ui.generation_options / procedural_binding.styled_closure |
| 10 | 闭眼层次 | 下睫毛随实际下眼眶的连续位移和旋转运动。闭眼时将整条下睫毛的上下缘收在上睫毛投影内，再求解前后层次。Face 接触后复查并修正遮盖，最终悬空和覆盖不足单独报告 | 存在对应分区时执行 | recipe | procedural_lashes.follow_lower_rim / cover_lower_band / finish_closed_order |
| 11 | 眼角弯折 | 跟随下眼眶的强度随切线倾角连续增加，垂直达到 1，继续内斜仍保持 1。按原曲线弧长定位截面，避免竖向长度展开成内眼角横向拉长。普通闭眼保留内眼角跨度约束，なごみ和笑闭眼保持整条中心线的横向长度；单眼表情继承对应约束 | 存在对应分区时执行 | recipe | procedural_lashes.slope_follow_weight / finish_upper_sweep |
| 12 | 计算设备 | Windows NVIDIA CUDA 可用时，以双精度 GPU 内核求解三角面投影接触。小任务、缺少运行库、显存或调用失败时使用 CPU。两种设备共用几何规则、容差和可移动条件，报告设备、调用数与回退原因 | 存在对应分区时执行 | recipe | procedural_gpu.try_depth |
| 13 | 口腔 | 口内边界固定到实际唇缘，内部连续变形；强制镜像后重新贴合 Face 与 Mouth，避免两次表面插值产生小接缝 | 存在对应分区时执行 | recipe | procedural_cavity.deform |
| 14 | 牙齿 | 内置口型按 Original 张口时牙片的一致运动校准上下排，再按嘴宽适配各自位移与旋转，不重复叠加竖向随唇浮动。原参考静止的牙齿保持原位；目标有小间隙时，下牙整组上移至首次接触，最多嘴宽的 30%，缺少独立上下牙则跳过。未校准的自定义或下颌动作保留有界随唇处理。接触可先收回校准动作中的前移，再按牙弓与嘴宽的较大值取 6.5% 额度整排后移，保留牙弓及上下行程；未校准动作仍采用 2.5% 共同后移及 4% 局部后移。检查局部修正是否引入新的三角面翻折；额度不足记录穿插，不向外推 Face，不缩放牙弓，不改变 Basis | 存在对应分区时执行 | recipe | procedural_constraints.close_dental_contact / procedural_contacts.oral_face |
| 15 | 口内接触 | 按唇缘相连拓扑选择 Face 接触面，包含斜面及内翻唇面；牙齿及口腔退回面部内侧，口腔唇缘固定。取消舌头随整排牙齿最前点后退；牙齿与舌头的接触只由实际三角面交叉触发。舌头上表面避开下口腔，Basis 同样检查；接触位移上限取舌长 12% 和口宽 8% 的较小值，同次修正反复检查共用额度；超出额度报告冲突 | 存在对应分区时执行 | recipe | procedural_contacts.finish / tongue_teeth / tongue_side |
| 16 | 写入 | 表情形态键、口腔联动和最终变形曲线一起保存 | 存在对应分区时执行 | recipe | procedural_generate.generate |
| 17 | 睁眼动作 | 上眼睑向下、外侧更多；最高点靠内眼角，向外侧平滑下斜。下眼睑上移、中部更多。 | 按当前曲线与分区计算 | recipe.eyes.-1.open_motion | procedural_atoms.open_lid_rule |
| 18 | 眼部数值 | 位移采样 × 当前眼宽；Z 再乘当前眼高与参考高宽比修正；17 个 XYZ 采样保存在 JSON | 按当前曲线与分区计算 | recipe.eyes.-1.upper | procedural_atoms.sampled |
| 19 | 眼部数值 | 位移采样 × 当前眼宽；Z 再乘当前眼高与参考高宽比修正；17 个 XYZ 采样保存在 JSON | 按当前曲线与分区计算 | recipe.eyes.-1.lower | procedural_atoms.sampled |
| 20 | 闭合规则 | 闭合=0；下眼参与=0.354278；笑眼=0；平直=0。上缘不升、水平下缘不降且限幅；竖向眼角以转折为下降边界。笑眼上拱、なごみ平直，冲突不回退为相反曲率。 | 按当前曲线与分区计算 | recipe.eyes.-1 | procedural_atoms.solve |
| 21 | 睁眼动作 | 上眼睑向下、外侧更多；最高点靠内眼角，向外侧平滑下斜。下眼睑上移、中部更多。 | 按当前曲线与分区计算 | recipe.eyes.1.open_motion | procedural_atoms.open_lid_rule |
| 22 | 眼部数值 | 位移采样 × 当前眼宽；Z 再乘当前眼高与参考高宽比修正；17 个 XYZ 采样保存在 JSON | 按当前曲线与分区计算 | recipe.eyes.1.upper | procedural_atoms.sampled |
| 23 | 眼部数值 | 位移采样 × 当前眼宽；Z 再乘当前眼高与参考高宽比修正；17 个 XYZ 采样保存在 JSON | 按当前曲线与分区计算 | recipe.eyes.1.lower | procedural_atoms.sampled |
| 24 | 闭合规则 | 闭合=0；下眼参与=0.354286；笑眼=0；平直=0。上缘不升、水平下缘不降且限幅；竖向眼角以转折为下降边界。笑眼上拱、なごみ平直，冲突不回退为相反曲率。 | 按当前曲线与分区计算 | recipe.eyes.1 | procedural_atoms.solve |

数值定义：JSON 中 `expressions` 的同名项。

## 怒り目

| 顺序 | 阶段 | 计算准则 | 条件 | 数值路径 | 实现 |
| --- | --- | --- | --- | --- | --- |
| 1 | 对称策略 | 允许强制左右对称；正侧完成约束后直接镜像最终坐标到负侧，不再两侧平均。独立眼眉在相关顶点可配对时只计算正侧，不要求三角面划分相同。跨中线口型保留整体求解；活动顶点无法配对则跳过。镜像后的翻折数量写入报告 | 生成时开启强制对称 | can_symmetrize / special / relation | procedural_symmetry |
| 2 | 输入 | 按当前标记读取；已删除必要曲线所依赖的表情跳过 | 存在对应分区时执行 | recipe | procedural_rig.checkpoint |
| 3 | 眼部目标 | 按眼宽和眼高归一化；普通闭眼反射当前上眼缘曲率，笑闭眼保留上拱 | 存在对应分区时执行 | recipe | procedural_atoms.character_arc |
| 4 | 眼缘拟合 | 上下缘共用闭眼接缝；上缘向下、水平下缘不下降且上移上限 30%，笑眼弧顶额外 10%。闭眼内眼角允许下降，但不低于原始下眼睑横向主体，并略微上提。笑眼保持上拱，なごみ保持直线；边界冲突则跳过并说明原因 | 存在对应分区时执行 | recipe | procedural_atoms.solve |
| 5 | 皮肤求解 | 固定眼口控制点，沿 Face 邻接平滑传播 | 存在对应分区时执行 | recipe | procedural_skin.EyelidSkin.deform |
| 6 | 防破面 | 保持轮廓约束，限制局部修正，残余冲突写入报告 | 存在对应分区时执行 | recipe | procedural_constraints.finalize_skin |
| 7 | 眼部接触 | 沿用原始预设的眼层依次避让。高光、瞳孔、眼白依次执行整体深度位移，保留原始间距和形状；检查 Basis 到终点的 16 个权重。位移上限保留闭眼眼宽 24%、睁眼 35%，Basis 不变。整片睫毛向内贴合、向外避让，保留原始嵌入。未消除的接触与覆盖问题写入报告 | 存在对应分区时执行 | recipe | procedural_constraints.closed_eye_stack / procedural_lashes.lower_owned_upper_sections |
| 8 | 睫毛 | 拟合原始截面中心，沿最终 XYZ 闭眼曲线统一平移和旋转截面，保留厚度；眼尾连续延伸，不截断修正斜率。单根睫毛、双眼皮等共用最终截面变换，眉毛独立。竖向眼角平滑进入弯折区，之后执行贴脸与避让，并复查最终闭合线覆盖。まばたき下凹、笑い上拱且弧度延续到眼尾、なごみ优先水平平直；闭眼接合和下眼睑限幅更强。单根只读取已有标记 | 存在对应分区时执行 | recipe | procedural_lashes.style_band / fold_vertical_sections / finish_upper_sweep / deform / audit_closed_band |
| 9 | 风格设置 | 下眼睑参与量在可行闭合范围中选择接合位置，不改变下眼睑 30% 上移及笑眼弧顶额外 10% 的硬上限。笑眼弧度与形态保持调整曲线偏好，闭合、接触和厚度优先。组合、曲线写回沿用生成时保存的风格设置 | 存在对应分区时执行 | recipe | procedural_ui.generation_options / procedural_binding.styled_closure |
| 10 | 闭眼层次 | 下睫毛随实际下眼眶的连续位移和旋转运动。闭眼时将整条下睫毛的上下缘收在上睫毛投影内，再求解前后层次。Face 接触后复查并修正遮盖，最终悬空和覆盖不足单独报告 | 存在对应分区时执行 | recipe | procedural_lashes.follow_lower_rim / cover_lower_band / finish_closed_order |
| 11 | 眼角弯折 | 跟随下眼眶的强度随切线倾角连续增加，垂直达到 1，继续内斜仍保持 1。按原曲线弧长定位截面，避免竖向长度展开成内眼角横向拉长。普通闭眼保留内眼角跨度约束，なごみ和笑闭眼保持整条中心线的横向长度；单眼表情继承对应约束 | 存在对应分区时执行 | recipe | procedural_lashes.slope_follow_weight / finish_upper_sweep |
| 12 | 计算设备 | Windows NVIDIA CUDA 可用时，以双精度 GPU 内核求解三角面投影接触。小任务、缺少运行库、显存或调用失败时使用 CPU。两种设备共用几何规则、容差和可移动条件，报告设备、调用数与回退原因 | 存在对应分区时执行 | recipe | procedural_gpu.try_depth |
| 13 | 口腔 | 口内边界固定到实际唇缘，内部连续变形；强制镜像后重新贴合 Face 与 Mouth，避免两次表面插值产生小接缝 | 存在对应分区时执行 | recipe | procedural_cavity.deform |
| 14 | 牙齿 | 内置口型按 Original 张口时牙片的一致运动校准上下排，再按嘴宽适配各自位移与旋转，不重复叠加竖向随唇浮动。原参考静止的牙齿保持原位；目标有小间隙时，下牙整组上移至首次接触，最多嘴宽的 30%，缺少独立上下牙则跳过。未校准的自定义或下颌动作保留有界随唇处理。接触可先收回校准动作中的前移，再按牙弓与嘴宽的较大值取 6.5% 额度整排后移，保留牙弓及上下行程；未校准动作仍采用 2.5% 共同后移及 4% 局部后移。检查局部修正是否引入新的三角面翻折；额度不足记录穿插，不向外推 Face，不缩放牙弓，不改变 Basis | 存在对应分区时执行 | recipe | procedural_constraints.close_dental_contact / procedural_contacts.oral_face |
| 15 | 口内接触 | 按唇缘相连拓扑选择 Face 接触面，包含斜面及内翻唇面；牙齿及口腔退回面部内侧，口腔唇缘固定。取消舌头随整排牙齿最前点后退；牙齿与舌头的接触只由实际三角面交叉触发。舌头上表面避开下口腔，Basis 同样检查；接触位移上限取舌长 12% 和口宽 8% 的较小值，同次修正反复检查共用额度；超出额度报告冲突 | 存在对应分区时执行 | recipe | procedural_contacts.finish / tongue_teeth / tongue_side |
| 16 | 写入 | 表情形态键、口腔联动和最终变形曲线一起保存 | 存在对应分区时执行 | recipe | procedural_generate.generate |
| 17 | 睁眼动作 | 上眼睑向下、内侧更多；下眼睑上移，曲率减小并趋于平直。 | 按当前曲线与分区计算 | recipe.eyes.-1.open_motion | procedural_atoms.open_lid_rule |
| 18 | 眼部数值 | 位移采样 × 当前眼宽；Z 再乘当前眼高与参考高宽比修正；17 个 XYZ 采样保存在 JSON | 按当前曲线与分区计算 | recipe.eyes.-1.upper | procedural_atoms.sampled |
| 19 | 眼部数值 | 位移采样 × 当前眼宽；Z 再乘当前眼高与参考高宽比修正；17 个 XYZ 采样保存在 JSON | 按当前曲线与分区计算 | recipe.eyes.-1.lower | procedural_atoms.sampled |
| 20 | 闭合规则 | 闭合=0；下眼参与=0.315596；笑眼=0；平直=0。上缘不升、水平下缘不降且限幅；竖向眼角以转折为下降边界。笑眼上拱、なごみ平直，冲突不回退为相反曲率。 | 按当前曲线与分区计算 | recipe.eyes.-1 | procedural_atoms.solve |
| 21 | 睁眼动作 | 上眼睑向下、内侧更多；下眼睑上移，曲率减小并趋于平直。 | 按当前曲线与分区计算 | recipe.eyes.1.open_motion | procedural_atoms.open_lid_rule |
| 22 | 眼部数值 | 位移采样 × 当前眼宽；Z 再乘当前眼高与参考高宽比修正；17 个 XYZ 采样保存在 JSON | 按当前曲线与分区计算 | recipe.eyes.1.upper | procedural_atoms.sampled |
| 23 | 眼部数值 | 位移采样 × 当前眼宽；Z 再乘当前眼高与参考高宽比修正；17 个 XYZ 采样保存在 JSON | 按当前曲线与分区计算 | recipe.eyes.1.lower | procedural_atoms.sampled |
| 24 | 闭合规则 | 闭合=0；下眼参与=0.315597；笑眼=0；平直=0。上缘不升、水平下缘不降且限幅；竖向眼角以转折为下降边界。笑眼上拱、なごみ平直，冲突不回退为相反曲率。 | 按当前曲线与分区计算 | recipe.eyes.1 | procedural_atoms.solve |

数值定义：JSON 中 `expressions` 的同名项。

## ジト目

| 顺序 | 阶段 | 计算准则 | 条件 | 数值路径 | 实现 |
| --- | --- | --- | --- | --- | --- |
| 1 | 对称策略 | 允许强制左右对称；正侧完成约束后直接镜像最终坐标到负侧，不再两侧平均。独立眼眉在相关顶点可配对时只计算正侧，不要求三角面划分相同。跨中线口型保留整体求解；活动顶点无法配对则跳过。镜像后的翻折数量写入报告 | 生成时开启强制对称 | can_symmetrize / special / relation | procedural_symmetry |
| 2 | 输入 | 按当前标记读取；已删除必要曲线所依赖的表情跳过 | 存在对应分区时执行 | recipe | procedural_rig.checkpoint |
| 3 | 眼部目标 | 按眼宽和眼高归一化；普通闭眼反射当前上眼缘曲率，笑闭眼保留上拱 | 存在对应分区时执行 | recipe | procedural_atoms.character_arc |
| 4 | 眼缘拟合 | 上下缘共用闭眼接缝；上缘向下、水平下缘不下降且上移上限 30%，笑眼弧顶额外 10%。闭眼内眼角允许下降，但不低于原始下眼睑横向主体，并略微上提。笑眼保持上拱，なごみ保持直线；边界冲突则跳过并说明原因 | 存在对应分区时执行 | recipe | procedural_atoms.solve |
| 5 | 皮肤求解 | 固定眼口控制点，沿 Face 邻接平滑传播 | 存在对应分区时执行 | recipe | procedural_skin.EyelidSkin.deform |
| 6 | 防破面 | 保持轮廓约束，限制局部修正，残余冲突写入报告 | 存在对应分区时执行 | recipe | procedural_constraints.finalize_skin |
| 7 | 眼部接触 | 沿用原始预设的眼层依次避让。高光、瞳孔、眼白依次执行整体深度位移，保留原始间距和形状；检查 Basis 到终点的 16 个权重。位移上限保留闭眼眼宽 24%、睁眼 35%，Basis 不变。整片睫毛向内贴合、向外避让，保留原始嵌入。未消除的接触与覆盖问题写入报告 | 存在对应分区时执行 | recipe | procedural_constraints.closed_eye_stack / procedural_lashes.lower_owned_upper_sections |
| 8 | 睫毛 | 拟合原始截面中心，沿最终 XYZ 闭眼曲线统一平移和旋转截面，保留厚度；眼尾连续延伸，不截断修正斜率。单根睫毛、双眼皮等共用最终截面变换，眉毛独立。竖向眼角平滑进入弯折区，之后执行贴脸与避让，并复查最终闭合线覆盖。まばたき下凹、笑い上拱且弧度延续到眼尾、なごみ优先水平平直；闭眼接合和下眼睑限幅更强。单根只读取已有标记 | 存在对应分区时执行 | recipe | procedural_lashes.style_band / fold_vertical_sections / finish_upper_sweep / deform / audit_closed_band |
| 9 | 风格设置 | 下眼睑参与量在可行闭合范围中选择接合位置，不改变下眼睑 30% 上移及笑眼弧顶额外 10% 的硬上限。笑眼弧度与形态保持调整曲线偏好，闭合、接触和厚度优先。组合、曲线写回沿用生成时保存的风格设置 | 存在对应分区时执行 | recipe | procedural_ui.generation_options / procedural_binding.styled_closure |
| 10 | 闭眼层次 | 下睫毛随实际下眼眶的连续位移和旋转运动。闭眼时将整条下睫毛的上下缘收在上睫毛投影内，再求解前后层次。Face 接触后复查并修正遮盖，最终悬空和覆盖不足单独报告 | 存在对应分区时执行 | recipe | procedural_lashes.follow_lower_rim / cover_lower_band / finish_closed_order |
| 11 | 眼角弯折 | 跟随下眼眶的强度随切线倾角连续增加，垂直达到 1，继续内斜仍保持 1。按原曲线弧长定位截面，避免竖向长度展开成内眼角横向拉长。普通闭眼保留内眼角跨度约束，なごみ和笑闭眼保持整条中心线的横向长度；单眼表情继承对应约束 | 存在对应分区时执行 | recipe | procedural_lashes.slope_follow_weight / finish_upper_sweep |
| 12 | 计算设备 | Windows NVIDIA CUDA 可用时，以双精度 GPU 内核求解三角面投影接触。小任务、缺少运行库、显存或调用失败时使用 CPU。两种设备共用几何规则、容差和可移动条件，报告设备、调用数与回退原因 | 存在对应分区时执行 | recipe | procedural_gpu.try_depth |
| 13 | 口腔 | 口内边界固定到实际唇缘，内部连续变形；强制镜像后重新贴合 Face 与 Mouth，避免两次表面插值产生小接缝 | 存在对应分区时执行 | recipe | procedural_cavity.deform |
| 14 | 牙齿 | 内置口型按 Original 张口时牙片的一致运动校准上下排，再按嘴宽适配各自位移与旋转，不重复叠加竖向随唇浮动。原参考静止的牙齿保持原位；目标有小间隙时，下牙整组上移至首次接触，最多嘴宽的 30%，缺少独立上下牙则跳过。未校准的自定义或下颌动作保留有界随唇处理。接触可先收回校准动作中的前移，再按牙弓与嘴宽的较大值取 6.5% 额度整排后移，保留牙弓及上下行程；未校准动作仍采用 2.5% 共同后移及 4% 局部后移。检查局部修正是否引入新的三角面翻折；额度不足记录穿插，不向外推 Face，不缩放牙弓，不改变 Basis | 存在对应分区时执行 | recipe | procedural_constraints.close_dental_contact / procedural_contacts.oral_face |
| 15 | 口内接触 | 按唇缘相连拓扑选择 Face 接触面，包含斜面及内翻唇面；牙齿及口腔退回面部内侧，口腔唇缘固定。取消舌头随整排牙齿最前点后退；牙齿与舌头的接触只由实际三角面交叉触发。舌头上表面避开下口腔，Basis 同样检查；接触位移上限取舌长 12% 和口宽 8% 的较小值，同次修正反复检查共用额度；超出额度报告冲突 | 存在对应分区时执行 | recipe | procedural_contacts.finish / tongue_teeth / tongue_side |
| 16 | 写入 | 表情形态键、口腔联动和最终变形曲线一起保存 | 存在对应分区时执行 | recipe | procedural_generate.generate |
| 17 | 睁眼动作 | 下眼睑固定；上眼睑比じと目下移更多，趋于平直。 | 按当前曲线与分区计算 | recipe.eyes.-1.open_motion | procedural_atoms.open_lid_rule |
| 18 | 眼部数值 | 位移采样 × 当前眼宽；Z 再乘当前眼高与参考高宽比修正；17 个 XYZ 采样保存在 JSON | 按当前曲线与分区计算 | recipe.eyes.-1.upper | procedural_atoms.sampled |
| 19 | 眼部数值 | 位移采样 × 当前眼宽；Z 再乘当前眼高与参考高宽比修正；17 个 XYZ 采样保存在 JSON | 按当前曲线与分区计算 | recipe.eyes.-1.lower | procedural_atoms.sampled |
| 20 | 闭合规则 | 闭合=0；下眼参与=0.04；笑眼=0；平直=0。上缘不升、水平下缘不降且限幅；竖向眼角以转折为下降边界。笑眼上拱、なごみ平直，冲突不回退为相反曲率。 | 按当前曲线与分区计算 | recipe.eyes.-1 | procedural_atoms.solve |
| 21 | 睁眼动作 | 下眼睑固定；上眼睑比じと目下移更多，趋于平直。 | 按当前曲线与分区计算 | recipe.eyes.1.open_motion | procedural_atoms.open_lid_rule |
| 22 | 眼部数值 | 位移采样 × 当前眼宽；Z 再乘当前眼高与参考高宽比修正；17 个 XYZ 采样保存在 JSON | 按当前曲线与分区计算 | recipe.eyes.1.upper | procedural_atoms.sampled |
| 23 | 眼部数值 | 位移采样 × 当前眼宽；Z 再乘当前眼高与参考高宽比修正；17 个 XYZ 采样保存在 JSON | 按当前曲线与分区计算 | recipe.eyes.1.lower | procedural_atoms.sampled |
| 24 | 闭合规则 | 闭合=0；下眼参与=0.04；笑眼=0；平直=0。上缘不升、水平下缘不降且限幅；竖向眼角以转折为下降边界。笑眼上拱、なごみ平直，冲突不回退为相反曲率。 | 按当前曲线与分区计算 | recipe.eyes.1 | procedural_atoms.solve |

数值定义：JSON 中 `expressions` 的同名项。

## 眼角上

| 顺序 | 阶段 | 计算准则 | 条件 | 数值路径 | 实现 |
| --- | --- | --- | --- | --- | --- |
| 1 | 对称策略 | 允许强制左右对称；正侧完成约束后直接镜像最终坐标到负侧，不再两侧平均。独立眼眉在相关顶点可配对时只计算正侧，不要求三角面划分相同。跨中线口型保留整体求解；活动顶点无法配对则跳过。镜像后的翻折数量写入报告 | 生成时开启强制对称 | can_symmetrize / special / relation | procedural_symmetry |
| 2 | 输入 | 按当前标记读取；已删除必要曲线所依赖的表情跳过 | 存在对应分区时执行 | recipe | procedural_rig.checkpoint |
| 3 | 眼部目标 | 按眼宽和眼高归一化；普通闭眼反射当前上眼缘曲率，笑闭眼保留上拱 | 存在对应分区时执行 | recipe | procedural_atoms.character_arc |
| 4 | 眼缘拟合 | 上下缘共用闭眼接缝；上缘向下、水平下缘不下降且上移上限 30%，笑眼弧顶额外 10%。闭眼内眼角允许下降，但不低于原始下眼睑横向主体，并略微上提。笑眼保持上拱，なごみ保持直线；边界冲突则跳过并说明原因 | 存在对应分区时执行 | recipe | procedural_atoms.solve |
| 5 | 皮肤求解 | 固定眼口控制点，沿 Face 邻接平滑传播 | 存在对应分区时执行 | recipe | procedural_skin.EyelidSkin.deform |
| 6 | 防破面 | 保持轮廓约束，限制局部修正，残余冲突写入报告 | 存在对应分区时执行 | recipe | procedural_constraints.finalize_skin |
| 7 | 眼部接触 | 沿用原始预设的眼层依次避让。高光、瞳孔、眼白依次执行整体深度位移，保留原始间距和形状；检查 Basis 到终点的 16 个权重。位移上限保留闭眼眼宽 24%、睁眼 35%，Basis 不变。整片睫毛向内贴合、向外避让，保留原始嵌入。未消除的接触与覆盖问题写入报告 | 存在对应分区时执行 | recipe | procedural_constraints.closed_eye_stack / procedural_lashes.lower_owned_upper_sections |
| 8 | 睫毛 | 拟合原始截面中心，沿最终 XYZ 闭眼曲线统一平移和旋转截面，保留厚度；眼尾连续延伸，不截断修正斜率。单根睫毛、双眼皮等共用最终截面变换，眉毛独立。竖向眼角平滑进入弯折区，之后执行贴脸与避让，并复查最终闭合线覆盖。まばたき下凹、笑い上拱且弧度延续到眼尾、なごみ优先水平平直；闭眼接合和下眼睑限幅更强。单根只读取已有标记 | 存在对应分区时执行 | recipe | procedural_lashes.style_band / fold_vertical_sections / finish_upper_sweep / deform / audit_closed_band |
| 9 | 风格设置 | 下眼睑参与量在可行闭合范围中选择接合位置，不改变下眼睑 30% 上移及笑眼弧顶额外 10% 的硬上限。笑眼弧度与形态保持调整曲线偏好，闭合、接触和厚度优先。组合、曲线写回沿用生成时保存的风格设置 | 存在对应分区时执行 | recipe | procedural_ui.generation_options / procedural_binding.styled_closure |
| 10 | 闭眼层次 | 下睫毛随实际下眼眶的连续位移和旋转运动。闭眼时将整条下睫毛的上下缘收在上睫毛投影内，再求解前后层次。Face 接触后复查并修正遮盖，最终悬空和覆盖不足单独报告 | 存在对应分区时执行 | recipe | procedural_lashes.follow_lower_rim / cover_lower_band / finish_closed_order |
| 11 | 眼角弯折 | 跟随下眼眶的强度随切线倾角连续增加，垂直达到 1，继续内斜仍保持 1。按原曲线弧长定位截面，避免竖向长度展开成内眼角横向拉长。普通闭眼保留内眼角跨度约束，なごみ和笑闭眼保持整条中心线的横向长度；单眼表情继承对应约束 | 存在对应分区时执行 | recipe | procedural_lashes.slope_follow_weight / finish_upper_sweep |
| 12 | 计算设备 | Windows NVIDIA CUDA 可用时，以双精度 GPU 内核求解三角面投影接触。小任务、缺少运行库、显存或调用失败时使用 CPU。两种设备共用几何规则、容差和可移动条件，报告设备、调用数与回退原因 | 存在对应分区时执行 | recipe | procedural_gpu.try_depth |
| 13 | 口腔 | 口内边界固定到实际唇缘，内部连续变形；强制镜像后重新贴合 Face 与 Mouth，避免两次表面插值产生小接缝 | 存在对应分区时执行 | recipe | procedural_cavity.deform |
| 14 | 牙齿 | 内置口型按 Original 张口时牙片的一致运动校准上下排，再按嘴宽适配各自位移与旋转，不重复叠加竖向随唇浮动。原参考静止的牙齿保持原位；目标有小间隙时，下牙整组上移至首次接触，最多嘴宽的 30%，缺少独立上下牙则跳过。未校准的自定义或下颌动作保留有界随唇处理。接触可先收回校准动作中的前移，再按牙弓与嘴宽的较大值取 6.5% 额度整排后移，保留牙弓及上下行程；未校准动作仍采用 2.5% 共同后移及 4% 局部后移。检查局部修正是否引入新的三角面翻折；额度不足记录穿插，不向外推 Face，不缩放牙弓，不改变 Basis | 存在对应分区时执行 | recipe | procedural_constraints.close_dental_contact / procedural_contacts.oral_face |
| 15 | 口内接触 | 按唇缘相连拓扑选择 Face 接触面，包含斜面及内翻唇面；牙齿及口腔退回面部内侧，口腔唇缘固定。取消舌头随整排牙齿最前点后退；牙齿与舌头的接触只由实际三角面交叉触发。舌头上表面避开下口腔，Basis 同样检查；接触位移上限取舌长 12% 和口宽 8% 的较小值，同次修正反复检查共用额度；超出额度报告冲突 | 存在对应分区时执行 | recipe | procedural_contacts.finish / tongue_teeth / tongue_side |
| 16 | 写入 | 表情形态键、口腔联动和最终变形曲线一起保存 | 存在对应分区时执行 | recipe | procedural_generate.generate |
| 17 | 眼部数值 | 位移采样 × 当前眼宽；Z 再乘当前眼高与参考高宽比修正；17 个 XYZ 采样保存在 JSON | 按当前曲线与分区计算 | recipe.eyes.-1.upper | procedural_atoms.sampled |
| 18 | 眼部数值 | 位移采样 × 当前眼宽；Z 再乘当前眼高与参考高宽比修正；17 个 XYZ 采样保存在 JSON | 按当前曲线与分区计算 | recipe.eyes.-1.lower | procedural_atoms.sampled |
| 19 | 闭合规则 | 闭合=0；下眼参与=0.1；笑眼=0；平直=0。上缘不升、水平下缘不降且限幅；竖向眼角以转折为下降边界。笑眼上拱、なごみ平直，冲突不回退为相反曲率。 | 按当前曲线与分区计算 | recipe.eyes.-1 | procedural_atoms.solve |
| 20 | 眼部数值 | 位移采样 × 当前眼宽；Z 再乘当前眼高与参考高宽比修正；17 个 XYZ 采样保存在 JSON | 按当前曲线与分区计算 | recipe.eyes.1.upper | procedural_atoms.sampled |
| 21 | 眼部数值 | 位移采样 × 当前眼宽；Z 再乘当前眼高与参考高宽比修正；17 个 XYZ 采样保存在 JSON | 按当前曲线与分区计算 | recipe.eyes.1.lower | procedural_atoms.sampled |
| 22 | 闭合规则 | 闭合=0；下眼参与=0.1；笑眼=0；平直=0。上缘不升、水平下缘不降且限幅；竖向眼角以转折为下降边界。笑眼上拱、なごみ平直，冲突不回退为相反曲率。 | 按当前曲线与分区计算 | recipe.eyes.1 | procedural_atoms.solve |

数值定义：JSON 中 `expressions` 的同名项。

## 眼角下

| 顺序 | 阶段 | 计算准则 | 条件 | 数值路径 | 实现 |
| --- | --- | --- | --- | --- | --- |
| 1 | 对称策略 | 允许强制左右对称；正侧完成约束后直接镜像最终坐标到负侧，不再两侧平均。独立眼眉在相关顶点可配对时只计算正侧，不要求三角面划分相同。跨中线口型保留整体求解；活动顶点无法配对则跳过。镜像后的翻折数量写入报告 | 生成时开启强制对称 | can_symmetrize / special / relation | procedural_symmetry |
| 2 | 输入 | 按当前标记读取；已删除必要曲线所依赖的表情跳过 | 存在对应分区时执行 | recipe | procedural_rig.checkpoint |
| 3 | 眼部目标 | 按眼宽和眼高归一化；普通闭眼反射当前上眼缘曲率，笑闭眼保留上拱 | 存在对应分区时执行 | recipe | procedural_atoms.character_arc |
| 4 | 眼缘拟合 | 上下缘共用闭眼接缝；上缘向下、水平下缘不下降且上移上限 30%，笑眼弧顶额外 10%。闭眼内眼角允许下降，但不低于原始下眼睑横向主体，并略微上提。笑眼保持上拱，なごみ保持直线；边界冲突则跳过并说明原因 | 存在对应分区时执行 | recipe | procedural_atoms.solve |
| 5 | 皮肤求解 | 固定眼口控制点，沿 Face 邻接平滑传播 | 存在对应分区时执行 | recipe | procedural_skin.EyelidSkin.deform |
| 6 | 防破面 | 保持轮廓约束，限制局部修正，残余冲突写入报告 | 存在对应分区时执行 | recipe | procedural_constraints.finalize_skin |
| 7 | 眼部接触 | 沿用原始预设的眼层依次避让。高光、瞳孔、眼白依次执行整体深度位移，保留原始间距和形状；检查 Basis 到终点的 16 个权重。位移上限保留闭眼眼宽 24%、睁眼 35%，Basis 不变。整片睫毛向内贴合、向外避让，保留原始嵌入。未消除的接触与覆盖问题写入报告 | 存在对应分区时执行 | recipe | procedural_constraints.closed_eye_stack / procedural_lashes.lower_owned_upper_sections |
| 8 | 睫毛 | 拟合原始截面中心，沿最终 XYZ 闭眼曲线统一平移和旋转截面，保留厚度；眼尾连续延伸，不截断修正斜率。单根睫毛、双眼皮等共用最终截面变换，眉毛独立。竖向眼角平滑进入弯折区，之后执行贴脸与避让，并复查最终闭合线覆盖。まばたき下凹、笑い上拱且弧度延续到眼尾、なごみ优先水平平直；闭眼接合和下眼睑限幅更强。单根只读取已有标记 | 存在对应分区时执行 | recipe | procedural_lashes.style_band / fold_vertical_sections / finish_upper_sweep / deform / audit_closed_band |
| 9 | 风格设置 | 下眼睑参与量在可行闭合范围中选择接合位置，不改变下眼睑 30% 上移及笑眼弧顶额外 10% 的硬上限。笑眼弧度与形态保持调整曲线偏好，闭合、接触和厚度优先。组合、曲线写回沿用生成时保存的风格设置 | 存在对应分区时执行 | recipe | procedural_ui.generation_options / procedural_binding.styled_closure |
| 10 | 闭眼层次 | 下睫毛随实际下眼眶的连续位移和旋转运动。闭眼时将整条下睫毛的上下缘收在上睫毛投影内，再求解前后层次。Face 接触后复查并修正遮盖，最终悬空和覆盖不足单独报告 | 存在对应分区时执行 | recipe | procedural_lashes.follow_lower_rim / cover_lower_band / finish_closed_order |
| 11 | 眼角弯折 | 跟随下眼眶的强度随切线倾角连续增加，垂直达到 1，继续内斜仍保持 1。按原曲线弧长定位截面，避免竖向长度展开成内眼角横向拉长。普通闭眼保留内眼角跨度约束，なごみ和笑闭眼保持整条中心线的横向长度；单眼表情继承对应约束 | 存在对应分区时执行 | recipe | procedural_lashes.slope_follow_weight / finish_upper_sweep |
| 12 | 计算设备 | Windows NVIDIA CUDA 可用时，以双精度 GPU 内核求解三角面投影接触。小任务、缺少运行库、显存或调用失败时使用 CPU。两种设备共用几何规则、容差和可移动条件，报告设备、调用数与回退原因 | 存在对应分区时执行 | recipe | procedural_gpu.try_depth |
| 13 | 口腔 | 口内边界固定到实际唇缘，内部连续变形；强制镜像后重新贴合 Face 与 Mouth，避免两次表面插值产生小接缝 | 存在对应分区时执行 | recipe | procedural_cavity.deform |
| 14 | 牙齿 | 内置口型按 Original 张口时牙片的一致运动校准上下排，再按嘴宽适配各自位移与旋转，不重复叠加竖向随唇浮动。原参考静止的牙齿保持原位；目标有小间隙时，下牙整组上移至首次接触，最多嘴宽的 30%，缺少独立上下牙则跳过。未校准的自定义或下颌动作保留有界随唇处理。接触可先收回校准动作中的前移，再按牙弓与嘴宽的较大值取 6.5% 额度整排后移，保留牙弓及上下行程；未校准动作仍采用 2.5% 共同后移及 4% 局部后移。检查局部修正是否引入新的三角面翻折；额度不足记录穿插，不向外推 Face，不缩放牙弓，不改变 Basis | 存在对应分区时执行 | recipe | procedural_constraints.close_dental_contact / procedural_contacts.oral_face |
| 15 | 口内接触 | 按唇缘相连拓扑选择 Face 接触面，包含斜面及内翻唇面；牙齿及口腔退回面部内侧，口腔唇缘固定。取消舌头随整排牙齿最前点后退；牙齿与舌头的接触只由实际三角面交叉触发。舌头上表面避开下口腔，Basis 同样检查；接触位移上限取舌长 12% 和口宽 8% 的较小值，同次修正反复检查共用额度；超出额度报告冲突 | 存在对应分区时执行 | recipe | procedural_contacts.finish / tongue_teeth / tongue_side |
| 16 | 写入 | 表情形态键、口腔联动和最终变形曲线一起保存 | 存在对应分区时执行 | recipe | procedural_generate.generate |
| 17 | 眼部数值 | 位移采样 × 当前眼宽；Z 再乘当前眼高与参考高宽比修正；17 个 XYZ 采样保存在 JSON | 按当前曲线与分区计算 | recipe.eyes.-1.upper | procedural_atoms.sampled |
| 18 | 眼部数值 | 位移采样 × 当前眼宽；Z 再乘当前眼高与参考高宽比修正；17 个 XYZ 采样保存在 JSON | 按当前曲线与分区计算 | recipe.eyes.-1.lower | procedural_atoms.sampled |
| 19 | 闭合规则 | 闭合=0；下眼参与=0.1；笑眼=0；平直=0。上缘不升、水平下缘不降且限幅；竖向眼角以转折为下降边界。笑眼上拱、なごみ平直，冲突不回退为相反曲率。 | 按当前曲线与分区计算 | recipe.eyes.-1 | procedural_atoms.solve |
| 20 | 眼部数值 | 位移采样 × 当前眼宽；Z 再乘当前眼高与参考高宽比修正；17 个 XYZ 采样保存在 JSON | 按当前曲线与分区计算 | recipe.eyes.1.upper | procedural_atoms.sampled |
| 21 | 眼部数值 | 位移采样 × 当前眼宽；Z 再乘当前眼高与参考高宽比修正；17 个 XYZ 采样保存在 JSON | 按当前曲线与分区计算 | recipe.eyes.1.lower | procedural_atoms.sampled |
| 22 | 闭合规则 | 闭合=0；下眼参与=0.1；笑眼=0；平直=0。上缘不升、水平下缘不降且限幅；竖向眼角以转折为下降边界。笑眼上拱、なごみ平直，冲突不回退为相反曲率。 | 按当前曲线与分区计算 | recipe.eyes.1 | procedural_atoms.solve |

数值定义：JSON 中 `expressions` 的同名项。

## 下眼上

| 顺序 | 阶段 | 计算准则 | 条件 | 数值路径 | 实现 |
| --- | --- | --- | --- | --- | --- |
| 1 | 对称策略 | 允许强制左右对称；正侧完成约束后直接镜像最终坐标到负侧，不再两侧平均。独立眼眉在相关顶点可配对时只计算正侧，不要求三角面划分相同。跨中线口型保留整体求解；活动顶点无法配对则跳过。镜像后的翻折数量写入报告 | 生成时开启强制对称 | can_symmetrize / special / relation | procedural_symmetry |
| 2 | 输入 | 按当前标记读取；已删除必要曲线所依赖的表情跳过 | 存在对应分区时执行 | recipe | procedural_rig.checkpoint |
| 3 | 眼部目标 | 按眼宽和眼高归一化；普通闭眼反射当前上眼缘曲率，笑闭眼保留上拱 | 存在对应分区时执行 | recipe | procedural_atoms.character_arc |
| 4 | 眼缘拟合 | 上下缘共用闭眼接缝；上缘向下、水平下缘不下降且上移上限 30%，笑眼弧顶额外 10%。闭眼内眼角允许下降，但不低于原始下眼睑横向主体，并略微上提。笑眼保持上拱，なごみ保持直线；边界冲突则跳过并说明原因 | 存在对应分区时执行 | recipe | procedural_atoms.solve |
| 5 | 皮肤求解 | 固定眼口控制点，沿 Face 邻接平滑传播 | 存在对应分区时执行 | recipe | procedural_skin.EyelidSkin.deform |
| 6 | 防破面 | 保持轮廓约束，限制局部修正，残余冲突写入报告 | 存在对应分区时执行 | recipe | procedural_constraints.finalize_skin |
| 7 | 眼部接触 | 沿用原始预设的眼层依次避让。高光、瞳孔、眼白依次执行整体深度位移，保留原始间距和形状；检查 Basis 到终点的 16 个权重。位移上限保留闭眼眼宽 24%、睁眼 35%，Basis 不变。整片睫毛向内贴合、向外避让，保留原始嵌入。未消除的接触与覆盖问题写入报告 | 存在对应分区时执行 | recipe | procedural_constraints.closed_eye_stack / procedural_lashes.lower_owned_upper_sections |
| 8 | 睫毛 | 拟合原始截面中心，沿最终 XYZ 闭眼曲线统一平移和旋转截面，保留厚度；眼尾连续延伸，不截断修正斜率。单根睫毛、双眼皮等共用最终截面变换，眉毛独立。竖向眼角平滑进入弯折区，之后执行贴脸与避让，并复查最终闭合线覆盖。まばたき下凹、笑い上拱且弧度延续到眼尾、なごみ优先水平平直；闭眼接合和下眼睑限幅更强。单根只读取已有标记 | 存在对应分区时执行 | recipe | procedural_lashes.style_band / fold_vertical_sections / finish_upper_sweep / deform / audit_closed_band |
| 9 | 风格设置 | 下眼睑参与量在可行闭合范围中选择接合位置，不改变下眼睑 30% 上移及笑眼弧顶额外 10% 的硬上限。笑眼弧度与形态保持调整曲线偏好，闭合、接触和厚度优先。组合、曲线写回沿用生成时保存的风格设置 | 存在对应分区时执行 | recipe | procedural_ui.generation_options / procedural_binding.styled_closure |
| 10 | 闭眼层次 | 下睫毛随实际下眼眶的连续位移和旋转运动。闭眼时将整条下睫毛的上下缘收在上睫毛投影内，再求解前后层次。Face 接触后复查并修正遮盖，最终悬空和覆盖不足单独报告 | 存在对应分区时执行 | recipe | procedural_lashes.follow_lower_rim / cover_lower_band / finish_closed_order |
| 11 | 眼角弯折 | 跟随下眼眶的强度随切线倾角连续增加，垂直达到 1，继续内斜仍保持 1。按原曲线弧长定位截面，避免竖向长度展开成内眼角横向拉长。普通闭眼保留内眼角跨度约束，なごみ和笑闭眼保持整条中心线的横向长度；单眼表情继承对应约束 | 存在对应分区时执行 | recipe | procedural_lashes.slope_follow_weight / finish_upper_sweep |
| 12 | 计算设备 | Windows NVIDIA CUDA 可用时，以双精度 GPU 内核求解三角面投影接触。小任务、缺少运行库、显存或调用失败时使用 CPU。两种设备共用几何规则、容差和可移动条件，报告设备、调用数与回退原因 | 存在对应分区时执行 | recipe | procedural_gpu.try_depth |
| 13 | 口腔 | 口内边界固定到实际唇缘，内部连续变形；强制镜像后重新贴合 Face 与 Mouth，避免两次表面插值产生小接缝 | 存在对应分区时执行 | recipe | procedural_cavity.deform |
| 14 | 牙齿 | 内置口型按 Original 张口时牙片的一致运动校准上下排，再按嘴宽适配各自位移与旋转，不重复叠加竖向随唇浮动。原参考静止的牙齿保持原位；目标有小间隙时，下牙整组上移至首次接触，最多嘴宽的 30%，缺少独立上下牙则跳过。未校准的自定义或下颌动作保留有界随唇处理。接触可先收回校准动作中的前移，再按牙弓与嘴宽的较大值取 6.5% 额度整排后移，保留牙弓及上下行程；未校准动作仍采用 2.5% 共同后移及 4% 局部后移。检查局部修正是否引入新的三角面翻折；额度不足记录穿插，不向外推 Face，不缩放牙弓，不改变 Basis | 存在对应分区时执行 | recipe | procedural_constraints.close_dental_contact / procedural_contacts.oral_face |
| 15 | 口内接触 | 按唇缘相连拓扑选择 Face 接触面，包含斜面及内翻唇面；牙齿及口腔退回面部内侧，口腔唇缘固定。取消舌头随整排牙齿最前点后退；牙齿与舌头的接触只由实际三角面交叉触发。舌头上表面避开下口腔，Basis 同样检查；接触位移上限取舌长 12% 和口宽 8% 的较小值，同次修正反复检查共用额度；超出额度报告冲突 | 存在对应分区时执行 | recipe | procedural_contacts.finish / tongue_teeth / tongue_side |
| 16 | 写入 | 表情形态键、口腔联动和最终变形曲线一起保存 | 存在对应分区时执行 | recipe | procedural_generate.generate |
| 17 | 眼部数值 | 位移采样 × 当前眼宽；Z 再乘当前眼高与参考高宽比修正；17 个 XYZ 采样保存在 JSON | 按当前曲线与分区计算 | recipe.eyes.-1.upper | procedural_atoms.sampled |
| 18 | 眼部数值 | 位移采样 × 当前眼宽；Z 再乘当前眼高与参考高宽比修正；17 个 XYZ 采样保存在 JSON | 按当前曲线与分区计算 | recipe.eyes.-1.lower | procedural_atoms.sampled |
| 19 | 闭合规则 | 闭合=0；下眼参与=0.1；笑眼=0；平直=0。上缘不升、水平下缘不降且限幅；竖向眼角以转折为下降边界。笑眼上拱、なごみ平直，冲突不回退为相反曲率。 | 按当前曲线与分区计算 | recipe.eyes.-1 | procedural_atoms.solve |
| 20 | 眼部数值 | 位移采样 × 当前眼宽；Z 再乘当前眼高与参考高宽比修正；17 个 XYZ 采样保存在 JSON | 按当前曲线与分区计算 | recipe.eyes.1.upper | procedural_atoms.sampled |
| 21 | 眼部数值 | 位移采样 × 当前眼宽；Z 再乘当前眼高与参考高宽比修正；17 个 XYZ 采样保存在 JSON | 按当前曲线与分区计算 | recipe.eyes.1.lower | procedural_atoms.sampled |
| 22 | 闭合规则 | 闭合=0；下眼参与=0.1；笑眼=0；平直=0。上缘不升、水平下缘不降且限幅；竖向眼角以转折为下降边界。笑眼上拱、なごみ平直，冲突不回退为相反曲率。 | 按当前曲线与分区计算 | recipe.eyes.1 | procedural_atoms.solve |

数值定义：JSON 中 `expressions` 的同名项。

## 睫下

| 顺序 | 阶段 | 计算准则 | 条件 | 数值路径 | 实现 |
| --- | --- | --- | --- | --- | --- |
| 1 | 对称策略 | 允许强制左右对称；正侧完成约束后直接镜像最终坐标到负侧，不再两侧平均。独立眼眉在相关顶点可配对时只计算正侧，不要求三角面划分相同。跨中线口型保留整体求解；活动顶点无法配对则跳过。镜像后的翻折数量写入报告 | 生成时开启强制对称 | can_symmetrize / special / relation | procedural_symmetry |
| 2 | 输入 | 按当前标记读取；已删除必要曲线所依赖的表情跳过 | 存在对应分区时执行 | recipe | procedural_rig.checkpoint |
| 3 | 眼部目标 | 按眼宽和眼高归一化；普通闭眼反射当前上眼缘曲率，笑闭眼保留上拱 | 存在对应分区时执行 | recipe | procedural_atoms.character_arc |
| 4 | 眼缘拟合 | 上下缘共用闭眼接缝；上缘向下、水平下缘不下降且上移上限 30%，笑眼弧顶额外 10%。闭眼内眼角允许下降，但不低于原始下眼睑横向主体，并略微上提。笑眼保持上拱，なごみ保持直线；边界冲突则跳过并说明原因 | 存在对应分区时执行 | recipe | procedural_atoms.solve |
| 5 | 皮肤求解 | 固定眼口控制点，沿 Face 邻接平滑传播 | 存在对应分区时执行 | recipe | procedural_skin.EyelidSkin.deform |
| 6 | 防破面 | 保持轮廓约束，限制局部修正，残余冲突写入报告 | 存在对应分区时执行 | recipe | procedural_constraints.finalize_skin |
| 7 | 眼部接触 | 沿用原始预设的眼层依次避让。高光、瞳孔、眼白依次执行整体深度位移，保留原始间距和形状；检查 Basis 到终点的 16 个权重。位移上限保留闭眼眼宽 24%、睁眼 35%，Basis 不变。整片睫毛向内贴合、向外避让，保留原始嵌入。未消除的接触与覆盖问题写入报告 | 存在对应分区时执行 | recipe | procedural_constraints.closed_eye_stack / procedural_lashes.lower_owned_upper_sections |
| 8 | 睫毛 | 拟合原始截面中心，沿最终 XYZ 闭眼曲线统一平移和旋转截面，保留厚度；眼尾连续延伸，不截断修正斜率。单根睫毛、双眼皮等共用最终截面变换，眉毛独立。竖向眼角平滑进入弯折区，之后执行贴脸与避让，并复查最终闭合线覆盖。まばたき下凹、笑い上拱且弧度延续到眼尾、なごみ优先水平平直；闭眼接合和下眼睑限幅更强。单根只读取已有标记 | 存在对应分区时执行 | recipe | procedural_lashes.style_band / fold_vertical_sections / finish_upper_sweep / deform / audit_closed_band |
| 9 | 风格设置 | 下眼睑参与量在可行闭合范围中选择接合位置，不改变下眼睑 30% 上移及笑眼弧顶额外 10% 的硬上限。笑眼弧度与形态保持调整曲线偏好，闭合、接触和厚度优先。组合、曲线写回沿用生成时保存的风格设置 | 存在对应分区时执行 | recipe | procedural_ui.generation_options / procedural_binding.styled_closure |
| 10 | 闭眼层次 | 下睫毛随实际下眼眶的连续位移和旋转运动。闭眼时将整条下睫毛的上下缘收在上睫毛投影内，再求解前后层次。Face 接触后复查并修正遮盖，最终悬空和覆盖不足单独报告 | 存在对应分区时执行 | recipe | procedural_lashes.follow_lower_rim / cover_lower_band / finish_closed_order |
| 11 | 眼角弯折 | 跟随下眼眶的强度随切线倾角连续增加，垂直达到 1，继续内斜仍保持 1。按原曲线弧长定位截面，避免竖向长度展开成内眼角横向拉长。普通闭眼保留内眼角跨度约束，なごみ和笑闭眼保持整条中心线的横向长度；单眼表情继承对应约束 | 存在对应分区时执行 | recipe | procedural_lashes.slope_follow_weight / finish_upper_sweep |
| 12 | 计算设备 | Windows NVIDIA CUDA 可用时，以双精度 GPU 内核求解三角面投影接触。小任务、缺少运行库、显存或调用失败时使用 CPU。两种设备共用几何规则、容差和可移动条件，报告设备、调用数与回退原因 | 存在对应分区时执行 | recipe | procedural_gpu.try_depth |
| 13 | 口腔 | 口内边界固定到实际唇缘，内部连续变形；强制镜像后重新贴合 Face 与 Mouth，避免两次表面插值产生小接缝 | 存在对应分区时执行 | recipe | procedural_cavity.deform |
| 14 | 牙齿 | 内置口型按 Original 张口时牙片的一致运动校准上下排，再按嘴宽适配各自位移与旋转，不重复叠加竖向随唇浮动。原参考静止的牙齿保持原位；目标有小间隙时，下牙整组上移至首次接触，最多嘴宽的 30%，缺少独立上下牙则跳过。未校准的自定义或下颌动作保留有界随唇处理。接触可先收回校准动作中的前移，再按牙弓与嘴宽的较大值取 6.5% 额度整排后移，保留牙弓及上下行程；未校准动作仍采用 2.5% 共同后移及 4% 局部后移。检查局部修正是否引入新的三角面翻折；额度不足记录穿插，不向外推 Face，不缩放牙弓，不改变 Basis | 存在对应分区时执行 | recipe | procedural_constraints.close_dental_contact / procedural_contacts.oral_face |
| 15 | 口内接触 | 按唇缘相连拓扑选择 Face 接触面，包含斜面及内翻唇面；牙齿及口腔退回面部内侧，口腔唇缘固定。取消舌头随整排牙齿最前点后退；牙齿与舌头的接触只由实际三角面交叉触发。舌头上表面避开下口腔，Basis 同样检查；接触位移上限取舌长 12% 和口宽 8% 的较小值，同次修正反复检查共用额度；超出额度报告冲突 | 存在对应分区时执行 | recipe | procedural_contacts.finish / tongue_teeth / tongue_side |
| 16 | 写入 | 表情形态键、口腔联动和最终变形曲线一起保存 | 存在对应分区时执行 | recipe | procedural_generate.generate |
| 17 | 眼部数值 | 位移采样 × 当前眼宽；Z 再乘当前眼高与参考高宽比修正；17 个 XYZ 采样保存在 JSON | 按当前曲线与分区计算 | recipe.eyes.-1.upper | procedural_atoms.sampled |
| 18 | 眼部数值 | 位移采样 × 当前眼宽；Z 再乘当前眼高与参考高宽比修正；17 个 XYZ 采样保存在 JSON | 按当前曲线与分区计算 | recipe.eyes.-1.lower | procedural_atoms.sampled |
| 19 | 闭合规则 | 闭合=0；下眼参与=0.1；笑眼=0；平直=0。上缘不升、水平下缘不降且限幅；竖向眼角以转折为下降边界。笑眼上拱、なごみ平直，冲突不回退为相反曲率。 | 按当前曲线与分区计算 | recipe.eyes.-1 | procedural_atoms.solve |
| 20 | 眼部数值 | 位移采样 × 当前眼宽；Z 再乘当前眼高与参考高宽比修正；17 个 XYZ 采样保存在 JSON | 按当前曲线与分区计算 | recipe.eyes.1.upper | procedural_atoms.sampled |
| 21 | 眼部数值 | 位移采样 × 当前眼宽；Z 再乘当前眼高与参考高宽比修正；17 个 XYZ 采样保存在 JSON | 按当前曲线与分区计算 | recipe.eyes.1.lower | procedural_atoms.sampled |
| 22 | 闭合规则 | 闭合=0；下眼参与=0.1；笑眼=0；平直=0。上缘不升、水平下缘不降且限幅；竖向眼角以转折为下降边界。笑眼上拱、なごみ平直，冲突不回退为相反曲率。 | 按当前曲线与分区计算 | recipe.eyes.1 | procedural_atoms.solve |

数值定义：JSON 中 `expressions` 的同名项。

## あ

| 顺序 | 阶段 | 计算准则 | 条件 | 数值路径 | 实现 |
| --- | --- | --- | --- | --- | --- |
| 1 | 对称策略 | 允许强制左右对称；正侧完成约束后直接镜像最终坐标到负侧，不再两侧平均。独立眼眉在相关顶点可配对时只计算正侧，不要求三角面划分相同。跨中线口型保留整体求解；活动顶点无法配对则跳过。镜像后的翻折数量写入报告 | 生成时开启强制对称 | can_symmetrize / special / relation | procedural_symmetry |
| 2 | 输入 | 按当前标记读取；已删除必要曲线所依赖的表情跳过 | 存在对应分区时执行 | recipe | procedural_rig.checkpoint |
| 3 | 嘴型目标 | 按口宽适配目标轮廓，保留上下唇拓扑归属 | 存在对应分区时执行 | recipe | procedural_atoms.mouth_outline |
| 4 | 舌头目标 | 普通口型保留 Original 舌头的整体位移和旋转。てへぺろ按原曲线侧伸，ぺろっ居中下卷；截面沿等弧长曲线弯曲，过厚或过宽的目标舌头在吐舌形态中按原参考与嘴宽的比例等比缩小，不修改生成的 Basis。尺寸检查保留旋转和平移，限制额外边长 ≤ Basis 的 1.04 倍；沿去除整体旋转后的方向检查 X/Y 跨度 ≤ 1.08/1.04 倍，Z 跨度 ≤ 原厚度 + 舌长的 28%。出口局部最多变薄 15% | 存在对应分区时执行 | recipe | procedural_tongue.reference_pose / deform / limit_size |
| 5 | 人中与唇周 | 开口沿当前 Face 的局部轮廓采样有限深度变化，不沿初始切线无限外推；唇缘邻近面片共同平移，保留原斜面与厚度，再向周围脸皮平滑过渡 | 存在对应分区时执行 | recipe | procedural_lips.surface_motion / deform |
| 6 | 皮肤求解 | 固定眼口控制点，沿 Face 邻接平滑传播 | 存在对应分区时执行 | recipe | procedural_skin.EyelidSkin.deform |
| 7 | 防破面 | 保持轮廓约束，限制局部修正，残余冲突写入报告 | 存在对应分区时执行 | recipe | procedural_constraints.finalize_skin |
| 8 | 风格设置 | 下眼睑参与量在可行闭合范围中选择接合位置，不改变下眼睑 30% 上移及笑眼弧顶额外 10% 的硬上限。笑眼弧度与形态保持调整曲线偏好，闭合、接触和厚度优先。组合、曲线写回沿用生成时保存的风格设置 | 存在对应分区时执行 | recipe | procedural_ui.generation_options / procedural_binding.styled_closure |
| 9 | 闭眼层次 | 下睫毛随实际下眼眶的连续位移和旋转运动。闭眼时将整条下睫毛的上下缘收在上睫毛投影内，再求解前后层次。Face 接触后复查并修正遮盖，最终悬空和覆盖不足单独报告 | 存在对应分区时执行 | recipe | procedural_lashes.follow_lower_rim / cover_lower_band / finish_closed_order |
| 10 | 计算设备 | Windows NVIDIA CUDA 可用时，以双精度 GPU 内核求解三角面投影接触。小任务、缺少运行库、显存或调用失败时使用 CPU。两种设备共用几何规则、容差和可移动条件，报告设备、调用数与回退原因 | 存在对应分区时执行 | recipe | procedural_gpu.try_depth |
| 11 | 口腔 | 口内边界固定到实际唇缘，内部连续变形；强制镜像后重新贴合 Face 与 Mouth，避免两次表面插值产生小接缝 | 存在对应分区时执行 | recipe | procedural_cavity.deform |
| 12 | 牙齿 | 内置口型按 Original 张口时牙片的一致运动校准上下排，再按嘴宽适配各自位移与旋转，不重复叠加竖向随唇浮动。原参考静止的牙齿保持原位；目标有小间隙时，下牙整组上移至首次接触，最多嘴宽的 30%，缺少独立上下牙则跳过。未校准的自定义或下颌动作保留有界随唇处理。接触可先收回校准动作中的前移，再按牙弓与嘴宽的较大值取 6.5% 额度整排后移，保留牙弓及上下行程；未校准动作仍采用 2.5% 共同后移及 4% 局部后移。检查局部修正是否引入新的三角面翻折；额度不足记录穿插，不向外推 Face，不缩放牙弓，不改变 Basis | 存在对应分区时执行 | recipe | procedural_constraints.close_dental_contact / procedural_contacts.oral_face |
| 13 | 吐舌接触 | 检查外露下表面和外侧面；独立舌头整体平移避开 Face，避免把外露截面拉离舌根；焊接舌头保留局部处理及最终尺寸限制，冲突写入报告 | 存在对应分区时执行 | recipe | procedural_tongue.keep_exterior |
| 14 | 口内接触 | 按唇缘相连拓扑选择 Face 接触面，包含斜面及内翻唇面；牙齿及口腔退回面部内侧，口腔唇缘固定。取消舌头随整排牙齿最前点后退；牙齿与舌头的接触只由实际三角面交叉触发。舌头上表面避开下口腔，Basis 同样检查；接触位移上限取舌长 12% 和口宽 8% 的较小值，同次修正反复检查共用额度；超出额度报告冲突 | 存在对应分区时执行 | recipe | procedural_contacts.finish / tongue_teeth / tongue_side |
| 15 | 写入 | 表情形态键、口腔联动和最终变形曲线一起保存 | 存在对应分区时执行 | recipe | procedural_generate.generate |
| 16 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.mouth | procedural_atoms.merge |
| 17 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.mouth_reference | procedural_atoms.merge |
| 18 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.tongue | procedural_atoms.merge |
| 19 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.oral | procedural_atoms.merge |

数值定义：JSON 中 `expressions` 的同名项。

## い

| 顺序 | 阶段 | 计算准则 | 条件 | 数值路径 | 实现 |
| --- | --- | --- | --- | --- | --- |
| 1 | 对称策略 | 允许强制左右对称；正侧完成约束后直接镜像最终坐标到负侧，不再两侧平均。独立眼眉在相关顶点可配对时只计算正侧，不要求三角面划分相同。跨中线口型保留整体求解；活动顶点无法配对则跳过。镜像后的翻折数量写入报告 | 生成时开启强制对称 | can_symmetrize / special / relation | procedural_symmetry |
| 2 | 输入 | 按当前标记读取；已删除必要曲线所依赖的表情跳过 | 存在对应分区时执行 | recipe | procedural_rig.checkpoint |
| 3 | 嘴型目标 | 按口宽适配目标轮廓，保留上下唇拓扑归属 | 存在对应分区时执行 | recipe | procedural_atoms.mouth_outline |
| 4 | 舌头目标 | 普通口型保留 Original 舌头的整体位移和旋转。てへぺろ按原曲线侧伸，ぺろっ居中下卷；截面沿等弧长曲线弯曲，过厚或过宽的目标舌头在吐舌形态中按原参考与嘴宽的比例等比缩小，不修改生成的 Basis。尺寸检查保留旋转和平移，限制额外边长 ≤ Basis 的 1.04 倍；沿去除整体旋转后的方向检查 X/Y 跨度 ≤ 1.08/1.04 倍，Z 跨度 ≤ 原厚度 + 舌长的 28%。出口局部最多变薄 15% | 存在对应分区时执行 | recipe | procedural_tongue.reference_pose / deform / limit_size |
| 5 | 人中与唇周 | 开口沿当前 Face 的局部轮廓采样有限深度变化，不沿初始切线无限外推；唇缘邻近面片共同平移，保留原斜面与厚度，再向周围脸皮平滑过渡 | 存在对应分区时执行 | recipe | procedural_lips.surface_motion / deform |
| 6 | 皮肤求解 | 固定眼口控制点，沿 Face 邻接平滑传播 | 存在对应分区时执行 | recipe | procedural_skin.EyelidSkin.deform |
| 7 | 防破面 | 保持轮廓约束，限制局部修正，残余冲突写入报告 | 存在对应分区时执行 | recipe | procedural_constraints.finalize_skin |
| 8 | 风格设置 | 下眼睑参与量在可行闭合范围中选择接合位置，不改变下眼睑 30% 上移及笑眼弧顶额外 10% 的硬上限。笑眼弧度与形态保持调整曲线偏好，闭合、接触和厚度优先。组合、曲线写回沿用生成时保存的风格设置 | 存在对应分区时执行 | recipe | procedural_ui.generation_options / procedural_binding.styled_closure |
| 9 | 闭眼层次 | 下睫毛随实际下眼眶的连续位移和旋转运动。闭眼时将整条下睫毛的上下缘收在上睫毛投影内，再求解前后层次。Face 接触后复查并修正遮盖，最终悬空和覆盖不足单独报告 | 存在对应分区时执行 | recipe | procedural_lashes.follow_lower_rim / cover_lower_band / finish_closed_order |
| 10 | 计算设备 | Windows NVIDIA CUDA 可用时，以双精度 GPU 内核求解三角面投影接触。小任务、缺少运行库、显存或调用失败时使用 CPU。两种设备共用几何规则、容差和可移动条件，报告设备、调用数与回退原因 | 存在对应分区时执行 | recipe | procedural_gpu.try_depth |
| 11 | 口腔 | 口内边界固定到实际唇缘，内部连续变形；强制镜像后重新贴合 Face 与 Mouth，避免两次表面插值产生小接缝 | 存在对应分区时执行 | recipe | procedural_cavity.deform |
| 12 | 牙齿 | 内置口型按 Original 张口时牙片的一致运动校准上下排，再按嘴宽适配各自位移与旋转，不重复叠加竖向随唇浮动。原参考静止的牙齿保持原位；目标有小间隙时，下牙整组上移至首次接触，最多嘴宽的 30%，缺少独立上下牙则跳过。未校准的自定义或下颌动作保留有界随唇处理。接触可先收回校准动作中的前移，再按牙弓与嘴宽的较大值取 6.5% 额度整排后移，保留牙弓及上下行程；未校准动作仍采用 2.5% 共同后移及 4% 局部后移。检查局部修正是否引入新的三角面翻折；额度不足记录穿插，不向外推 Face，不缩放牙弓，不改变 Basis | 存在对应分区时执行 | recipe | procedural_constraints.close_dental_contact / procedural_contacts.oral_face |
| 13 | 吐舌接触 | 检查外露下表面和外侧面；独立舌头整体平移避开 Face，避免把外露截面拉离舌根；焊接舌头保留局部处理及最终尺寸限制，冲突写入报告 | 存在对应分区时执行 | recipe | procedural_tongue.keep_exterior |
| 14 | 口内接触 | 按唇缘相连拓扑选择 Face 接触面，包含斜面及内翻唇面；牙齿及口腔退回面部内侧，口腔唇缘固定。取消舌头随整排牙齿最前点后退；牙齿与舌头的接触只由实际三角面交叉触发。舌头上表面避开下口腔，Basis 同样检查；接触位移上限取舌长 12% 和口宽 8% 的较小值，同次修正反复检查共用额度；超出额度报告冲突 | 存在对应分区时执行 | recipe | procedural_contacts.finish / tongue_teeth / tongue_side |
| 15 | 写入 | 表情形态键、口腔联动和最终变形曲线一起保存 | 存在对应分区时执行 | recipe | procedural_generate.generate |
| 16 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.mouth | procedural_atoms.merge |
| 17 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.mouth_reference | procedural_atoms.merge |
| 18 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.tongue | procedural_atoms.merge |
| 19 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.oral | procedural_atoms.merge |

数值定义：JSON 中 `expressions` 的同名项。

## う

| 顺序 | 阶段 | 计算准则 | 条件 | 数值路径 | 实现 |
| --- | --- | --- | --- | --- | --- |
| 1 | 对称策略 | 允许强制左右对称；正侧完成约束后直接镜像最终坐标到负侧，不再两侧平均。独立眼眉在相关顶点可配对时只计算正侧，不要求三角面划分相同。跨中线口型保留整体求解；活动顶点无法配对则跳过。镜像后的翻折数量写入报告 | 生成时开启强制对称 | can_symmetrize / special / relation | procedural_symmetry |
| 2 | 输入 | 按当前标记读取；已删除必要曲线所依赖的表情跳过 | 存在对应分区时执行 | recipe | procedural_rig.checkpoint |
| 3 | 嘴型目标 | 按口宽适配目标轮廓，保留上下唇拓扑归属 | 存在对应分区时执行 | recipe | procedural_atoms.mouth_outline |
| 4 | 舌头目标 | 普通口型保留 Original 舌头的整体位移和旋转。てへぺろ按原曲线侧伸，ぺろっ居中下卷；截面沿等弧长曲线弯曲，过厚或过宽的目标舌头在吐舌形态中按原参考与嘴宽的比例等比缩小，不修改生成的 Basis。尺寸检查保留旋转和平移，限制额外边长 ≤ Basis 的 1.04 倍；沿去除整体旋转后的方向检查 X/Y 跨度 ≤ 1.08/1.04 倍，Z 跨度 ≤ 原厚度 + 舌长的 28%。出口局部最多变薄 15% | 存在对应分区时执行 | recipe | procedural_tongue.reference_pose / deform / limit_size |
| 5 | 人中与唇周 | 开口沿当前 Face 的局部轮廓采样有限深度变化，不沿初始切线无限外推；唇缘邻近面片共同平移，保留原斜面与厚度，再向周围脸皮平滑过渡 | 存在对应分区时执行 | recipe | procedural_lips.surface_motion / deform |
| 6 | 皮肤求解 | 固定眼口控制点，沿 Face 邻接平滑传播 | 存在对应分区时执行 | recipe | procedural_skin.EyelidSkin.deform |
| 7 | 防破面 | 保持轮廓约束，限制局部修正，残余冲突写入报告 | 存在对应分区时执行 | recipe | procedural_constraints.finalize_skin |
| 8 | 风格设置 | 下眼睑参与量在可行闭合范围中选择接合位置，不改变下眼睑 30% 上移及笑眼弧顶额外 10% 的硬上限。笑眼弧度与形态保持调整曲线偏好，闭合、接触和厚度优先。组合、曲线写回沿用生成时保存的风格设置 | 存在对应分区时执行 | recipe | procedural_ui.generation_options / procedural_binding.styled_closure |
| 9 | 闭眼层次 | 下睫毛随实际下眼眶的连续位移和旋转运动。闭眼时将整条下睫毛的上下缘收在上睫毛投影内，再求解前后层次。Face 接触后复查并修正遮盖，最终悬空和覆盖不足单独报告 | 存在对应分区时执行 | recipe | procedural_lashes.follow_lower_rim / cover_lower_band / finish_closed_order |
| 10 | 计算设备 | Windows NVIDIA CUDA 可用时，以双精度 GPU 内核求解三角面投影接触。小任务、缺少运行库、显存或调用失败时使用 CPU。两种设备共用几何规则、容差和可移动条件，报告设备、调用数与回退原因 | 存在对应分区时执行 | recipe | procedural_gpu.try_depth |
| 11 | 口腔 | 口内边界固定到实际唇缘，内部连续变形；强制镜像后重新贴合 Face 与 Mouth，避免两次表面插值产生小接缝 | 存在对应分区时执行 | recipe | procedural_cavity.deform |
| 12 | 牙齿 | 内置口型按 Original 张口时牙片的一致运动校准上下排，再按嘴宽适配各自位移与旋转，不重复叠加竖向随唇浮动。原参考静止的牙齿保持原位；目标有小间隙时，下牙整组上移至首次接触，最多嘴宽的 30%，缺少独立上下牙则跳过。未校准的自定义或下颌动作保留有界随唇处理。接触可先收回校准动作中的前移，再按牙弓与嘴宽的较大值取 6.5% 额度整排后移，保留牙弓及上下行程；未校准动作仍采用 2.5% 共同后移及 4% 局部后移。检查局部修正是否引入新的三角面翻折；额度不足记录穿插，不向外推 Face，不缩放牙弓，不改变 Basis | 存在对应分区时执行 | recipe | procedural_constraints.close_dental_contact / procedural_contacts.oral_face |
| 13 | 吐舌接触 | 检查外露下表面和外侧面；独立舌头整体平移避开 Face，避免把外露截面拉离舌根；焊接舌头保留局部处理及最终尺寸限制，冲突写入报告 | 存在对应分区时执行 | recipe | procedural_tongue.keep_exterior |
| 14 | 口内接触 | 按唇缘相连拓扑选择 Face 接触面，包含斜面及内翻唇面；牙齿及口腔退回面部内侧，口腔唇缘固定。取消舌头随整排牙齿最前点后退；牙齿与舌头的接触只由实际三角面交叉触发。舌头上表面避开下口腔，Basis 同样检查；接触位移上限取舌长 12% 和口宽 8% 的较小值，同次修正反复检查共用额度；超出额度报告冲突 | 存在对应分区时执行 | recipe | procedural_contacts.finish / tongue_teeth / tongue_side |
| 15 | 写入 | 表情形态键、口腔联动和最终变形曲线一起保存 | 存在对应分区时执行 | recipe | procedural_generate.generate |
| 16 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.mouth | procedural_atoms.merge |
| 17 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.mouth_reference | procedural_atoms.merge |
| 18 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.tongue | procedural_atoms.merge |
| 19 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.oral | procedural_atoms.merge |

数值定义：JSON 中 `expressions` 的同名项。

## え

| 顺序 | 阶段 | 计算准则 | 条件 | 数值路径 | 实现 |
| --- | --- | --- | --- | --- | --- |
| 1 | 对称策略 | 允许强制左右对称；正侧完成约束后直接镜像最终坐标到负侧，不再两侧平均。独立眼眉在相关顶点可配对时只计算正侧，不要求三角面划分相同。跨中线口型保留整体求解；活动顶点无法配对则跳过。镜像后的翻折数量写入报告 | 生成时开启强制对称 | can_symmetrize / special / relation | procedural_symmetry |
| 2 | 输入 | 按当前标记读取；已删除必要曲线所依赖的表情跳过 | 存在对应分区时执行 | recipe | procedural_rig.checkpoint |
| 3 | 嘴型目标 | 按口宽适配目标轮廓，保留上下唇拓扑归属 | 存在对应分区时执行 | recipe | procedural_atoms.mouth_outline |
| 4 | 舌头目标 | 普通口型保留 Original 舌头的整体位移和旋转。てへぺろ按原曲线侧伸，ぺろっ居中下卷；截面沿等弧长曲线弯曲，过厚或过宽的目标舌头在吐舌形态中按原参考与嘴宽的比例等比缩小，不修改生成的 Basis。尺寸检查保留旋转和平移，限制额外边长 ≤ Basis 的 1.04 倍；沿去除整体旋转后的方向检查 X/Y 跨度 ≤ 1.08/1.04 倍，Z 跨度 ≤ 原厚度 + 舌长的 28%。出口局部最多变薄 15% | 存在对应分区时执行 | recipe | procedural_tongue.reference_pose / deform / limit_size |
| 5 | 人中与唇周 | 开口沿当前 Face 的局部轮廓采样有限深度变化，不沿初始切线无限外推；唇缘邻近面片共同平移，保留原斜面与厚度，再向周围脸皮平滑过渡 | 存在对应分区时执行 | recipe | procedural_lips.surface_motion / deform |
| 6 | 皮肤求解 | 固定眼口控制点，沿 Face 邻接平滑传播 | 存在对应分区时执行 | recipe | procedural_skin.EyelidSkin.deform |
| 7 | 防破面 | 保持轮廓约束，限制局部修正，残余冲突写入报告 | 存在对应分区时执行 | recipe | procedural_constraints.finalize_skin |
| 8 | 风格设置 | 下眼睑参与量在可行闭合范围中选择接合位置，不改变下眼睑 30% 上移及笑眼弧顶额外 10% 的硬上限。笑眼弧度与形态保持调整曲线偏好，闭合、接触和厚度优先。组合、曲线写回沿用生成时保存的风格设置 | 存在对应分区时执行 | recipe | procedural_ui.generation_options / procedural_binding.styled_closure |
| 9 | 闭眼层次 | 下睫毛随实际下眼眶的连续位移和旋转运动。闭眼时将整条下睫毛的上下缘收在上睫毛投影内，再求解前后层次。Face 接触后复查并修正遮盖，最终悬空和覆盖不足单独报告 | 存在对应分区时执行 | recipe | procedural_lashes.follow_lower_rim / cover_lower_band / finish_closed_order |
| 10 | 计算设备 | Windows NVIDIA CUDA 可用时，以双精度 GPU 内核求解三角面投影接触。小任务、缺少运行库、显存或调用失败时使用 CPU。两种设备共用几何规则、容差和可移动条件，报告设备、调用数与回退原因 | 存在对应分区时执行 | recipe | procedural_gpu.try_depth |
| 11 | 口腔 | 口内边界固定到实际唇缘，内部连续变形；强制镜像后重新贴合 Face 与 Mouth，避免两次表面插值产生小接缝 | 存在对应分区时执行 | recipe | procedural_cavity.deform |
| 12 | 牙齿 | 内置口型按 Original 张口时牙片的一致运动校准上下排，再按嘴宽适配各自位移与旋转，不重复叠加竖向随唇浮动。原参考静止的牙齿保持原位；目标有小间隙时，下牙整组上移至首次接触，最多嘴宽的 30%，缺少独立上下牙则跳过。未校准的自定义或下颌动作保留有界随唇处理。接触可先收回校准动作中的前移，再按牙弓与嘴宽的较大值取 6.5% 额度整排后移，保留牙弓及上下行程；未校准动作仍采用 2.5% 共同后移及 4% 局部后移。检查局部修正是否引入新的三角面翻折；额度不足记录穿插，不向外推 Face，不缩放牙弓，不改变 Basis | 存在对应分区时执行 | recipe | procedural_constraints.close_dental_contact / procedural_contacts.oral_face |
| 13 | 吐舌接触 | 检查外露下表面和外侧面；独立舌头整体平移避开 Face，避免把外露截面拉离舌根；焊接舌头保留局部处理及最终尺寸限制，冲突写入报告 | 存在对应分区时执行 | recipe | procedural_tongue.keep_exterior |
| 14 | 口内接触 | 按唇缘相连拓扑选择 Face 接触面，包含斜面及内翻唇面；牙齿及口腔退回面部内侧，口腔唇缘固定。取消舌头随整排牙齿最前点后退；牙齿与舌头的接触只由实际三角面交叉触发。舌头上表面避开下口腔，Basis 同样检查；接触位移上限取舌长 12% 和口宽 8% 的较小值，同次修正反复检查共用额度；超出额度报告冲突 | 存在对应分区时执行 | recipe | procedural_contacts.finish / tongue_teeth / tongue_side |
| 15 | 写入 | 表情形态键、口腔联动和最终变形曲线一起保存 | 存在对应分区时执行 | recipe | procedural_generate.generate |
| 16 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.mouth | procedural_atoms.merge |
| 17 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.mouth_reference | procedural_atoms.merge |
| 18 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.tongue | procedural_atoms.merge |
| 19 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.oral | procedural_atoms.merge |

数值定义：JSON 中 `expressions` 的同名项。

## お

| 顺序 | 阶段 | 计算准则 | 条件 | 数值路径 | 实现 |
| --- | --- | --- | --- | --- | --- |
| 1 | 对称策略 | 允许强制左右对称；正侧完成约束后直接镜像最终坐标到负侧，不再两侧平均。独立眼眉在相关顶点可配对时只计算正侧，不要求三角面划分相同。跨中线口型保留整体求解；活动顶点无法配对则跳过。镜像后的翻折数量写入报告 | 生成时开启强制对称 | can_symmetrize / special / relation | procedural_symmetry |
| 2 | 输入 | 按当前标记读取；已删除必要曲线所依赖的表情跳过 | 存在对应分区时执行 | recipe | procedural_rig.checkpoint |
| 3 | 嘴型目标 | 按口宽适配目标轮廓，保留上下唇拓扑归属 | 存在对应分区时执行 | recipe | procedural_atoms.mouth_outline |
| 4 | 舌头目标 | 普通口型保留 Original 舌头的整体位移和旋转。てへぺろ按原曲线侧伸，ぺろっ居中下卷；截面沿等弧长曲线弯曲，过厚或过宽的目标舌头在吐舌形态中按原参考与嘴宽的比例等比缩小，不修改生成的 Basis。尺寸检查保留旋转和平移，限制额外边长 ≤ Basis 的 1.04 倍；沿去除整体旋转后的方向检查 X/Y 跨度 ≤ 1.08/1.04 倍，Z 跨度 ≤ 原厚度 + 舌长的 28%。出口局部最多变薄 15% | 存在对应分区时执行 | recipe | procedural_tongue.reference_pose / deform / limit_size |
| 5 | 人中与唇周 | 开口沿当前 Face 的局部轮廓采样有限深度变化，不沿初始切线无限外推；唇缘邻近面片共同平移，保留原斜面与厚度，再向周围脸皮平滑过渡 | 存在对应分区时执行 | recipe | procedural_lips.surface_motion / deform |
| 6 | 皮肤求解 | 固定眼口控制点，沿 Face 邻接平滑传播 | 存在对应分区时执行 | recipe | procedural_skin.EyelidSkin.deform |
| 7 | 防破面 | 保持轮廓约束，限制局部修正，残余冲突写入报告 | 存在对应分区时执行 | recipe | procedural_constraints.finalize_skin |
| 8 | 风格设置 | 下眼睑参与量在可行闭合范围中选择接合位置，不改变下眼睑 30% 上移及笑眼弧顶额外 10% 的硬上限。笑眼弧度与形态保持调整曲线偏好，闭合、接触和厚度优先。组合、曲线写回沿用生成时保存的风格设置 | 存在对应分区时执行 | recipe | procedural_ui.generation_options / procedural_binding.styled_closure |
| 9 | 闭眼层次 | 下睫毛随实际下眼眶的连续位移和旋转运动。闭眼时将整条下睫毛的上下缘收在上睫毛投影内，再求解前后层次。Face 接触后复查并修正遮盖，最终悬空和覆盖不足单独报告 | 存在对应分区时执行 | recipe | procedural_lashes.follow_lower_rim / cover_lower_band / finish_closed_order |
| 10 | 计算设备 | Windows NVIDIA CUDA 可用时，以双精度 GPU 内核求解三角面投影接触。小任务、缺少运行库、显存或调用失败时使用 CPU。两种设备共用几何规则、容差和可移动条件，报告设备、调用数与回退原因 | 存在对应分区时执行 | recipe | procedural_gpu.try_depth |
| 11 | 口腔 | 口内边界固定到实际唇缘，内部连续变形；强制镜像后重新贴合 Face 与 Mouth，避免两次表面插值产生小接缝 | 存在对应分区时执行 | recipe | procedural_cavity.deform |
| 12 | 牙齿 | 内置口型按 Original 张口时牙片的一致运动校准上下排，再按嘴宽适配各自位移与旋转，不重复叠加竖向随唇浮动。原参考静止的牙齿保持原位；目标有小间隙时，下牙整组上移至首次接触，最多嘴宽的 30%，缺少独立上下牙则跳过。未校准的自定义或下颌动作保留有界随唇处理。接触可先收回校准动作中的前移，再按牙弓与嘴宽的较大值取 6.5% 额度整排后移，保留牙弓及上下行程；未校准动作仍采用 2.5% 共同后移及 4% 局部后移。检查局部修正是否引入新的三角面翻折；额度不足记录穿插，不向外推 Face，不缩放牙弓，不改变 Basis | 存在对应分区时执行 | recipe | procedural_constraints.close_dental_contact / procedural_contacts.oral_face |
| 13 | 吐舌接触 | 检查外露下表面和外侧面；独立舌头整体平移避开 Face，避免把外露截面拉离舌根；焊接舌头保留局部处理及最终尺寸限制，冲突写入报告 | 存在对应分区时执行 | recipe | procedural_tongue.keep_exterior |
| 14 | 口内接触 | 按唇缘相连拓扑选择 Face 接触面，包含斜面及内翻唇面；牙齿及口腔退回面部内侧，口腔唇缘固定。取消舌头随整排牙齿最前点后退；牙齿与舌头的接触只由实际三角面交叉触发。舌头上表面避开下口腔，Basis 同样检查；接触位移上限取舌长 12% 和口宽 8% 的较小值，同次修正反复检查共用额度；超出额度报告冲突 | 存在对应分区时执行 | recipe | procedural_contacts.finish / tongue_teeth / tongue_side |
| 15 | 写入 | 表情形态键、口腔联动和最终变形曲线一起保存 | 存在对应分区时执行 | recipe | procedural_generate.generate |
| 16 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.mouth | procedural_atoms.merge |
| 17 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.mouth_reference | procedural_atoms.merge |
| 18 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.tongue | procedural_atoms.merge |
| 19 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.oral | procedural_atoms.merge |

数值定义：JSON 中 `expressions` 的同名项。

## にやり

| 顺序 | 阶段 | 计算准则 | 条件 | 数值路径 | 实现 |
| --- | --- | --- | --- | --- | --- |
| 1 | 对称策略 | 允许强制左右对称；正侧完成约束后直接镜像最终坐标到负侧，不再两侧平均。独立眼眉在相关顶点可配对时只计算正侧，不要求三角面划分相同。跨中线口型保留整体求解；活动顶点无法配对则跳过。镜像后的翻折数量写入报告 | 生成时开启强制对称 | can_symmetrize / special / relation | procedural_symmetry |
| 2 | 输入 | 按当前标记读取；已删除必要曲线所依赖的表情跳过 | 存在对应分区时执行 | recipe | procedural_rig.checkpoint |
| 3 | 嘴型目标 | 按口宽适配目标轮廓，保留上下唇拓扑归属 | 存在对应分区时执行 | recipe | procedural_atoms.mouth_outline |
| 4 | 人中与唇周 | 开口沿当前 Face 的局部轮廓采样有限深度变化，不沿初始切线无限外推；唇缘邻近面片共同平移，保留原斜面与厚度，再向周围脸皮平滑过渡 | 存在对应分区时执行 | recipe | procedural_lips.surface_motion / deform |
| 5 | 皮肤求解 | 固定眼口控制点，沿 Face 邻接平滑传播 | 存在对应分区时执行 | recipe | procedural_skin.EyelidSkin.deform |
| 6 | 防破面 | 保持轮廓约束，限制局部修正，残余冲突写入报告 | 存在对应分区时执行 | recipe | procedural_constraints.finalize_skin |
| 7 | 风格设置 | 下眼睑参与量在可行闭合范围中选择接合位置，不改变下眼睑 30% 上移及笑眼弧顶额外 10% 的硬上限。笑眼弧度与形态保持调整曲线偏好，闭合、接触和厚度优先。组合、曲线写回沿用生成时保存的风格设置 | 存在对应分区时执行 | recipe | procedural_ui.generation_options / procedural_binding.styled_closure |
| 8 | 闭眼层次 | 下睫毛随实际下眼眶的连续位移和旋转运动。闭眼时将整条下睫毛的上下缘收在上睫毛投影内，再求解前后层次。Face 接触后复查并修正遮盖，最终悬空和覆盖不足单独报告 | 存在对应分区时执行 | recipe | procedural_lashes.follow_lower_rim / cover_lower_band / finish_closed_order |
| 9 | 计算设备 | Windows NVIDIA CUDA 可用时，以双精度 GPU 内核求解三角面投影接触。小任务、缺少运行库、显存或调用失败时使用 CPU。两种设备共用几何规则、容差和可移动条件，报告设备、调用数与回退原因 | 存在对应分区时执行 | recipe | procedural_gpu.try_depth |
| 10 | 口腔 | 口内边界固定到实际唇缘，内部连续变形；强制镜像后重新贴合 Face 与 Mouth，避免两次表面插值产生小接缝 | 存在对应分区时执行 | recipe | procedural_cavity.deform |
| 11 | 牙齿 | 内置口型按 Original 张口时牙片的一致运动校准上下排，再按嘴宽适配各自位移与旋转，不重复叠加竖向随唇浮动。原参考静止的牙齿保持原位；目标有小间隙时，下牙整组上移至首次接触，最多嘴宽的 30%，缺少独立上下牙则跳过。未校准的自定义或下颌动作保留有界随唇处理。接触可先收回校准动作中的前移，再按牙弓与嘴宽的较大值取 6.5% 额度整排后移，保留牙弓及上下行程；未校准动作仍采用 2.5% 共同后移及 4% 局部后移。检查局部修正是否引入新的三角面翻折；额度不足记录穿插，不向外推 Face，不缩放牙弓，不改变 Basis | 存在对应分区时执行 | recipe | procedural_constraints.close_dental_contact / procedural_contacts.oral_face |
| 12 | 口内接触 | 按唇缘相连拓扑选择 Face 接触面，包含斜面及内翻唇面；牙齿及口腔退回面部内侧，口腔唇缘固定。取消舌头随整排牙齿最前点后退；牙齿与舌头的接触只由实际三角面交叉触发。舌头上表面避开下口腔，Basis 同样检查；接触位移上限取舌长 12% 和口宽 8% 的较小值，同次修正反复检查共用额度；超出额度报告冲突 | 存在对应分区时执行 | recipe | procedural_contacts.finish / tongue_teeth / tongue_side |
| 13 | 写入 | 表情形态键、口腔联动和最终变形曲线一起保存 | 存在对应分区时执行 | recipe | procedural_generate.generate |
| 14 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.mouth | procedural_atoms.merge |
| 15 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.mouth_reference | procedural_atoms.merge |
| 16 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.oral | procedural_atoms.merge |

数值定义：JSON 中 `expressions` 的同名项。

## ワ

| 顺序 | 阶段 | 计算准则 | 条件 | 数值路径 | 实现 |
| --- | --- | --- | --- | --- | --- |
| 1 | 对称策略 | 允许强制左右对称；正侧完成约束后直接镜像最终坐标到负侧，不再两侧平均。独立眼眉在相关顶点可配对时只计算正侧，不要求三角面划分相同。跨中线口型保留整体求解；活动顶点无法配对则跳过。镜像后的翻折数量写入报告 | 生成时开启强制对称 | can_symmetrize / special / relation | procedural_symmetry |
| 2 | 输入 | 按当前标记读取；已删除必要曲线所依赖的表情跳过 | 存在对应分区时执行 | recipe | procedural_rig.checkpoint |
| 3 | 嘴型目标 | 按口宽适配目标轮廓，保留上下唇拓扑归属 | 存在对应分区时执行 | recipe | procedural_atoms.mouth_outline |
| 4 | 舌头目标 | 普通口型保留 Original 舌头的整体位移和旋转。てへぺろ按原曲线侧伸，ぺろっ居中下卷；截面沿等弧长曲线弯曲，过厚或过宽的目标舌头在吐舌形态中按原参考与嘴宽的比例等比缩小，不修改生成的 Basis。尺寸检查保留旋转和平移，限制额外边长 ≤ Basis 的 1.04 倍；沿去除整体旋转后的方向检查 X/Y 跨度 ≤ 1.08/1.04 倍，Z 跨度 ≤ 原厚度 + 舌长的 28%。出口局部最多变薄 15% | 存在对应分区时执行 | recipe | procedural_tongue.reference_pose / deform / limit_size |
| 5 | 人中与唇周 | 开口沿当前 Face 的局部轮廓采样有限深度变化，不沿初始切线无限外推；唇缘邻近面片共同平移，保留原斜面与厚度，再向周围脸皮平滑过渡 | 存在对应分区时执行 | recipe | procedural_lips.surface_motion / deform |
| 6 | 皮肤求解 | 固定眼口控制点，沿 Face 邻接平滑传播 | 存在对应分区时执行 | recipe | procedural_skin.EyelidSkin.deform |
| 7 | 防破面 | 保持轮廓约束，限制局部修正，残余冲突写入报告 | 存在对应分区时执行 | recipe | procedural_constraints.finalize_skin |
| 8 | 风格设置 | 下眼睑参与量在可行闭合范围中选择接合位置，不改变下眼睑 30% 上移及笑眼弧顶额外 10% 的硬上限。笑眼弧度与形态保持调整曲线偏好，闭合、接触和厚度优先。组合、曲线写回沿用生成时保存的风格设置 | 存在对应分区时执行 | recipe | procedural_ui.generation_options / procedural_binding.styled_closure |
| 9 | 闭眼层次 | 下睫毛随实际下眼眶的连续位移和旋转运动。闭眼时将整条下睫毛的上下缘收在上睫毛投影内，再求解前后层次。Face 接触后复查并修正遮盖，最终悬空和覆盖不足单独报告 | 存在对应分区时执行 | recipe | procedural_lashes.follow_lower_rim / cover_lower_band / finish_closed_order |
| 10 | 计算设备 | Windows NVIDIA CUDA 可用时，以双精度 GPU 内核求解三角面投影接触。小任务、缺少运行库、显存或调用失败时使用 CPU。两种设备共用几何规则、容差和可移动条件，报告设备、调用数与回退原因 | 存在对应分区时执行 | recipe | procedural_gpu.try_depth |
| 11 | 口腔 | 口内边界固定到实际唇缘，内部连续变形；强制镜像后重新贴合 Face 与 Mouth，避免两次表面插值产生小接缝 | 存在对应分区时执行 | recipe | procedural_cavity.deform |
| 12 | 牙齿 | 内置口型按 Original 张口时牙片的一致运动校准上下排，再按嘴宽适配各自位移与旋转，不重复叠加竖向随唇浮动。原参考静止的牙齿保持原位；目标有小间隙时，下牙整组上移至首次接触，最多嘴宽的 30%，缺少独立上下牙则跳过。未校准的自定义或下颌动作保留有界随唇处理。接触可先收回校准动作中的前移，再按牙弓与嘴宽的较大值取 6.5% 额度整排后移，保留牙弓及上下行程；未校准动作仍采用 2.5% 共同后移及 4% 局部后移。检查局部修正是否引入新的三角面翻折；额度不足记录穿插，不向外推 Face，不缩放牙弓，不改变 Basis | 存在对应分区时执行 | recipe | procedural_constraints.close_dental_contact / procedural_contacts.oral_face |
| 13 | 吐舌接触 | 检查外露下表面和外侧面；独立舌头整体平移避开 Face，避免把外露截面拉离舌根；焊接舌头保留局部处理及最终尺寸限制，冲突写入报告 | 存在对应分区时执行 | recipe | procedural_tongue.keep_exterior |
| 14 | 口内接触 | 按唇缘相连拓扑选择 Face 接触面，包含斜面及内翻唇面；牙齿及口腔退回面部内侧，口腔唇缘固定。取消舌头随整排牙齿最前点后退；牙齿与舌头的接触只由实际三角面交叉触发。舌头上表面避开下口腔，Basis 同样检查；接触位移上限取舌长 12% 和口宽 8% 的较小值，同次修正反复检查共用额度；超出额度报告冲突 | 存在对应分区时执行 | recipe | procedural_contacts.finish / tongue_teeth / tongue_side |
| 15 | 写入 | 表情形态键、口腔联动和最终变形曲线一起保存 | 存在对应分区时执行 | recipe | procedural_generate.generate |
| 16 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.mouth | procedural_atoms.merge |
| 17 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.mouth_reference | procedural_atoms.merge |
| 18 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.tongue | procedural_atoms.merge |
| 19 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.oral | procedural_atoms.merge |

数值定义：JSON 中 `expressions` 的同名项。

## ん

| 顺序 | 阶段 | 计算准则 | 条件 | 数值路径 | 实现 |
| --- | --- | --- | --- | --- | --- |
| 1 | 对称策略 | 允许强制左右对称；正侧完成约束后直接镜像最终坐标到负侧，不再两侧平均。独立眼眉在相关顶点可配对时只计算正侧，不要求三角面划分相同。跨中线口型保留整体求解；活动顶点无法配对则跳过。镜像后的翻折数量写入报告 | 生成时开启强制对称 | can_symmetrize / special / relation | procedural_symmetry |
| 2 | 输入 | 按当前标记读取；已删除必要曲线所依赖的表情跳过 | 存在对应分区时执行 | recipe | procedural_rig.checkpoint |
| 3 | 嘴型目标 | 按口宽适配目标轮廓，保留上下唇拓扑归属 | 存在对应分区时执行 | recipe | procedural_atoms.mouth_outline |
| 4 | 舌头目标 | 普通口型保留 Original 舌头的整体位移和旋转。てへぺろ按原曲线侧伸，ぺろっ居中下卷；截面沿等弧长曲线弯曲，过厚或过宽的目标舌头在吐舌形态中按原参考与嘴宽的比例等比缩小，不修改生成的 Basis。尺寸检查保留旋转和平移，限制额外边长 ≤ Basis 的 1.04 倍；沿去除整体旋转后的方向检查 X/Y 跨度 ≤ 1.08/1.04 倍，Z 跨度 ≤ 原厚度 + 舌长的 28%。出口局部最多变薄 15% | 存在对应分区时执行 | recipe | procedural_tongue.reference_pose / deform / limit_size |
| 5 | 人中与唇周 | 开口沿当前 Face 的局部轮廓采样有限深度变化，不沿初始切线无限外推；唇缘邻近面片共同平移，保留原斜面与厚度，再向周围脸皮平滑过渡 | 存在对应分区时执行 | recipe | procedural_lips.surface_motion / deform |
| 6 | 皮肤求解 | 固定眼口控制点，沿 Face 邻接平滑传播 | 存在对应分区时执行 | recipe | procedural_skin.EyelidSkin.deform |
| 7 | 防破面 | 保持轮廓约束，限制局部修正，残余冲突写入报告 | 存在对应分区时执行 | recipe | procedural_constraints.finalize_skin |
| 8 | 风格设置 | 下眼睑参与量在可行闭合范围中选择接合位置，不改变下眼睑 30% 上移及笑眼弧顶额外 10% 的硬上限。笑眼弧度与形态保持调整曲线偏好，闭合、接触和厚度优先。组合、曲线写回沿用生成时保存的风格设置 | 存在对应分区时执行 | recipe | procedural_ui.generation_options / procedural_binding.styled_closure |
| 9 | 闭眼层次 | 下睫毛随实际下眼眶的连续位移和旋转运动。闭眼时将整条下睫毛的上下缘收在上睫毛投影内，再求解前后层次。Face 接触后复查并修正遮盖，最终悬空和覆盖不足单独报告 | 存在对应分区时执行 | recipe | procedural_lashes.follow_lower_rim / cover_lower_band / finish_closed_order |
| 10 | 计算设备 | Windows NVIDIA CUDA 可用时，以双精度 GPU 内核求解三角面投影接触。小任务、缺少运行库、显存或调用失败时使用 CPU。两种设备共用几何规则、容差和可移动条件，报告设备、调用数与回退原因 | 存在对应分区时执行 | recipe | procedural_gpu.try_depth |
| 11 | 口腔 | 口内边界固定到实际唇缘，内部连续变形；强制镜像后重新贴合 Face 与 Mouth，避免两次表面插值产生小接缝 | 存在对应分区时执行 | recipe | procedural_cavity.deform |
| 12 | 牙齿 | 内置口型按 Original 张口时牙片的一致运动校准上下排，再按嘴宽适配各自位移与旋转，不重复叠加竖向随唇浮动。原参考静止的牙齿保持原位；目标有小间隙时，下牙整组上移至首次接触，最多嘴宽的 30%，缺少独立上下牙则跳过。未校准的自定义或下颌动作保留有界随唇处理。接触可先收回校准动作中的前移，再按牙弓与嘴宽的较大值取 6.5% 额度整排后移，保留牙弓及上下行程；未校准动作仍采用 2.5% 共同后移及 4% 局部后移。检查局部修正是否引入新的三角面翻折；额度不足记录穿插，不向外推 Face，不缩放牙弓，不改变 Basis | 存在对应分区时执行 | recipe | procedural_constraints.close_dental_contact / procedural_contacts.oral_face |
| 13 | 吐舌接触 | 检查外露下表面和外侧面；独立舌头整体平移避开 Face，避免把外露截面拉离舌根；焊接舌头保留局部处理及最终尺寸限制，冲突写入报告 | 存在对应分区时执行 | recipe | procedural_tongue.keep_exterior |
| 14 | 口内接触 | 按唇缘相连拓扑选择 Face 接触面，包含斜面及内翻唇面；牙齿及口腔退回面部内侧，口腔唇缘固定。取消舌头随整排牙齿最前点后退；牙齿与舌头的接触只由实际三角面交叉触发。舌头上表面避开下口腔，Basis 同样检查；接触位移上限取舌长 12% 和口宽 8% 的较小值，同次修正反复检查共用额度；超出额度报告冲突 | 存在对应分区时执行 | recipe | procedural_contacts.finish / tongue_teeth / tongue_side |
| 15 | 写入 | 表情形态键、口腔联动和最终变形曲线一起保存 | 存在对应分区时执行 | recipe | procedural_generate.generate |
| 16 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.mouth | procedural_atoms.merge |
| 17 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.mouth_reference | procedural_atoms.merge |
| 18 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.tongue | procedural_atoms.merge |
| 19 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.oral | procedural_atoms.merge |

数值定义：JSON 中 `expressions` 的同名项。

## い１

| 顺序 | 阶段 | 计算准则 | 条件 | 数值路径 | 实现 |
| --- | --- | --- | --- | --- | --- |
| 1 | 对称策略 | 允许强制左右对称；正侧完成约束后直接镜像最终坐标到负侧，不再两侧平均。独立眼眉在相关顶点可配对时只计算正侧，不要求三角面划分相同。跨中线口型保留整体求解；活动顶点无法配对则跳过。镜像后的翻折数量写入报告 | 生成时开启强制对称 | can_symmetrize / special / relation | procedural_symmetry |
| 2 | 输入 | 按当前标记读取；已删除必要曲线所依赖的表情跳过 | 存在对应分区时执行 | recipe | procedural_rig.checkpoint |
| 3 | 嘴型目标 | 按口宽适配目标轮廓，保留上下唇拓扑归属 | 存在对应分区时执行 | recipe | procedural_atoms.mouth_outline |
| 4 | 舌头目标 | 普通口型保留 Original 舌头的整体位移和旋转。てへぺろ按原曲线侧伸，ぺろっ居中下卷；截面沿等弧长曲线弯曲，过厚或过宽的目标舌头在吐舌形态中按原参考与嘴宽的比例等比缩小，不修改生成的 Basis。尺寸检查保留旋转和平移，限制额外边长 ≤ Basis 的 1.04 倍；沿去除整体旋转后的方向检查 X/Y 跨度 ≤ 1.08/1.04 倍，Z 跨度 ≤ 原厚度 + 舌长的 28%。出口局部最多变薄 15% | 存在对应分区时执行 | recipe | procedural_tongue.reference_pose / deform / limit_size |
| 5 | 人中与唇周 | 开口沿当前 Face 的局部轮廓采样有限深度变化，不沿初始切线无限外推；唇缘邻近面片共同平移，保留原斜面与厚度，再向周围脸皮平滑过渡 | 存在对应分区时执行 | recipe | procedural_lips.surface_motion / deform |
| 6 | 皮肤求解 | 固定眼口控制点，沿 Face 邻接平滑传播 | 存在对应分区时执行 | recipe | procedural_skin.EyelidSkin.deform |
| 7 | 防破面 | 保持轮廓约束，限制局部修正，残余冲突写入报告 | 存在对应分区时执行 | recipe | procedural_constraints.finalize_skin |
| 8 | 风格设置 | 下眼睑参与量在可行闭合范围中选择接合位置，不改变下眼睑 30% 上移及笑眼弧顶额外 10% 的硬上限。笑眼弧度与形态保持调整曲线偏好，闭合、接触和厚度优先。组合、曲线写回沿用生成时保存的风格设置 | 存在对应分区时执行 | recipe | procedural_ui.generation_options / procedural_binding.styled_closure |
| 9 | 闭眼层次 | 下睫毛随实际下眼眶的连续位移和旋转运动。闭眼时将整条下睫毛的上下缘收在上睫毛投影内，再求解前后层次。Face 接触后复查并修正遮盖，最终悬空和覆盖不足单独报告 | 存在对应分区时执行 | recipe | procedural_lashes.follow_lower_rim / cover_lower_band / finish_closed_order |
| 10 | 计算设备 | Windows NVIDIA CUDA 可用时，以双精度 GPU 内核求解三角面投影接触。小任务、缺少运行库、显存或调用失败时使用 CPU。两种设备共用几何规则、容差和可移动条件，报告设备、调用数与回退原因 | 存在对应分区时执行 | recipe | procedural_gpu.try_depth |
| 11 | 口腔 | 口内边界固定到实际唇缘，内部连续变形；强制镜像后重新贴合 Face 与 Mouth，避免两次表面插值产生小接缝 | 存在对应分区时执行 | recipe | procedural_cavity.deform |
| 12 | 牙齿 | 内置口型按 Original 张口时牙片的一致运动校准上下排，再按嘴宽适配各自位移与旋转，不重复叠加竖向随唇浮动。原参考静止的牙齿保持原位；目标有小间隙时，下牙整组上移至首次接触，最多嘴宽的 30%，缺少独立上下牙则跳过。未校准的自定义或下颌动作保留有界随唇处理。接触可先收回校准动作中的前移，再按牙弓与嘴宽的较大值取 6.5% 额度整排后移，保留牙弓及上下行程；未校准动作仍采用 2.5% 共同后移及 4% 局部后移。检查局部修正是否引入新的三角面翻折；额度不足记录穿插，不向外推 Face，不缩放牙弓，不改变 Basis | 存在对应分区时执行 | recipe | procedural_constraints.close_dental_contact / procedural_contacts.oral_face |
| 13 | 吐舌接触 | 检查外露下表面和外侧面；独立舌头整体平移避开 Face，避免把外露截面拉离舌根；焊接舌头保留局部处理及最终尺寸限制，冲突写入报告 | 存在对应分区时执行 | recipe | procedural_tongue.keep_exterior |
| 14 | 口内接触 | 按唇缘相连拓扑选择 Face 接触面，包含斜面及内翻唇面；牙齿及口腔退回面部内侧，口腔唇缘固定。取消舌头随整排牙齿最前点后退；牙齿与舌头的接触只由实际三角面交叉触发。舌头上表面避开下口腔，Basis 同样检查；接触位移上限取舌长 12% 和口宽 8% 的较小值，同次修正反复检查共用额度；超出额度报告冲突 | 存在对应分区时执行 | recipe | procedural_contacts.finish / tongue_teeth / tongue_side |
| 15 | 写入 | 表情形态键、口腔联动和最终变形曲线一起保存 | 存在对应分区时执行 | recipe | procedural_generate.generate |
| 16 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.mouth | procedural_atoms.merge |
| 17 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.mouth_reference | procedural_atoms.merge |
| 18 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.tongue | procedural_atoms.merge |
| 19 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.oral | procedural_atoms.merge |

数值定义：JSON 中 `expressions` 的同名项。

## い２

| 顺序 | 阶段 | 计算准则 | 条件 | 数值路径 | 实现 |
| --- | --- | --- | --- | --- | --- |
| 1 | 对称策略 | 允许强制左右对称；正侧完成约束后直接镜像最终坐标到负侧，不再两侧平均。独立眼眉在相关顶点可配对时只计算正侧，不要求三角面划分相同。跨中线口型保留整体求解；活动顶点无法配对则跳过。镜像后的翻折数量写入报告 | 生成时开启强制对称 | can_symmetrize / special / relation | procedural_symmetry |
| 2 | 输入 | 按当前标记读取；已删除必要曲线所依赖的表情跳过 | 存在对应分区时执行 | recipe | procedural_rig.checkpoint |
| 3 | 嘴型目标 | 按口宽适配目标轮廓，保留上下唇拓扑归属 | 存在对应分区时执行 | recipe | procedural_atoms.mouth_outline |
| 4 | 舌头目标 | 普通口型保留 Original 舌头的整体位移和旋转。てへぺろ按原曲线侧伸，ぺろっ居中下卷；截面沿等弧长曲线弯曲，过厚或过宽的目标舌头在吐舌形态中按原参考与嘴宽的比例等比缩小，不修改生成的 Basis。尺寸检查保留旋转和平移，限制额外边长 ≤ Basis 的 1.04 倍；沿去除整体旋转后的方向检查 X/Y 跨度 ≤ 1.08/1.04 倍，Z 跨度 ≤ 原厚度 + 舌长的 28%。出口局部最多变薄 15% | 存在对应分区时执行 | recipe | procedural_tongue.reference_pose / deform / limit_size |
| 5 | 人中与唇周 | 开口沿当前 Face 的局部轮廓采样有限深度变化，不沿初始切线无限外推；唇缘邻近面片共同平移，保留原斜面与厚度，再向周围脸皮平滑过渡 | 存在对应分区时执行 | recipe | procedural_lips.surface_motion / deform |
| 6 | 皮肤求解 | 固定眼口控制点，沿 Face 邻接平滑传播 | 存在对应分区时执行 | recipe | procedural_skin.EyelidSkin.deform |
| 7 | 防破面 | 保持轮廓约束，限制局部修正，残余冲突写入报告 | 存在对应分区时执行 | recipe | procedural_constraints.finalize_skin |
| 8 | 风格设置 | 下眼睑参与量在可行闭合范围中选择接合位置，不改变下眼睑 30% 上移及笑眼弧顶额外 10% 的硬上限。笑眼弧度与形态保持调整曲线偏好，闭合、接触和厚度优先。组合、曲线写回沿用生成时保存的风格设置 | 存在对应分区时执行 | recipe | procedural_ui.generation_options / procedural_binding.styled_closure |
| 9 | 闭眼层次 | 下睫毛随实际下眼眶的连续位移和旋转运动。闭眼时将整条下睫毛的上下缘收在上睫毛投影内，再求解前后层次。Face 接触后复查并修正遮盖，最终悬空和覆盖不足单独报告 | 存在对应分区时执行 | recipe | procedural_lashes.follow_lower_rim / cover_lower_band / finish_closed_order |
| 10 | 计算设备 | Windows NVIDIA CUDA 可用时，以双精度 GPU 内核求解三角面投影接触。小任务、缺少运行库、显存或调用失败时使用 CPU。两种设备共用几何规则、容差和可移动条件，报告设备、调用数与回退原因 | 存在对应分区时执行 | recipe | procedural_gpu.try_depth |
| 11 | 口腔 | 口内边界固定到实际唇缘，内部连续变形；强制镜像后重新贴合 Face 与 Mouth，避免两次表面插值产生小接缝 | 存在对应分区时执行 | recipe | procedural_cavity.deform |
| 12 | 牙齿 | 内置口型按 Original 张口时牙片的一致运动校准上下排，再按嘴宽适配各自位移与旋转，不重复叠加竖向随唇浮动。原参考静止的牙齿保持原位；目标有小间隙时，下牙整组上移至首次接触，最多嘴宽的 30%，缺少独立上下牙则跳过。未校准的自定义或下颌动作保留有界随唇处理。接触可先收回校准动作中的前移，再按牙弓与嘴宽的较大值取 6.5% 额度整排后移，保留牙弓及上下行程；未校准动作仍采用 2.5% 共同后移及 4% 局部后移。检查局部修正是否引入新的三角面翻折；额度不足记录穿插，不向外推 Face，不缩放牙弓，不改变 Basis | 存在对应分区时执行 | recipe | procedural_constraints.close_dental_contact / procedural_contacts.oral_face |
| 13 | 吐舌接触 | 检查外露下表面和外侧面；独立舌头整体平移避开 Face，避免把外露截面拉离舌根；焊接舌头保留局部处理及最终尺寸限制，冲突写入报告 | 存在对应分区时执行 | recipe | procedural_tongue.keep_exterior |
| 14 | 口内接触 | 按唇缘相连拓扑选择 Face 接触面，包含斜面及内翻唇面；牙齿及口腔退回面部内侧，口腔唇缘固定。取消舌头随整排牙齿最前点后退；牙齿与舌头的接触只由实际三角面交叉触发。舌头上表面避开下口腔，Basis 同样检查；接触位移上限取舌长 12% 和口宽 8% 的较小值，同次修正反复检查共用额度；超出额度报告冲突 | 存在对应分区时执行 | recipe | procedural_contacts.finish / tongue_teeth / tongue_side |
| 15 | 写入 | 表情形态键、口腔联动和最终变形曲线一起保存 | 存在对应分区时执行 | recipe | procedural_generate.generate |
| 16 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.mouth | procedural_atoms.merge |
| 17 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.mouth_reference | procedural_atoms.merge |
| 18 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.tongue | procedural_atoms.merge |
| 19 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.oral | procedural_atoms.merge |

数值定义：JSON 中 `expressions` 的同名项。

## あ２

| 顺序 | 阶段 | 计算准则 | 条件 | 数值路径 | 实现 |
| --- | --- | --- | --- | --- | --- |
| 1 | 对称策略 | 允许强制左右对称；正侧完成约束后直接镜像最终坐标到负侧，不再两侧平均。独立眼眉在相关顶点可配对时只计算正侧，不要求三角面划分相同。跨中线口型保留整体求解；活动顶点无法配对则跳过。镜像后的翻折数量写入报告 | 生成时开启强制对称 | can_symmetrize / special / relation | procedural_symmetry |
| 2 | 输入 | 按当前标记读取；已删除必要曲线所依赖的表情跳过 | 存在对应分区时执行 | recipe | procedural_rig.checkpoint |
| 3 | 嘴型目标 | 按口宽适配目标轮廓，保留上下唇拓扑归属 | 存在对应分区时执行 | recipe | procedural_atoms.mouth_outline |
| 4 | 舌头目标 | 普通口型保留 Original 舌头的整体位移和旋转。てへぺろ按原曲线侧伸，ぺろっ居中下卷；截面沿等弧长曲线弯曲，过厚或过宽的目标舌头在吐舌形态中按原参考与嘴宽的比例等比缩小，不修改生成的 Basis。尺寸检查保留旋转和平移，限制额外边长 ≤ Basis 的 1.04 倍；沿去除整体旋转后的方向检查 X/Y 跨度 ≤ 1.08/1.04 倍，Z 跨度 ≤ 原厚度 + 舌长的 28%。出口局部最多变薄 15% | 存在对应分区时执行 | recipe | procedural_tongue.reference_pose / deform / limit_size |
| 5 | 人中与唇周 | 开口沿当前 Face 的局部轮廓采样有限深度变化，不沿初始切线无限外推；唇缘邻近面片共同平移，保留原斜面与厚度，再向周围脸皮平滑过渡 | 存在对应分区时执行 | recipe | procedural_lips.surface_motion / deform |
| 6 | 皮肤求解 | 固定眼口控制点，沿 Face 邻接平滑传播 | 存在对应分区时执行 | recipe | procedural_skin.EyelidSkin.deform |
| 7 | 防破面 | 保持轮廓约束，限制局部修正，残余冲突写入报告 | 存在对应分区时执行 | recipe | procedural_constraints.finalize_skin |
| 8 | 风格设置 | 下眼睑参与量在可行闭合范围中选择接合位置，不改变下眼睑 30% 上移及笑眼弧顶额外 10% 的硬上限。笑眼弧度与形态保持调整曲线偏好，闭合、接触和厚度优先。组合、曲线写回沿用生成时保存的风格设置 | 存在对应分区时执行 | recipe | procedural_ui.generation_options / procedural_binding.styled_closure |
| 9 | 闭眼层次 | 下睫毛随实际下眼眶的连续位移和旋转运动。闭眼时将整条下睫毛的上下缘收在上睫毛投影内，再求解前后层次。Face 接触后复查并修正遮盖，最终悬空和覆盖不足单独报告 | 存在对应分区时执行 | recipe | procedural_lashes.follow_lower_rim / cover_lower_band / finish_closed_order |
| 10 | 计算设备 | Windows NVIDIA CUDA 可用时，以双精度 GPU 内核求解三角面投影接触。小任务、缺少运行库、显存或调用失败时使用 CPU。两种设备共用几何规则、容差和可移动条件，报告设备、调用数与回退原因 | 存在对应分区时执行 | recipe | procedural_gpu.try_depth |
| 11 | 口腔 | 口内边界固定到实际唇缘，内部连续变形；强制镜像后重新贴合 Face 与 Mouth，避免两次表面插值产生小接缝 | 存在对应分区时执行 | recipe | procedural_cavity.deform |
| 12 | 牙齿 | 内置口型按 Original 张口时牙片的一致运动校准上下排，再按嘴宽适配各自位移与旋转，不重复叠加竖向随唇浮动。原参考静止的牙齿保持原位；目标有小间隙时，下牙整组上移至首次接触，最多嘴宽的 30%，缺少独立上下牙则跳过。未校准的自定义或下颌动作保留有界随唇处理。接触可先收回校准动作中的前移，再按牙弓与嘴宽的较大值取 6.5% 额度整排后移，保留牙弓及上下行程；未校准动作仍采用 2.5% 共同后移及 4% 局部后移。检查局部修正是否引入新的三角面翻折；额度不足记录穿插，不向外推 Face，不缩放牙弓，不改变 Basis | 存在对应分区时执行 | recipe | procedural_constraints.close_dental_contact / procedural_contacts.oral_face |
| 13 | 吐舌接触 | 检查外露下表面和外侧面；独立舌头整体平移避开 Face，避免把外露截面拉离舌根；焊接舌头保留局部处理及最终尺寸限制，冲突写入报告 | 存在对应分区时执行 | recipe | procedural_tongue.keep_exterior |
| 14 | 口内接触 | 按唇缘相连拓扑选择 Face 接触面，包含斜面及内翻唇面；牙齿及口腔退回面部内侧，口腔唇缘固定。取消舌头随整排牙齿最前点后退；牙齿与舌头的接触只由实际三角面交叉触发。舌头上表面避开下口腔，Basis 同样检查；接触位移上限取舌长 12% 和口宽 8% 的较小值，同次修正反复检查共用额度；超出额度报告冲突 | 存在对应分区时执行 | recipe | procedural_contacts.finish / tongue_teeth / tongue_side |
| 15 | 写入 | 表情形态键、口腔联动和最终变形曲线一起保存 | 存在对应分区时执行 | recipe | procedural_generate.generate |
| 16 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.mouth | procedural_atoms.merge |
| 17 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.mouth_reference | procedural_atoms.merge |
| 18 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.tongue | procedural_atoms.merge |
| 19 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.oral | procedural_atoms.merge |

数值定义：JSON 中 `expressions` 的同名项。

## にやり２

| 顺序 | 阶段 | 计算准则 | 条件 | 数值路径 | 实现 |
| --- | --- | --- | --- | --- | --- |
| 1 | 对称策略 | 不对该表情强制镜像；保留子表情、组合或特殊动作的定义 | 生成时开启强制对称 | can_symmetrize / special / relation | procedural_symmetry |
| 2 | 输入 | 按当前标记读取；已删除必要曲线所依赖的表情跳过 | 存在对应分区时执行 | recipe | procedural_rig.checkpoint |
| 3 | 嘴型目标 | 按口宽适配目标轮廓，保留上下唇拓扑归属 | 存在对应分区时执行 | recipe | procedural_atoms.mouth_outline |
| 4 | 人中与唇周 | 开口沿当前 Face 的局部轮廓采样有限深度变化，不沿初始切线无限外推；唇缘邻近面片共同平移，保留原斜面与厚度，再向周围脸皮平滑过渡 | 存在对应分区时执行 | recipe | procedural_lips.surface_motion / deform |
| 5 | 皮肤求解 | 固定眼口控制点，沿 Face 邻接平滑传播 | 存在对应分区时执行 | recipe | procedural_skin.EyelidSkin.deform |
| 6 | 防破面 | 保持轮廓约束，限制局部修正，残余冲突写入报告 | 存在对应分区时执行 | recipe | procedural_constraints.finalize_skin |
| 7 | 风格设置 | 下眼睑参与量在可行闭合范围中选择接合位置，不改变下眼睑 30% 上移及笑眼弧顶额外 10% 的硬上限。笑眼弧度与形态保持调整曲线偏好，闭合、接触和厚度优先。组合、曲线写回沿用生成时保存的风格设置 | 存在对应分区时执行 | recipe | procedural_ui.generation_options / procedural_binding.styled_closure |
| 8 | 闭眼层次 | 下睫毛随实际下眼眶的连续位移和旋转运动。闭眼时将整条下睫毛的上下缘收在上睫毛投影内，再求解前后层次。Face 接触后复查并修正遮盖，最终悬空和覆盖不足单独报告 | 存在对应分区时执行 | recipe | procedural_lashes.follow_lower_rim / cover_lower_band / finish_closed_order |
| 9 | 计算设备 | Windows NVIDIA CUDA 可用时，以双精度 GPU 内核求解三角面投影接触。小任务、缺少运行库、显存或调用失败时使用 CPU。两种设备共用几何规则、容差和可移动条件，报告设备、调用数与回退原因 | 存在对应分区时执行 | recipe | procedural_gpu.try_depth |
| 10 | 口腔 | 口内边界固定到实际唇缘，内部连续变形；强制镜像后重新贴合 Face 与 Mouth，避免两次表面插值产生小接缝 | 存在对应分区时执行 | recipe | procedural_cavity.deform |
| 11 | 牙齿 | 内置口型按 Original 张口时牙片的一致运动校准上下排，再按嘴宽适配各自位移与旋转，不重复叠加竖向随唇浮动。原参考静止的牙齿保持原位；目标有小间隙时，下牙整组上移至首次接触，最多嘴宽的 30%，缺少独立上下牙则跳过。未校准的自定义或下颌动作保留有界随唇处理。接触可先收回校准动作中的前移，再按牙弓与嘴宽的较大值取 6.5% 额度整排后移，保留牙弓及上下行程；未校准动作仍采用 2.5% 共同后移及 4% 局部后移。检查局部修正是否引入新的三角面翻折；额度不足记录穿插，不向外推 Face，不缩放牙弓，不改变 Basis | 存在对应分区时执行 | recipe | procedural_constraints.close_dental_contact / procedural_contacts.oral_face |
| 12 | 口内接触 | 按唇缘相连拓扑选择 Face 接触面，包含斜面及内翻唇面；牙齿及口腔退回面部内侧，口腔唇缘固定。取消舌头随整排牙齿最前点后退；牙齿与舌头的接触只由实际三角面交叉触发。舌头上表面避开下口腔，Basis 同样检查；接触位移上限取舌长 12% 和口宽 8% 的较小值，同次修正反复检查共用额度；超出额度报告冲突 | 存在对应分区时执行 | recipe | procedural_contacts.finish / tongue_teeth / tongue_side |
| 13 | 写入 | 表情形态键、口腔联动和最终变形曲线一起保存 | 存在对应分区时执行 | recipe | procedural_generate.generate |
| 14 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.mouth | procedural_atoms.merge |
| 15 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.mouth_reference | procedural_atoms.merge |
| 16 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.oral | procedural_atoms.merge |

数值定义：JSON 中 `expressions` 的同名项。

## にやり３

| 顺序 | 阶段 | 计算准则 | 条件 | 数值路径 | 实现 |
| --- | --- | --- | --- | --- | --- |
| 1 | 对称策略 | 不对该表情强制镜像；保留子表情、组合或特殊动作的定义 | 生成时开启强制对称 | can_symmetrize / special / relation | procedural_symmetry |
| 2 | 输入 | 按当前标记读取；已删除必要曲线所依赖的表情跳过 | 存在对应分区时执行 | recipe | procedural_rig.checkpoint |
| 3 | 嘴型目标 | 按口宽适配目标轮廓，保留上下唇拓扑归属 | 存在对应分区时执行 | recipe | procedural_atoms.mouth_outline |
| 4 | 舌头目标 | 普通口型保留 Original 舌头的整体位移和旋转。てへぺろ按原曲线侧伸，ぺろっ居中下卷；截面沿等弧长曲线弯曲，过厚或过宽的目标舌头在吐舌形态中按原参考与嘴宽的比例等比缩小，不修改生成的 Basis。尺寸检查保留旋转和平移，限制额外边长 ≤ Basis 的 1.04 倍；沿去除整体旋转后的方向检查 X/Y 跨度 ≤ 1.08/1.04 倍，Z 跨度 ≤ 原厚度 + 舌长的 28%。出口局部最多变薄 15% | 存在对应分区时执行 | recipe | procedural_tongue.reference_pose / deform / limit_size |
| 5 | 人中与唇周 | 开口沿当前 Face 的局部轮廓采样有限深度变化，不沿初始切线无限外推；唇缘邻近面片共同平移，保留原斜面与厚度，再向周围脸皮平滑过渡 | 存在对应分区时执行 | recipe | procedural_lips.surface_motion / deform |
| 6 | 皮肤求解 | 固定眼口控制点，沿 Face 邻接平滑传播 | 存在对应分区时执行 | recipe | procedural_skin.EyelidSkin.deform |
| 7 | 防破面 | 保持轮廓约束，限制局部修正，残余冲突写入报告 | 存在对应分区时执行 | recipe | procedural_constraints.finalize_skin |
| 8 | 风格设置 | 下眼睑参与量在可行闭合范围中选择接合位置，不改变下眼睑 30% 上移及笑眼弧顶额外 10% 的硬上限。笑眼弧度与形态保持调整曲线偏好，闭合、接触和厚度优先。组合、曲线写回沿用生成时保存的风格设置 | 存在对应分区时执行 | recipe | procedural_ui.generation_options / procedural_binding.styled_closure |
| 9 | 闭眼层次 | 下睫毛随实际下眼眶的连续位移和旋转运动。闭眼时将整条下睫毛的上下缘收在上睫毛投影内，再求解前后层次。Face 接触后复查并修正遮盖，最终悬空和覆盖不足单独报告 | 存在对应分区时执行 | recipe | procedural_lashes.follow_lower_rim / cover_lower_band / finish_closed_order |
| 10 | 计算设备 | Windows NVIDIA CUDA 可用时，以双精度 GPU 内核求解三角面投影接触。小任务、缺少运行库、显存或调用失败时使用 CPU。两种设备共用几何规则、容差和可移动条件，报告设备、调用数与回退原因 | 存在对应分区时执行 | recipe | procedural_gpu.try_depth |
| 11 | 口腔 | 口内边界固定到实际唇缘，内部连续变形；强制镜像后重新贴合 Face 与 Mouth，避免两次表面插值产生小接缝 | 存在对应分区时执行 | recipe | procedural_cavity.deform |
| 12 | 牙齿 | 内置口型按 Original 张口时牙片的一致运动校准上下排，再按嘴宽适配各自位移与旋转，不重复叠加竖向随唇浮动。原参考静止的牙齿保持原位；目标有小间隙时，下牙整组上移至首次接触，最多嘴宽的 30%，缺少独立上下牙则跳过。未校准的自定义或下颌动作保留有界随唇处理。接触可先收回校准动作中的前移，再按牙弓与嘴宽的较大值取 6.5% 额度整排后移，保留牙弓及上下行程；未校准动作仍采用 2.5% 共同后移及 4% 局部后移。检查局部修正是否引入新的三角面翻折；额度不足记录穿插，不向外推 Face，不缩放牙弓，不改变 Basis | 存在对应分区时执行 | recipe | procedural_constraints.close_dental_contact / procedural_contacts.oral_face |
| 13 | 吐舌接触 | 检查外露下表面和外侧面；独立舌头整体平移避开 Face，避免把外露截面拉离舌根；焊接舌头保留局部处理及最终尺寸限制，冲突写入报告 | 存在对应分区时执行 | recipe | procedural_tongue.keep_exterior |
| 14 | 口内接触 | 按唇缘相连拓扑选择 Face 接触面，包含斜面及内翻唇面；牙齿及口腔退回面部内侧，口腔唇缘固定。取消舌头随整排牙齿最前点后退；牙齿与舌头的接触只由实际三角面交叉触发。舌头上表面避开下口腔，Basis 同样检查；接触位移上限取舌长 12% 和口宽 8% 的较小值，同次修正反复检查共用额度；超出额度报告冲突 | 存在对应分区时执行 | recipe | procedural_contacts.finish / tongue_teeth / tongue_side |
| 15 | 写入 | 表情形态键、口腔联动和最终变形曲线一起保存 | 存在对应分区时执行 | recipe | procedural_generate.generate |
| 16 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.mouth | procedural_atoms.merge |
| 17 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.mouth_reference | procedural_atoms.merge |
| 18 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.tongue | procedural_atoms.merge |
| 19 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.oral | procedural_atoms.merge |

数值定义：JSON 中 `expressions` 的同名项。

## ω

| 顺序 | 阶段 | 计算准则 | 条件 | 数值路径 | 实现 |
| --- | --- | --- | --- | --- | --- |
| 1 | 对称策略 | 允许强制左右对称；正侧完成约束后直接镜像最终坐标到负侧，不再两侧平均。独立眼眉在相关顶点可配对时只计算正侧，不要求三角面划分相同。跨中线口型保留整体求解；活动顶点无法配对则跳过。镜像后的翻折数量写入报告 | 生成时开启强制对称 | can_symmetrize / special / relation | procedural_symmetry |
| 2 | 输入 | 按当前标记读取；已删除必要曲线所依赖的表情跳过 | 存在对应分区时执行 | recipe | procedural_rig.checkpoint |
| 3 | 嘴型目标 | 按口宽适配目标轮廓，保留上下唇拓扑归属 | 存在对应分区时执行 | recipe | procedural_atoms.mouth_outline |
| 4 | 人中与唇周 | 开口沿当前 Face 的局部轮廓采样有限深度变化，不沿初始切线无限外推；唇缘邻近面片共同平移，保留原斜面与厚度，再向周围脸皮平滑过渡 | 存在对应分区时执行 | recipe | procedural_lips.surface_motion / deform |
| 5 | 皮肤求解 | 固定眼口控制点，沿 Face 邻接平滑传播 | 存在对应分区时执行 | recipe | procedural_skin.EyelidSkin.deform |
| 6 | 防破面 | 保持轮廓约束，限制局部修正，残余冲突写入报告 | 存在对应分区时执行 | recipe | procedural_constraints.finalize_skin |
| 7 | 风格设置 | 下眼睑参与量在可行闭合范围中选择接合位置，不改变下眼睑 30% 上移及笑眼弧顶额外 10% 的硬上限。笑眼弧度与形态保持调整曲线偏好，闭合、接触和厚度优先。组合、曲线写回沿用生成时保存的风格设置 | 存在对应分区时执行 | recipe | procedural_ui.generation_options / procedural_binding.styled_closure |
| 8 | 闭眼层次 | 下睫毛随实际下眼眶的连续位移和旋转运动。闭眼时将整条下睫毛的上下缘收在上睫毛投影内，再求解前后层次。Face 接触后复查并修正遮盖，最终悬空和覆盖不足单独报告 | 存在对应分区时执行 | recipe | procedural_lashes.follow_lower_rim / cover_lower_band / finish_closed_order |
| 9 | 计算设备 | Windows NVIDIA CUDA 可用时，以双精度 GPU 内核求解三角面投影接触。小任务、缺少运行库、显存或调用失败时使用 CPU。两种设备共用几何规则、容差和可移动条件，报告设备、调用数与回退原因 | 存在对应分区时执行 | recipe | procedural_gpu.try_depth |
| 10 | 口腔 | 口内边界固定到实际唇缘，内部连续变形；强制镜像后重新贴合 Face 与 Mouth，避免两次表面插值产生小接缝 | 存在对应分区时执行 | recipe | procedural_cavity.deform |
| 11 | 牙齿 | 内置口型按 Original 张口时牙片的一致运动校准上下排，再按嘴宽适配各自位移与旋转，不重复叠加竖向随唇浮动。原参考静止的牙齿保持原位；目标有小间隙时，下牙整组上移至首次接触，最多嘴宽的 30%，缺少独立上下牙则跳过。未校准的自定义或下颌动作保留有界随唇处理。接触可先收回校准动作中的前移，再按牙弓与嘴宽的较大值取 6.5% 额度整排后移，保留牙弓及上下行程；未校准动作仍采用 2.5% 共同后移及 4% 局部后移。检查局部修正是否引入新的三角面翻折；额度不足记录穿插，不向外推 Face，不缩放牙弓，不改变 Basis | 存在对应分区时执行 | recipe | procedural_constraints.close_dental_contact / procedural_contacts.oral_face |
| 12 | 口内接触 | 按唇缘相连拓扑选择 Face 接触面，包含斜面及内翻唇面；牙齿及口腔退回面部内侧，口腔唇缘固定。取消舌头随整排牙齿最前点后退；牙齿与舌头的接触只由实际三角面交叉触发。舌头上表面避开下口腔，Basis 同样检查；接触位移上限取舌长 12% 和口宽 8% 的较小值，同次修正反复检查共用额度；超出额度报告冲突 | 存在对应分区时执行 | recipe | procedural_contacts.finish / tongue_teeth / tongue_side |
| 13 | 写入 | 表情形态键、口腔联动和最终变形曲线一起保存 | 存在对应分区时执行 | recipe | procedural_generate.generate |
| 14 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.mouth | procedural_atoms.merge |
| 15 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.mouth_reference | procedural_atoms.merge |
| 16 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.oral | procedural_atoms.merge |

数值定义：JSON 中 `expressions` 的同名项。

## てへぺろ

| 顺序 | 阶段 | 计算准则 | 条件 | 数值路径 | 实现 |
| --- | --- | --- | --- | --- | --- |
| 1 | 对称策略 | 不对该表情强制镜像；保留子表情、组合或特殊动作的定义 | 生成时开启强制对称 | can_symmetrize / special / relation | procedural_symmetry |
| 2 | 输入 | 按当前标记读取；已删除必要曲线所依赖的表情跳过 | 存在对应分区时执行 | recipe | procedural_rig.checkpoint |
| 3 | 嘴型目标 | 按口宽适配目标轮廓，保留上下唇拓扑归属 | 存在对应分区时执行 | recipe | procedural_atoms.mouth_outline |
| 4 | 舌头目标 | 普通口型保留 Original 舌头的整体位移和旋转。てへぺろ按原曲线侧伸，ぺろっ居中下卷；截面沿等弧长曲线弯曲，过厚或过宽的目标舌头在吐舌形态中按原参考与嘴宽的比例等比缩小，不修改生成的 Basis。尺寸检查保留旋转和平移，限制额外边长 ≤ Basis 的 1.04 倍；沿去除整体旋转后的方向检查 X/Y 跨度 ≤ 1.08/1.04 倍，Z 跨度 ≤ 原厚度 + 舌长的 28%。出口局部最多变薄 15% | 存在对应分区时执行 | recipe | procedural_tongue.reference_pose / deform / limit_size |
| 5 | 人中与唇周 | 开口沿当前 Face 的局部轮廓采样有限深度变化，不沿初始切线无限外推；唇缘邻近面片共同平移，保留原斜面与厚度，再向周围脸皮平滑过渡 | 存在对应分区时执行 | recipe | procedural_lips.surface_motion / deform |
| 6 | 皮肤求解 | 固定眼口控制点，沿 Face 邻接平滑传播 | 存在对应分区时执行 | recipe | procedural_skin.EyelidSkin.deform |
| 7 | 防破面 | 保持轮廓约束，限制局部修正，残余冲突写入报告 | 存在对应分区时执行 | recipe | procedural_constraints.finalize_skin |
| 8 | 风格设置 | 下眼睑参与量在可行闭合范围中选择接合位置，不改变下眼睑 30% 上移及笑眼弧顶额外 10% 的硬上限。笑眼弧度与形态保持调整曲线偏好，闭合、接触和厚度优先。组合、曲线写回沿用生成时保存的风格设置 | 存在对应分区时执行 | recipe | procedural_ui.generation_options / procedural_binding.styled_closure |
| 9 | 闭眼层次 | 下睫毛随实际下眼眶的连续位移和旋转运动。闭眼时将整条下睫毛的上下缘收在上睫毛投影内，再求解前后层次。Face 接触后复查并修正遮盖，最终悬空和覆盖不足单独报告 | 存在对应分区时执行 | recipe | procedural_lashes.follow_lower_rim / cover_lower_band / finish_closed_order |
| 10 | 计算设备 | Windows NVIDIA CUDA 可用时，以双精度 GPU 内核求解三角面投影接触。小任务、缺少运行库、显存或调用失败时使用 CPU。两种设备共用几何规则、容差和可移动条件，报告设备、调用数与回退原因 | 存在对应分区时执行 | recipe | procedural_gpu.try_depth |
| 11 | 口腔 | 口内边界固定到实际唇缘，内部连续变形；强制镜像后重新贴合 Face 与 Mouth，避免两次表面插值产生小接缝 | 存在对应分区时执行 | recipe | procedural_cavity.deform |
| 12 | 牙齿 | 内置口型按 Original 张口时牙片的一致运动校准上下排，再按嘴宽适配各自位移与旋转，不重复叠加竖向随唇浮动。原参考静止的牙齿保持原位；目标有小间隙时，下牙整组上移至首次接触，最多嘴宽的 30%，缺少独立上下牙则跳过。未校准的自定义或下颌动作保留有界随唇处理。接触可先收回校准动作中的前移，再按牙弓与嘴宽的较大值取 6.5% 额度整排后移，保留牙弓及上下行程；未校准动作仍采用 2.5% 共同后移及 4% 局部后移。检查局部修正是否引入新的三角面翻折；额度不足记录穿插，不向外推 Face，不缩放牙弓，不改变 Basis | 存在对应分区时执行 | recipe | procedural_constraints.close_dental_contact / procedural_contacts.oral_face |
| 13 | 吐舌接触 | 检查外露下表面和外侧面；独立舌头整体平移避开 Face，避免把外露截面拉离舌根；焊接舌头保留局部处理及最终尺寸限制，冲突写入报告 | 存在对应分区时执行 | recipe | procedural_tongue.keep_exterior |
| 14 | 口内接触 | 按唇缘相连拓扑选择 Face 接触面，包含斜面及内翻唇面；牙齿及口腔退回面部内侧，口腔唇缘固定。取消舌头随整排牙齿最前点后退；牙齿与舌头的接触只由实际三角面交叉触发。舌头上表面避开下口腔，Basis 同样检查；接触位移上限取舌长 12% 和口宽 8% 的较小值，同次修正反复检查共用额度；超出额度报告冲突 | 存在对应分区时执行 | recipe | procedural_contacts.finish / tongue_teeth / tongue_side |
| 15 | 写入 | 表情形态键、口腔联动和最终变形曲线一起保存 | 存在对应分区时执行 | recipe | procedural_generate.generate |
| 16 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.mouth | procedural_atoms.merge |
| 17 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.mouth_reference | procedural_atoms.merge |
| 18 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.tongue | procedural_atoms.merge |
| 19 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.oral | procedural_atoms.merge |

数值定义：JSON 中 `expressions` 的同名项。

## ぺろっ

| 顺序 | 阶段 | 计算准则 | 条件 | 数值路径 | 实现 |
| --- | --- | --- | --- | --- | --- |
| 1 | 对称策略 | 不对该表情强制镜像；保留子表情、组合或特殊动作的定义 | 生成时开启强制对称 | can_symmetrize / special / relation | procedural_symmetry |
| 2 | 输入 | 按当前标记读取；已删除必要曲线所依赖的表情跳过 | 存在对应分区时执行 | recipe | procedural_rig.checkpoint |
| 3 | 嘴型目标 | 按口宽适配目标轮廓，保留上下唇拓扑归属 | 存在对应分区时执行 | recipe | procedural_atoms.mouth_outline |
| 4 | 舌头目标 | 普通口型保留 Original 舌头的整体位移和旋转。てへぺろ按原曲线侧伸，ぺろっ居中下卷；截面沿等弧长曲线弯曲，过厚或过宽的目标舌头在吐舌形态中按原参考与嘴宽的比例等比缩小，不修改生成的 Basis。尺寸检查保留旋转和平移，限制额外边长 ≤ Basis 的 1.04 倍；沿去除整体旋转后的方向检查 X/Y 跨度 ≤ 1.08/1.04 倍，Z 跨度 ≤ 原厚度 + 舌长的 28%。出口局部最多变薄 15% | 存在对应分区时执行 | recipe | procedural_tongue.reference_pose / deform / limit_size |
| 5 | 人中与唇周 | 开口沿当前 Face 的局部轮廓采样有限深度变化，不沿初始切线无限外推；唇缘邻近面片共同平移，保留原斜面与厚度，再向周围脸皮平滑过渡 | 存在对应分区时执行 | recipe | procedural_lips.surface_motion / deform |
| 6 | 皮肤求解 | 固定眼口控制点，沿 Face 邻接平滑传播 | 存在对应分区时执行 | recipe | procedural_skin.EyelidSkin.deform |
| 7 | 防破面 | 保持轮廓约束，限制局部修正，残余冲突写入报告 | 存在对应分区时执行 | recipe | procedural_constraints.finalize_skin |
| 8 | 风格设置 | 下眼睑参与量在可行闭合范围中选择接合位置，不改变下眼睑 30% 上移及笑眼弧顶额外 10% 的硬上限。笑眼弧度与形态保持调整曲线偏好，闭合、接触和厚度优先。组合、曲线写回沿用生成时保存的风格设置 | 存在对应分区时执行 | recipe | procedural_ui.generation_options / procedural_binding.styled_closure |
| 9 | 闭眼层次 | 下睫毛随实际下眼眶的连续位移和旋转运动。闭眼时将整条下睫毛的上下缘收在上睫毛投影内，再求解前后层次。Face 接触后复查并修正遮盖，最终悬空和覆盖不足单独报告 | 存在对应分区时执行 | recipe | procedural_lashes.follow_lower_rim / cover_lower_band / finish_closed_order |
| 10 | 计算设备 | Windows NVIDIA CUDA 可用时，以双精度 GPU 内核求解三角面投影接触。小任务、缺少运行库、显存或调用失败时使用 CPU。两种设备共用几何规则、容差和可移动条件，报告设备、调用数与回退原因 | 存在对应分区时执行 | recipe | procedural_gpu.try_depth |
| 11 | 口腔 | 口内边界固定到实际唇缘，内部连续变形；强制镜像后重新贴合 Face 与 Mouth，避免两次表面插值产生小接缝 | 存在对应分区时执行 | recipe | procedural_cavity.deform |
| 12 | 牙齿 | 内置口型按 Original 张口时牙片的一致运动校准上下排，再按嘴宽适配各自位移与旋转，不重复叠加竖向随唇浮动。原参考静止的牙齿保持原位；目标有小间隙时，下牙整组上移至首次接触，最多嘴宽的 30%，缺少独立上下牙则跳过。未校准的自定义或下颌动作保留有界随唇处理。接触可先收回校准动作中的前移，再按牙弓与嘴宽的较大值取 6.5% 额度整排后移，保留牙弓及上下行程；未校准动作仍采用 2.5% 共同后移及 4% 局部后移。检查局部修正是否引入新的三角面翻折；额度不足记录穿插，不向外推 Face，不缩放牙弓，不改变 Basis | 存在对应分区时执行 | recipe | procedural_constraints.close_dental_contact / procedural_contacts.oral_face |
| 13 | 吐舌接触 | 检查外露下表面和外侧面；独立舌头整体平移避开 Face，避免把外露截面拉离舌根；焊接舌头保留局部处理及最终尺寸限制，冲突写入报告 | 存在对应分区时执行 | recipe | procedural_tongue.keep_exterior |
| 14 | 口内接触 | 按唇缘相连拓扑选择 Face 接触面，包含斜面及内翻唇面；牙齿及口腔退回面部内侧，口腔唇缘固定。取消舌头随整排牙齿最前点后退；牙齿与舌头的接触只由实际三角面交叉触发。舌头上表面避开下口腔，Basis 同样检查；接触位移上限取舌长 12% 和口宽 8% 的较小值，同次修正反复检查共用额度；超出额度报告冲突 | 存在对应分区时执行 | recipe | procedural_contacts.finish / tongue_teeth / tongue_side |
| 15 | 写入 | 表情形态键、口腔联动和最终变形曲线一起保存 | 存在对应分区时执行 | recipe | procedural_generate.generate |
| 16 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.mouth | procedural_atoms.merge |
| 17 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.mouth_reference | procedural_atoms.merge |
| 18 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.tongue | procedural_atoms.merge |
| 19 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.oral | procedural_atoms.merge |

数值定义：JSON 中 `expressions` 的同名项。

## 口角上げ

| 顺序 | 阶段 | 计算准则 | 条件 | 数值路径 | 实现 |
| --- | --- | --- | --- | --- | --- |
| 1 | 对称策略 | 允许强制左右对称；正侧完成约束后直接镜像最终坐标到负侧，不再两侧平均。独立眼眉在相关顶点可配对时只计算正侧，不要求三角面划分相同。跨中线口型保留整体求解；活动顶点无法配对则跳过。镜像后的翻折数量写入报告 | 生成时开启强制对称 | can_symmetrize / special / relation | procedural_symmetry |
| 2 | 输入 | 按当前标记读取；已删除必要曲线所依赖的表情跳过 | 存在对应分区时执行 | recipe | procedural_rig.checkpoint |
| 3 | 嘴型目标 | 按口宽适配目标轮廓，保留上下唇拓扑归属 | 存在对应分区时执行 | recipe | procedural_atoms.mouth_outline |
| 4 | 人中与唇周 | 开口沿当前 Face 的局部轮廓采样有限深度变化，不沿初始切线无限外推；唇缘邻近面片共同平移，保留原斜面与厚度，再向周围脸皮平滑过渡 | 存在对应分区时执行 | recipe | procedural_lips.surface_motion / deform |
| 5 | 皮肤求解 | 固定眼口控制点，沿 Face 邻接平滑传播 | 存在对应分区时执行 | recipe | procedural_skin.EyelidSkin.deform |
| 6 | 防破面 | 保持轮廓约束，限制局部修正，残余冲突写入报告 | 存在对应分区时执行 | recipe | procedural_constraints.finalize_skin |
| 7 | 风格设置 | 下眼睑参与量在可行闭合范围中选择接合位置，不改变下眼睑 30% 上移及笑眼弧顶额外 10% 的硬上限。笑眼弧度与形态保持调整曲线偏好，闭合、接触和厚度优先。组合、曲线写回沿用生成时保存的风格设置 | 存在对应分区时执行 | recipe | procedural_ui.generation_options / procedural_binding.styled_closure |
| 8 | 闭眼层次 | 下睫毛随实际下眼眶的连续位移和旋转运动。闭眼时将整条下睫毛的上下缘收在上睫毛投影内，再求解前后层次。Face 接触后复查并修正遮盖，最终悬空和覆盖不足单独报告 | 存在对应分区时执行 | recipe | procedural_lashes.follow_lower_rim / cover_lower_band / finish_closed_order |
| 9 | 计算设备 | Windows NVIDIA CUDA 可用时，以双精度 GPU 内核求解三角面投影接触。小任务、缺少运行库、显存或调用失败时使用 CPU。两种设备共用几何规则、容差和可移动条件，报告设备、调用数与回退原因 | 存在对应分区时执行 | recipe | procedural_gpu.try_depth |
| 10 | 口腔 | 口内边界固定到实际唇缘，内部连续变形；强制镜像后重新贴合 Face 与 Mouth，避免两次表面插值产生小接缝 | 存在对应分区时执行 | recipe | procedural_cavity.deform |
| 11 | 牙齿 | 内置口型按 Original 张口时牙片的一致运动校准上下排，再按嘴宽适配各自位移与旋转，不重复叠加竖向随唇浮动。原参考静止的牙齿保持原位；目标有小间隙时，下牙整组上移至首次接触，最多嘴宽的 30%，缺少独立上下牙则跳过。未校准的自定义或下颌动作保留有界随唇处理。接触可先收回校准动作中的前移，再按牙弓与嘴宽的较大值取 6.5% 额度整排后移，保留牙弓及上下行程；未校准动作仍采用 2.5% 共同后移及 4% 局部后移。检查局部修正是否引入新的三角面翻折；额度不足记录穿插，不向外推 Face，不缩放牙弓，不改变 Basis | 存在对应分区时执行 | recipe | procedural_constraints.close_dental_contact / procedural_contacts.oral_face |
| 12 | 口内接触 | 按唇缘相连拓扑选择 Face 接触面，包含斜面及内翻唇面；牙齿及口腔退回面部内侧，口腔唇缘固定。取消舌头随整排牙齿最前点后退；牙齿与舌头的接触只由实际三角面交叉触发。舌头上表面避开下口腔，Basis 同样检查；接触位移上限取舌长 12% 和口宽 8% 的较小值，同次修正反复检查共用额度；超出额度报告冲突 | 存在对应分区时执行 | recipe | procedural_contacts.finish / tongue_teeth / tongue_side |
| 13 | 写入 | 表情形态键、口腔联动和最终变形曲线一起保存 | 存在对应分区时执行 | recipe | procedural_generate.generate |
| 14 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.mouth | procedural_atoms.merge |
| 15 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.mouth_reference | procedural_atoms.merge |
| 16 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.oral | procedural_atoms.merge |

数值定义：JSON 中 `expressions` 的同名项。

## 口角下げ

| 顺序 | 阶段 | 计算准则 | 条件 | 数值路径 | 实现 |
| --- | --- | --- | --- | --- | --- |
| 1 | 对称策略 | 允许强制左右对称；正侧完成约束后直接镜像最终坐标到负侧，不再两侧平均。独立眼眉在相关顶点可配对时只计算正侧，不要求三角面划分相同。跨中线口型保留整体求解；活动顶点无法配对则跳过。镜像后的翻折数量写入报告 | 生成时开启强制对称 | can_symmetrize / special / relation | procedural_symmetry |
| 2 | 输入 | 按当前标记读取；已删除必要曲线所依赖的表情跳过 | 存在对应分区时执行 | recipe | procedural_rig.checkpoint |
| 3 | 嘴型目标 | 按口宽适配目标轮廓，保留上下唇拓扑归属 | 存在对应分区时执行 | recipe | procedural_atoms.mouth_outline |
| 4 | 人中与唇周 | 开口沿当前 Face 的局部轮廓采样有限深度变化，不沿初始切线无限外推；唇缘邻近面片共同平移，保留原斜面与厚度，再向周围脸皮平滑过渡 | 存在对应分区时执行 | recipe | procedural_lips.surface_motion / deform |
| 5 | 皮肤求解 | 固定眼口控制点，沿 Face 邻接平滑传播 | 存在对应分区时执行 | recipe | procedural_skin.EyelidSkin.deform |
| 6 | 防破面 | 保持轮廓约束，限制局部修正，残余冲突写入报告 | 存在对应分区时执行 | recipe | procedural_constraints.finalize_skin |
| 7 | 风格设置 | 下眼睑参与量在可行闭合范围中选择接合位置，不改变下眼睑 30% 上移及笑眼弧顶额外 10% 的硬上限。笑眼弧度与形态保持调整曲线偏好，闭合、接触和厚度优先。组合、曲线写回沿用生成时保存的风格设置 | 存在对应分区时执行 | recipe | procedural_ui.generation_options / procedural_binding.styled_closure |
| 8 | 闭眼层次 | 下睫毛随实际下眼眶的连续位移和旋转运动。闭眼时将整条下睫毛的上下缘收在上睫毛投影内，再求解前后层次。Face 接触后复查并修正遮盖，最终悬空和覆盖不足单独报告 | 存在对应分区时执行 | recipe | procedural_lashes.follow_lower_rim / cover_lower_band / finish_closed_order |
| 9 | 计算设备 | Windows NVIDIA CUDA 可用时，以双精度 GPU 内核求解三角面投影接触。小任务、缺少运行库、显存或调用失败时使用 CPU。两种设备共用几何规则、容差和可移动条件，报告设备、调用数与回退原因 | 存在对应分区时执行 | recipe | procedural_gpu.try_depth |
| 10 | 口腔 | 口内边界固定到实际唇缘，内部连续变形；强制镜像后重新贴合 Face 与 Mouth，避免两次表面插值产生小接缝 | 存在对应分区时执行 | recipe | procedural_cavity.deform |
| 11 | 牙齿 | 内置口型按 Original 张口时牙片的一致运动校准上下排，再按嘴宽适配各自位移与旋转，不重复叠加竖向随唇浮动。原参考静止的牙齿保持原位；目标有小间隙时，下牙整组上移至首次接触，最多嘴宽的 30%，缺少独立上下牙则跳过。未校准的自定义或下颌动作保留有界随唇处理。接触可先收回校准动作中的前移，再按牙弓与嘴宽的较大值取 6.5% 额度整排后移，保留牙弓及上下行程；未校准动作仍采用 2.5% 共同后移及 4% 局部后移。检查局部修正是否引入新的三角面翻折；额度不足记录穿插，不向外推 Face，不缩放牙弓，不改变 Basis | 存在对应分区时执行 | recipe | procedural_constraints.close_dental_contact / procedural_contacts.oral_face |
| 12 | 口内接触 | 按唇缘相连拓扑选择 Face 接触面，包含斜面及内翻唇面；牙齿及口腔退回面部内侧，口腔唇缘固定。取消舌头随整排牙齿最前点后退；牙齿与舌头的接触只由实际三角面交叉触发。舌头上表面避开下口腔，Basis 同样检查；接触位移上限取舌长 12% 和口宽 8% 的较小值，同次修正反复检查共用额度；超出额度报告冲突 | 存在对应分区时执行 | recipe | procedural_contacts.finish / tongue_teeth / tongue_side |
| 13 | 写入 | 表情形态键、口腔联动和最终变形曲线一起保存 | 存在对应分区时执行 | recipe | procedural_generate.generate |
| 14 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.mouth | procedural_atoms.merge |
| 15 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.mouth_reference | procedural_atoms.merge |
| 16 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.oral | procedural_atoms.merge |

数值定义：JSON 中 `expressions` 的同名项。

## 口横広げ

| 顺序 | 阶段 | 计算准则 | 条件 | 数值路径 | 实现 |
| --- | --- | --- | --- | --- | --- |
| 1 | 对称策略 | 允许强制左右对称；正侧完成约束后直接镜像最终坐标到负侧，不再两侧平均。独立眼眉在相关顶点可配对时只计算正侧，不要求三角面划分相同。跨中线口型保留整体求解；活动顶点无法配对则跳过。镜像后的翻折数量写入报告 | 生成时开启强制对称 | can_symmetrize / special / relation | procedural_symmetry |
| 2 | 输入 | 按当前标记读取；已删除必要曲线所依赖的表情跳过 | 存在对应分区时执行 | recipe | procedural_rig.checkpoint |
| 3 | 嘴型目标 | 按口宽适配目标轮廓，保留上下唇拓扑归属 | 存在对应分区时执行 | recipe | procedural_atoms.mouth_outline |
| 4 | 人中与唇周 | 开口沿当前 Face 的局部轮廓采样有限深度变化，不沿初始切线无限外推；唇缘邻近面片共同平移，保留原斜面与厚度，再向周围脸皮平滑过渡 | 存在对应分区时执行 | recipe | procedural_lips.surface_motion / deform |
| 5 | 皮肤求解 | 固定眼口控制点，沿 Face 邻接平滑传播 | 存在对应分区时执行 | recipe | procedural_skin.EyelidSkin.deform |
| 6 | 防破面 | 保持轮廓约束，限制局部修正，残余冲突写入报告 | 存在对应分区时执行 | recipe | procedural_constraints.finalize_skin |
| 7 | 风格设置 | 下眼睑参与量在可行闭合范围中选择接合位置，不改变下眼睑 30% 上移及笑眼弧顶额外 10% 的硬上限。笑眼弧度与形态保持调整曲线偏好，闭合、接触和厚度优先。组合、曲线写回沿用生成时保存的风格设置 | 存在对应分区时执行 | recipe | procedural_ui.generation_options / procedural_binding.styled_closure |
| 8 | 闭眼层次 | 下睫毛随实际下眼眶的连续位移和旋转运动。闭眼时将整条下睫毛的上下缘收在上睫毛投影内，再求解前后层次。Face 接触后复查并修正遮盖，最终悬空和覆盖不足单独报告 | 存在对应分区时执行 | recipe | procedural_lashes.follow_lower_rim / cover_lower_band / finish_closed_order |
| 9 | 计算设备 | Windows NVIDIA CUDA 可用时，以双精度 GPU 内核求解三角面投影接触。小任务、缺少运行库、显存或调用失败时使用 CPU。两种设备共用几何规则、容差和可移动条件，报告设备、调用数与回退原因 | 存在对应分区时执行 | recipe | procedural_gpu.try_depth |
| 10 | 口腔 | 口内边界固定到实际唇缘，内部连续变形；强制镜像后重新贴合 Face 与 Mouth，避免两次表面插值产生小接缝 | 存在对应分区时执行 | recipe | procedural_cavity.deform |
| 11 | 牙齿 | 内置口型按 Original 张口时牙片的一致运动校准上下排，再按嘴宽适配各自位移与旋转，不重复叠加竖向随唇浮动。原参考静止的牙齿保持原位；目标有小间隙时，下牙整组上移至首次接触，最多嘴宽的 30%，缺少独立上下牙则跳过。未校准的自定义或下颌动作保留有界随唇处理。接触可先收回校准动作中的前移，再按牙弓与嘴宽的较大值取 6.5% 额度整排后移，保留牙弓及上下行程；未校准动作仍采用 2.5% 共同后移及 4% 局部后移。检查局部修正是否引入新的三角面翻折；额度不足记录穿插，不向外推 Face，不缩放牙弓，不改变 Basis | 存在对应分区时执行 | recipe | procedural_constraints.close_dental_contact / procedural_contacts.oral_face |
| 12 | 口内接触 | 按唇缘相连拓扑选择 Face 接触面，包含斜面及内翻唇面；牙齿及口腔退回面部内侧，口腔唇缘固定。取消舌头随整排牙齿最前点后退；牙齿与舌头的接触只由实际三角面交叉触发。舌头上表面避开下口腔，Basis 同样检查；接触位移上限取舌长 12% 和口宽 8% 的较小值，同次修正反复检查共用额度；超出额度报告冲突 | 存在对应分区时执行 | recipe | procedural_contacts.finish / tongue_teeth / tongue_side |
| 13 | 写入 | 表情形态键、口腔联动和最终变形曲线一起保存 | 存在对应分区时执行 | recipe | procedural_generate.generate |
| 14 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.mouth | procedural_atoms.merge |
| 15 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.mouth_reference | procedural_atoms.merge |
| 16 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.oral | procedural_atoms.merge |

数值定义：JSON 中 `expressions` 的同名项。

## 口横狭め

| 顺序 | 阶段 | 计算准则 | 条件 | 数值路径 | 实现 |
| --- | --- | --- | --- | --- | --- |
| 1 | 对称策略 | 允许强制左右对称；正侧完成约束后直接镜像最终坐标到负侧，不再两侧平均。独立眼眉在相关顶点可配对时只计算正侧，不要求三角面划分相同。跨中线口型保留整体求解；活动顶点无法配对则跳过。镜像后的翻折数量写入报告 | 生成时开启强制对称 | can_symmetrize / special / relation | procedural_symmetry |
| 2 | 输入 | 按当前标记读取；已删除必要曲线所依赖的表情跳过 | 存在对应分区时执行 | recipe | procedural_rig.checkpoint |
| 3 | 嘴型目标 | 按口宽适配目标轮廓，保留上下唇拓扑归属 | 存在对应分区时执行 | recipe | procedural_atoms.mouth_outline |
| 4 | 人中与唇周 | 开口沿当前 Face 的局部轮廓采样有限深度变化，不沿初始切线无限外推；唇缘邻近面片共同平移，保留原斜面与厚度，再向周围脸皮平滑过渡 | 存在对应分区时执行 | recipe | procedural_lips.surface_motion / deform |
| 5 | 皮肤求解 | 固定眼口控制点，沿 Face 邻接平滑传播 | 存在对应分区时执行 | recipe | procedural_skin.EyelidSkin.deform |
| 6 | 防破面 | 保持轮廓约束，限制局部修正，残余冲突写入报告 | 存在对应分区时执行 | recipe | procedural_constraints.finalize_skin |
| 7 | 风格设置 | 下眼睑参与量在可行闭合范围中选择接合位置，不改变下眼睑 30% 上移及笑眼弧顶额外 10% 的硬上限。笑眼弧度与形态保持调整曲线偏好，闭合、接触和厚度优先。组合、曲线写回沿用生成时保存的风格设置 | 存在对应分区时执行 | recipe | procedural_ui.generation_options / procedural_binding.styled_closure |
| 8 | 闭眼层次 | 下睫毛随实际下眼眶的连续位移和旋转运动。闭眼时将整条下睫毛的上下缘收在上睫毛投影内，再求解前后层次。Face 接触后复查并修正遮盖，最终悬空和覆盖不足单独报告 | 存在对应分区时执行 | recipe | procedural_lashes.follow_lower_rim / cover_lower_band / finish_closed_order |
| 9 | 计算设备 | Windows NVIDIA CUDA 可用时，以双精度 GPU 内核求解三角面投影接触。小任务、缺少运行库、显存或调用失败时使用 CPU。两种设备共用几何规则、容差和可移动条件，报告设备、调用数与回退原因 | 存在对应分区时执行 | recipe | procedural_gpu.try_depth |
| 10 | 口腔 | 口内边界固定到实际唇缘，内部连续变形；强制镜像后重新贴合 Face 与 Mouth，避免两次表面插值产生小接缝 | 存在对应分区时执行 | recipe | procedural_cavity.deform |
| 11 | 牙齿 | 内置口型按 Original 张口时牙片的一致运动校准上下排，再按嘴宽适配各自位移与旋转，不重复叠加竖向随唇浮动。原参考静止的牙齿保持原位；目标有小间隙时，下牙整组上移至首次接触，最多嘴宽的 30%，缺少独立上下牙则跳过。未校准的自定义或下颌动作保留有界随唇处理。接触可先收回校准动作中的前移，再按牙弓与嘴宽的较大值取 6.5% 额度整排后移，保留牙弓及上下行程；未校准动作仍采用 2.5% 共同后移及 4% 局部后移。检查局部修正是否引入新的三角面翻折；额度不足记录穿插，不向外推 Face，不缩放牙弓，不改变 Basis | 存在对应分区时执行 | recipe | procedural_constraints.close_dental_contact / procedural_contacts.oral_face |
| 12 | 口内接触 | 按唇缘相连拓扑选择 Face 接触面，包含斜面及内翻唇面；牙齿及口腔退回面部内侧，口腔唇缘固定。取消舌头随整排牙齿最前点后退；牙齿与舌头的接触只由实际三角面交叉触发。舌头上表面避开下口腔，Basis 同样检查；接触位移上限取舌长 12% 和口宽 8% 的较小值，同次修正反复检查共用额度；超出额度报告冲突 | 存在对应分区时执行 | recipe | procedural_contacts.finish / tongue_teeth / tongue_side |
| 13 | 写入 | 表情形态键、口腔联动和最终变形曲线一起保存 | 存在对应分区时执行 | recipe | procedural_generate.generate |
| 14 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.mouth | procedural_atoms.merge |
| 15 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.mouth_reference | procedural_atoms.merge |
| 16 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.oral | procedural_atoms.merge |

数值定义：JSON 中 `expressions` 的同名项。

## 舌広げ

| 顺序 | 阶段 | 计算准则 | 条件 | 数值路径 | 实现 |
| --- | --- | --- | --- | --- | --- |
| 1 | 对称策略 | 允许强制左右对称；正侧完成约束后直接镜像最终坐标到负侧，不再两侧平均。独立眼眉在相关顶点可配对时只计算正侧，不要求三角面划分相同。跨中线口型保留整体求解；活动顶点无法配对则跳过。镜像后的翻折数量写入报告 | 生成时开启强制对称 | can_symmetrize / special / relation | procedural_symmetry |
| 2 | 输入 | 按当前标记读取；已删除必要曲线所依赖的表情跳过 | 存在对应分区时执行 | recipe | procedural_rig.checkpoint |
| 3 | 舌头目标 | 普通口型保留 Original 舌头的整体位移和旋转。てへぺろ按原曲线侧伸，ぺろっ居中下卷；截面沿等弧长曲线弯曲，过厚或过宽的目标舌头在吐舌形态中按原参考与嘴宽的比例等比缩小，不修改生成的 Basis。尺寸检查保留旋转和平移，限制额外边长 ≤ Basis 的 1.04 倍；沿去除整体旋转后的方向检查 X/Y 跨度 ≤ 1.08/1.04 倍，Z 跨度 ≤ 原厚度 + 舌长的 28%。出口局部最多变薄 15% | 存在对应分区时执行 | recipe | procedural_tongue.reference_pose / deform / limit_size |
| 4 | 皮肤求解 | 固定眼口控制点，沿 Face 邻接平滑传播 | 存在对应分区时执行 | recipe | procedural_skin.EyelidSkin.deform |
| 5 | 防破面 | 保持轮廓约束，限制局部修正，残余冲突写入报告 | 存在对应分区时执行 | recipe | procedural_constraints.finalize_skin |
| 6 | 风格设置 | 下眼睑参与量在可行闭合范围中选择接合位置，不改变下眼睑 30% 上移及笑眼弧顶额外 10% 的硬上限。笑眼弧度与形态保持调整曲线偏好，闭合、接触和厚度优先。组合、曲线写回沿用生成时保存的风格设置 | 存在对应分区时执行 | recipe | procedural_ui.generation_options / procedural_binding.styled_closure |
| 7 | 闭眼层次 | 下睫毛随实际下眼眶的连续位移和旋转运动。闭眼时将整条下睫毛的上下缘收在上睫毛投影内，再求解前后层次。Face 接触后复查并修正遮盖，最终悬空和覆盖不足单独报告 | 存在对应分区时执行 | recipe | procedural_lashes.follow_lower_rim / cover_lower_band / finish_closed_order |
| 8 | 计算设备 | Windows NVIDIA CUDA 可用时，以双精度 GPU 内核求解三角面投影接触。小任务、缺少运行库、显存或调用失败时使用 CPU。两种设备共用几何规则、容差和可移动条件，报告设备、调用数与回退原因 | 存在对应分区时执行 | recipe | procedural_gpu.try_depth |
| 9 | 口腔 | 口内边界固定到实际唇缘，内部连续变形；强制镜像后重新贴合 Face 与 Mouth，避免两次表面插值产生小接缝 | 存在对应分区时执行 | recipe | procedural_cavity.deform |
| 10 | 牙齿 | 内置口型按 Original 张口时牙片的一致运动校准上下排，再按嘴宽适配各自位移与旋转，不重复叠加竖向随唇浮动。原参考静止的牙齿保持原位；目标有小间隙时，下牙整组上移至首次接触，最多嘴宽的 30%，缺少独立上下牙则跳过。未校准的自定义或下颌动作保留有界随唇处理。接触可先收回校准动作中的前移，再按牙弓与嘴宽的较大值取 6.5% 额度整排后移，保留牙弓及上下行程；未校准动作仍采用 2.5% 共同后移及 4% 局部后移。检查局部修正是否引入新的三角面翻折；额度不足记录穿插，不向外推 Face，不缩放牙弓，不改变 Basis | 存在对应分区时执行 | recipe | procedural_constraints.close_dental_contact / procedural_contacts.oral_face |
| 11 | 吐舌接触 | 检查外露下表面和外侧面；独立舌头整体平移避开 Face，避免把外露截面拉离舌根；焊接舌头保留局部处理及最终尺寸限制，冲突写入报告 | 存在对应分区时执行 | recipe | procedural_tongue.keep_exterior |
| 12 | 口内接触 | 按唇缘相连拓扑选择 Face 接触面，包含斜面及内翻唇面；牙齿及口腔退回面部内侧，口腔唇缘固定。取消舌头随整排牙齿最前点后退；牙齿与舌头的接触只由实际三角面交叉触发。舌头上表面避开下口腔，Basis 同样检查；接触位移上限取舌长 12% 和口宽 8% 的较小值，同次修正反复检查共用额度；超出额度报告冲突 | 存在对应分区时执行 | recipe | procedural_contacts.finish / tongue_teeth / tongue_side |
| 13 | 写入 | 表情形态键、口腔联动和最终变形曲线一起保存 | 存在对应分区时执行 | recipe | procedural_generate.generate |
| 14 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.tongue | procedural_atoms.merge |

数值定义：JSON 中 `expressions` 的同名项。

## 下顎調整

| 顺序 | 阶段 | 计算准则 | 条件 | 数值路径 | 实现 |
| --- | --- | --- | --- | --- | --- |
| 1 | 对称策略 | 允许强制左右对称；正侧完成约束后直接镜像最终坐标到负侧，不再两侧平均。独立眼眉在相关顶点可配对时只计算正侧，不要求三角面划分相同。跨中线口型保留整体求解；活动顶点无法配对则跳过。镜像后的翻折数量写入报告 | 生成时开启强制对称 | can_symmetrize / special / relation | procedural_symmetry |
| 2 | 输入 | 按当前标记读取；已删除必要曲线所依赖的表情跳过 | 存在对应分区时执行 | recipe | procedural_rig.checkpoint |
| 3 | 下颌目标 | 以口宽归一化并按距口部的范围连续衰减 | 存在对应分区时执行 | recipe | procedural_atoms.solve |
| 4 | 皮肤求解 | 固定眼口控制点，沿 Face 邻接平滑传播 | 存在对应分区时执行 | recipe | procedural_skin.EyelidSkin.deform |
| 5 | 防破面 | 保持轮廓约束，限制局部修正，残余冲突写入报告 | 存在对应分区时执行 | recipe | procedural_constraints.finalize_skin |
| 6 | 风格设置 | 下眼睑参与量在可行闭合范围中选择接合位置，不改变下眼睑 30% 上移及笑眼弧顶额外 10% 的硬上限。笑眼弧度与形态保持调整曲线偏好，闭合、接触和厚度优先。组合、曲线写回沿用生成时保存的风格设置 | 存在对应分区时执行 | recipe | procedural_ui.generation_options / procedural_binding.styled_closure |
| 7 | 闭眼层次 | 下睫毛随实际下眼眶的连续位移和旋转运动。闭眼时将整条下睫毛的上下缘收在上睫毛投影内，再求解前后层次。Face 接触后复查并修正遮盖，最终悬空和覆盖不足单独报告 | 存在对应分区时执行 | recipe | procedural_lashes.follow_lower_rim / cover_lower_band / finish_closed_order |
| 8 | 计算设备 | Windows NVIDIA CUDA 可用时，以双精度 GPU 内核求解三角面投影接触。小任务、缺少运行库、显存或调用失败时使用 CPU。两种设备共用几何规则、容差和可移动条件，报告设备、调用数与回退原因 | 存在对应分区时执行 | recipe | procedural_gpu.try_depth |
| 9 | 口腔 | 口内边界固定到实际唇缘，内部连续变形；强制镜像后重新贴合 Face 与 Mouth，避免两次表面插值产生小接缝 | 存在对应分区时执行 | recipe | procedural_cavity.deform |
| 10 | 牙齿 | 内置口型按 Original 张口时牙片的一致运动校准上下排，再按嘴宽适配各自位移与旋转，不重复叠加竖向随唇浮动。原参考静止的牙齿保持原位；目标有小间隙时，下牙整组上移至首次接触，最多嘴宽的 30%，缺少独立上下牙则跳过。未校准的自定义或下颌动作保留有界随唇处理。接触可先收回校准动作中的前移，再按牙弓与嘴宽的较大值取 6.5% 额度整排后移，保留牙弓及上下行程；未校准动作仍采用 2.5% 共同后移及 4% 局部后移。检查局部修正是否引入新的三角面翻折；额度不足记录穿插，不向外推 Face，不缩放牙弓，不改变 Basis | 存在对应分区时执行 | recipe | procedural_constraints.close_dental_contact / procedural_contacts.oral_face |
| 11 | 口内接触 | 按唇缘相连拓扑选择 Face 接触面，包含斜面及内翻唇面；牙齿及口腔退回面部内侧，口腔唇缘固定。取消舌头随整排牙齿最前点后退；牙齿与舌头的接触只由实际三角面交叉触发。舌头上表面避开下口腔，Basis 同样检查；接触位移上限取舌长 12% 和口宽 8% 的较小值，同次修正反复检查共用额度；超出额度报告冲突 | 存在对应分区时执行 | recipe | procedural_contacts.finish / tongue_teeth / tongue_side |
| 12 | 写入 | 表情形态键、口腔联动和最终变形曲线一起保存 | 存在对应分区时执行 | recipe | procedural_generate.generate |
| 13 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.jaw | procedural_atoms.merge |

数值定义：JSON 中 `expressions` 的同名项。

## 真面目

| 顺序 | 阶段 | 计算准则 | 条件 | 数值路径 | 实现 |
| --- | --- | --- | --- | --- | --- |
| 1 | 对称策略 | 允许强制左右对称；正侧完成约束后直接镜像最终坐标到负侧，不再两侧平均。独立眼眉在相关顶点可配对时只计算正侧，不要求三角面划分相同。跨中线口型保留整体求解；活动顶点无法配对则跳过。镜像后的翻折数量写入报告 | 生成时开启强制对称 | can_symmetrize / special / relation | procedural_symmetry |
| 2 | 输入 | 按当前标记读取；已删除必要曲线所依赖的表情跳过 | 存在对应分区时执行 | recipe | procedural_rig.checkpoint |
| 3 | 眉毛目标 | 以同侧眉毛共同中心和眼宽计算位置，并叠加当前校正 | 存在对应分区时执行 | recipe | procedural_atoms.solve |
| 4 | 皮肤求解 | 固定眼口控制点，沿 Face 邻接平滑传播 | 存在对应分区时执行 | recipe | procedural_skin.EyelidSkin.deform |
| 5 | 防破面 | 保持轮廓约束，限制局部修正，残余冲突写入报告 | 存在对应分区时执行 | recipe | procedural_constraints.finalize_skin |
| 6 | 风格设置 | 下眼睑参与量在可行闭合范围中选择接合位置，不改变下眼睑 30% 上移及笑眼弧顶额外 10% 的硬上限。笑眼弧度与形态保持调整曲线偏好，闭合、接触和厚度优先。组合、曲线写回沿用生成时保存的风格设置 | 存在对应分区时执行 | recipe | procedural_ui.generation_options / procedural_binding.styled_closure |
| 7 | 闭眼层次 | 下睫毛随实际下眼眶的连续位移和旋转运动。闭眼时将整条下睫毛的上下缘收在上睫毛投影内，再求解前后层次。Face 接触后复查并修正遮盖，最终悬空和覆盖不足单独报告 | 存在对应分区时执行 | recipe | procedural_lashes.follow_lower_rim / cover_lower_band / finish_closed_order |
| 8 | 计算设备 | Windows NVIDIA CUDA 可用时，以双精度 GPU 内核求解三角面投影接触。小任务、缺少运行库、显存或调用失败时使用 CPU。两种设备共用几何规则、容差和可移动条件，报告设备、调用数与回退原因 | 存在对应分区时执行 | recipe | procedural_gpu.try_depth |
| 9 | 口腔 | 口内边界固定到实际唇缘，内部连续变形；强制镜像后重新贴合 Face 与 Mouth，避免两次表面插值产生小接缝 | 存在对应分区时执行 | recipe | procedural_cavity.deform |
| 10 | 牙齿 | 内置口型按 Original 张口时牙片的一致运动校准上下排，再按嘴宽适配各自位移与旋转，不重复叠加竖向随唇浮动。原参考静止的牙齿保持原位；目标有小间隙时，下牙整组上移至首次接触，最多嘴宽的 30%，缺少独立上下牙则跳过。未校准的自定义或下颌动作保留有界随唇处理。接触可先收回校准动作中的前移，再按牙弓与嘴宽的较大值取 6.5% 额度整排后移，保留牙弓及上下行程；未校准动作仍采用 2.5% 共同后移及 4% 局部后移。检查局部修正是否引入新的三角面翻折；额度不足记录穿插，不向外推 Face，不缩放牙弓，不改变 Basis | 存在对应分区时执行 | recipe | procedural_constraints.close_dental_contact / procedural_contacts.oral_face |
| 11 | 口内接触 | 按唇缘相连拓扑选择 Face 接触面，包含斜面及内翻唇面；牙齿及口腔退回面部内侧，口腔唇缘固定。取消舌头随整排牙齿最前点后退；牙齿与舌头的接触只由实际三角面交叉触发。舌头上表面避开下口腔，Basis 同样检查；接触位移上限取舌长 12% 和口宽 8% 的较小值，同次修正反复检查共用额度；超出额度报告冲突 | 存在对应分区时执行 | recipe | procedural_contacts.finish / tongue_teeth / tongue_side |
| 12 | 写入 | 表情形态键、口腔联动和最终变形曲线一起保存 | 存在对应分区时执行 | recipe | procedural_generate.generate |
| 13 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.brows | procedural_atoms.merge |

数值定义：JSON 中 `expressions` 的同名项。

## 困る

| 顺序 | 阶段 | 计算准则 | 条件 | 数值路径 | 实现 |
| --- | --- | --- | --- | --- | --- |
| 1 | 对称策略 | 允许强制左右对称；正侧完成约束后直接镜像最终坐标到负侧，不再两侧平均。独立眼眉在相关顶点可配对时只计算正侧，不要求三角面划分相同。跨中线口型保留整体求解；活动顶点无法配对则跳过。镜像后的翻折数量写入报告 | 生成时开启强制对称 | can_symmetrize / special / relation | procedural_symmetry |
| 2 | 输入 | 按当前标记读取；已删除必要曲线所依赖的表情跳过 | 存在对应分区时执行 | recipe | procedural_rig.checkpoint |
| 3 | 眉毛目标 | 以同侧眉毛共同中心和眼宽计算位置，并叠加当前校正 | 存在对应分区时执行 | recipe | procedural_atoms.solve |
| 4 | 皮肤求解 | 固定眼口控制点，沿 Face 邻接平滑传播 | 存在对应分区时执行 | recipe | procedural_skin.EyelidSkin.deform |
| 5 | 防破面 | 保持轮廓约束，限制局部修正，残余冲突写入报告 | 存在对应分区时执行 | recipe | procedural_constraints.finalize_skin |
| 6 | 风格设置 | 下眼睑参与量在可行闭合范围中选择接合位置，不改变下眼睑 30% 上移及笑眼弧顶额外 10% 的硬上限。笑眼弧度与形态保持调整曲线偏好，闭合、接触和厚度优先。组合、曲线写回沿用生成时保存的风格设置 | 存在对应分区时执行 | recipe | procedural_ui.generation_options / procedural_binding.styled_closure |
| 7 | 闭眼层次 | 下睫毛随实际下眼眶的连续位移和旋转运动。闭眼时将整条下睫毛的上下缘收在上睫毛投影内，再求解前后层次。Face 接触后复查并修正遮盖，最终悬空和覆盖不足单独报告 | 存在对应分区时执行 | recipe | procedural_lashes.follow_lower_rim / cover_lower_band / finish_closed_order |
| 8 | 计算设备 | Windows NVIDIA CUDA 可用时，以双精度 GPU 内核求解三角面投影接触。小任务、缺少运行库、显存或调用失败时使用 CPU。两种设备共用几何规则、容差和可移动条件，报告设备、调用数与回退原因 | 存在对应分区时执行 | recipe | procedural_gpu.try_depth |
| 9 | 口腔 | 口内边界固定到实际唇缘，内部连续变形；强制镜像后重新贴合 Face 与 Mouth，避免两次表面插值产生小接缝 | 存在对应分区时执行 | recipe | procedural_cavity.deform |
| 10 | 牙齿 | 内置口型按 Original 张口时牙片的一致运动校准上下排，再按嘴宽适配各自位移与旋转，不重复叠加竖向随唇浮动。原参考静止的牙齿保持原位；目标有小间隙时，下牙整组上移至首次接触，最多嘴宽的 30%，缺少独立上下牙则跳过。未校准的自定义或下颌动作保留有界随唇处理。接触可先收回校准动作中的前移，再按牙弓与嘴宽的较大值取 6.5% 额度整排后移，保留牙弓及上下行程；未校准动作仍采用 2.5% 共同后移及 4% 局部后移。检查局部修正是否引入新的三角面翻折；额度不足记录穿插，不向外推 Face，不缩放牙弓，不改变 Basis | 存在对应分区时执行 | recipe | procedural_constraints.close_dental_contact / procedural_contacts.oral_face |
| 11 | 口内接触 | 按唇缘相连拓扑选择 Face 接触面，包含斜面及内翻唇面；牙齿及口腔退回面部内侧，口腔唇缘固定。取消舌头随整排牙齿最前点后退；牙齿与舌头的接触只由实际三角面交叉触发。舌头上表面避开下口腔，Basis 同样检查；接触位移上限取舌长 12% 和口宽 8% 的较小值，同次修正反复检查共用额度；超出额度报告冲突 | 存在对应分区时执行 | recipe | procedural_contacts.finish / tongue_teeth / tongue_side |
| 12 | 写入 | 表情形态键、口腔联动和最终变形曲线一起保存 | 存在对应分区时执行 | recipe | procedural_generate.generate |
| 13 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.brows | procedural_atoms.merge |

数值定义：JSON 中 `expressions` 的同名项。

## にこり

| 顺序 | 阶段 | 计算准则 | 条件 | 数值路径 | 实现 |
| --- | --- | --- | --- | --- | --- |
| 1 | 对称策略 | 允许强制左右对称；正侧完成约束后直接镜像最终坐标到负侧，不再两侧平均。独立眼眉在相关顶点可配对时只计算正侧，不要求三角面划分相同。跨中线口型保留整体求解；活动顶点无法配对则跳过。镜像后的翻折数量写入报告 | 生成时开启强制对称 | can_symmetrize / special / relation | procedural_symmetry |
| 2 | 输入 | 按当前标记读取；已删除必要曲线所依赖的表情跳过 | 存在对应分区时执行 | recipe | procedural_rig.checkpoint |
| 3 | 眉毛目标 | 以同侧眉毛共同中心和眼宽计算位置，并叠加当前校正 | 存在对应分区时执行 | recipe | procedural_atoms.solve |
| 4 | 皮肤求解 | 固定眼口控制点，沿 Face 邻接平滑传播 | 存在对应分区时执行 | recipe | procedural_skin.EyelidSkin.deform |
| 5 | 防破面 | 保持轮廓约束，限制局部修正，残余冲突写入报告 | 存在对应分区时执行 | recipe | procedural_constraints.finalize_skin |
| 6 | 风格设置 | 下眼睑参与量在可行闭合范围中选择接合位置，不改变下眼睑 30% 上移及笑眼弧顶额外 10% 的硬上限。笑眼弧度与形态保持调整曲线偏好，闭合、接触和厚度优先。组合、曲线写回沿用生成时保存的风格设置 | 存在对应分区时执行 | recipe | procedural_ui.generation_options / procedural_binding.styled_closure |
| 7 | 闭眼层次 | 下睫毛随实际下眼眶的连续位移和旋转运动。闭眼时将整条下睫毛的上下缘收在上睫毛投影内，再求解前后层次。Face 接触后复查并修正遮盖，最终悬空和覆盖不足单独报告 | 存在对应分区时执行 | recipe | procedural_lashes.follow_lower_rim / cover_lower_band / finish_closed_order |
| 8 | 计算设备 | Windows NVIDIA CUDA 可用时，以双精度 GPU 内核求解三角面投影接触。小任务、缺少运行库、显存或调用失败时使用 CPU。两种设备共用几何规则、容差和可移动条件，报告设备、调用数与回退原因 | 存在对应分区时执行 | recipe | procedural_gpu.try_depth |
| 9 | 口腔 | 口内边界固定到实际唇缘，内部连续变形；强制镜像后重新贴合 Face 与 Mouth，避免两次表面插值产生小接缝 | 存在对应分区时执行 | recipe | procedural_cavity.deform |
| 10 | 牙齿 | 内置口型按 Original 张口时牙片的一致运动校准上下排，再按嘴宽适配各自位移与旋转，不重复叠加竖向随唇浮动。原参考静止的牙齿保持原位；目标有小间隙时，下牙整组上移至首次接触，最多嘴宽的 30%，缺少独立上下牙则跳过。未校准的自定义或下颌动作保留有界随唇处理。接触可先收回校准动作中的前移，再按牙弓与嘴宽的较大值取 6.5% 额度整排后移，保留牙弓及上下行程；未校准动作仍采用 2.5% 共同后移及 4% 局部后移。检查局部修正是否引入新的三角面翻折；额度不足记录穿插，不向外推 Face，不缩放牙弓，不改变 Basis | 存在对应分区时执行 | recipe | procedural_constraints.close_dental_contact / procedural_contacts.oral_face |
| 11 | 口内接触 | 按唇缘相连拓扑选择 Face 接触面，包含斜面及内翻唇面；牙齿及口腔退回面部内侧，口腔唇缘固定。取消舌头随整排牙齿最前点后退；牙齿与舌头的接触只由实际三角面交叉触发。舌头上表面避开下口腔，Basis 同样检查；接触位移上限取舌长 12% 和口宽 8% 的较小值，同次修正反复检查共用额度；超出额度报告冲突 | 存在对应分区时执行 | recipe | procedural_contacts.finish / tongue_teeth / tongue_side |
| 12 | 写入 | 表情形态键、口腔联动和最终变形曲线一起保存 | 存在对应分区时执行 | recipe | procedural_generate.generate |
| 13 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.brows | procedural_atoms.merge |

数值定义：JSON 中 `expressions` 的同名项。

## 怒り

| 顺序 | 阶段 | 计算准则 | 条件 | 数值路径 | 实现 |
| --- | --- | --- | --- | --- | --- |
| 1 | 对称策略 | 允许强制左右对称；正侧完成约束后直接镜像最终坐标到负侧，不再两侧平均。独立眼眉在相关顶点可配对时只计算正侧，不要求三角面划分相同。跨中线口型保留整体求解；活动顶点无法配对则跳过。镜像后的翻折数量写入报告 | 生成时开启强制对称 | can_symmetrize / special / relation | procedural_symmetry |
| 2 | 输入 | 按当前标记读取；已删除必要曲线所依赖的表情跳过 | 存在对应分区时执行 | recipe | procedural_rig.checkpoint |
| 3 | 眉毛目标 | 以同侧眉毛共同中心和眼宽计算位置，并叠加当前校正 | 存在对应分区时执行 | recipe | procedural_atoms.solve |
| 4 | 皮肤求解 | 固定眼口控制点，沿 Face 邻接平滑传播 | 存在对应分区时执行 | recipe | procedural_skin.EyelidSkin.deform |
| 5 | 防破面 | 保持轮廓约束，限制局部修正，残余冲突写入报告 | 存在对应分区时执行 | recipe | procedural_constraints.finalize_skin |
| 6 | 风格设置 | 下眼睑参与量在可行闭合范围中选择接合位置，不改变下眼睑 30% 上移及笑眼弧顶额外 10% 的硬上限。笑眼弧度与形态保持调整曲线偏好，闭合、接触和厚度优先。组合、曲线写回沿用生成时保存的风格设置 | 存在对应分区时执行 | recipe | procedural_ui.generation_options / procedural_binding.styled_closure |
| 7 | 闭眼层次 | 下睫毛随实际下眼眶的连续位移和旋转运动。闭眼时将整条下睫毛的上下缘收在上睫毛投影内，再求解前后层次。Face 接触后复查并修正遮盖，最终悬空和覆盖不足单独报告 | 存在对应分区时执行 | recipe | procedural_lashes.follow_lower_rim / cover_lower_band / finish_closed_order |
| 8 | 计算设备 | Windows NVIDIA CUDA 可用时，以双精度 GPU 内核求解三角面投影接触。小任务、缺少运行库、显存或调用失败时使用 CPU。两种设备共用几何规则、容差和可移动条件，报告设备、调用数与回退原因 | 存在对应分区时执行 | recipe | procedural_gpu.try_depth |
| 9 | 口腔 | 口内边界固定到实际唇缘，内部连续变形；强制镜像后重新贴合 Face 与 Mouth，避免两次表面插值产生小接缝 | 存在对应分区时执行 | recipe | procedural_cavity.deform |
| 10 | 牙齿 | 内置口型按 Original 张口时牙片的一致运动校准上下排，再按嘴宽适配各自位移与旋转，不重复叠加竖向随唇浮动。原参考静止的牙齿保持原位；目标有小间隙时，下牙整组上移至首次接触，最多嘴宽的 30%，缺少独立上下牙则跳过。未校准的自定义或下颌动作保留有界随唇处理。接触可先收回校准动作中的前移，再按牙弓与嘴宽的较大值取 6.5% 额度整排后移，保留牙弓及上下行程；未校准动作仍采用 2.5% 共同后移及 4% 局部后移。检查局部修正是否引入新的三角面翻折；额度不足记录穿插，不向外推 Face，不缩放牙弓，不改变 Basis | 存在对应分区时执行 | recipe | procedural_constraints.close_dental_contact / procedural_contacts.oral_face |
| 11 | 口内接触 | 按唇缘相连拓扑选择 Face 接触面，包含斜面及内翻唇面；牙齿及口腔退回面部内侧，口腔唇缘固定。取消舌头随整排牙齿最前点后退；牙齿与舌头的接触只由实际三角面交叉触发。舌头上表面避开下口腔，Basis 同样检查；接触位移上限取舌长 12% 和口宽 8% 的较小值，同次修正反复检查共用额度；超出额度报告冲突 | 存在对应分区时执行 | recipe | procedural_contacts.finish / tongue_teeth / tongue_side |
| 12 | 写入 | 表情形态键、口腔联动和最终变形曲线一起保存 | 存在对应分区时执行 | recipe | procedural_generate.generate |
| 13 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.brows | procedural_atoms.merge |

数值定义：JSON 中 `expressions` 的同名项。

## 恥ずかしい

| 顺序 | 阶段 | 计算准则 | 条件 | 数值路径 | 实现 |
| --- | --- | --- | --- | --- | --- |
| 1 | 对称策略 | 允许强制左右对称；正侧完成约束后直接镜像最终坐标到负侧，不再两侧平均。独立眼眉在相关顶点可配对时只计算正侧，不要求三角面划分相同。跨中线口型保留整体求解；活动顶点无法配对则跳过。镜像后的翻折数量写入报告 | 生成时开启强制对称 | can_symmetrize / special / relation | procedural_symmetry |
| 2 | 输入 | 按当前标记读取；已删除必要曲线所依赖的表情跳过 | 存在对应分区时执行 | recipe | procedural_rig.checkpoint |
| 3 | 眉毛目标 | 以同侧眉毛共同中心和眼宽计算位置，并叠加当前校正 | 存在对应分区时执行 | recipe | procedural_atoms.solve |
| 4 | 皮肤求解 | 固定眼口控制点，沿 Face 邻接平滑传播 | 存在对应分区时执行 | recipe | procedural_skin.EyelidSkin.deform |
| 5 | 防破面 | 保持轮廓约束，限制局部修正，残余冲突写入报告 | 存在对应分区时执行 | recipe | procedural_constraints.finalize_skin |
| 6 | 风格设置 | 下眼睑参与量在可行闭合范围中选择接合位置，不改变下眼睑 30% 上移及笑眼弧顶额外 10% 的硬上限。笑眼弧度与形态保持调整曲线偏好，闭合、接触和厚度优先。组合、曲线写回沿用生成时保存的风格设置 | 存在对应分区时执行 | recipe | procedural_ui.generation_options / procedural_binding.styled_closure |
| 7 | 闭眼层次 | 下睫毛随实际下眼眶的连续位移和旋转运动。闭眼时将整条下睫毛的上下缘收在上睫毛投影内，再求解前后层次。Face 接触后复查并修正遮盖，最终悬空和覆盖不足单独报告 | 存在对应分区时执行 | recipe | procedural_lashes.follow_lower_rim / cover_lower_band / finish_closed_order |
| 8 | 计算设备 | Windows NVIDIA CUDA 可用时，以双精度 GPU 内核求解三角面投影接触。小任务、缺少运行库、显存或调用失败时使用 CPU。两种设备共用几何规则、容差和可移动条件，报告设备、调用数与回退原因 | 存在对应分区时执行 | recipe | procedural_gpu.try_depth |
| 9 | 口腔 | 口内边界固定到实际唇缘，内部连续变形；强制镜像后重新贴合 Face 与 Mouth，避免两次表面插值产生小接缝 | 存在对应分区时执行 | recipe | procedural_cavity.deform |
| 10 | 牙齿 | 内置口型按 Original 张口时牙片的一致运动校准上下排，再按嘴宽适配各自位移与旋转，不重复叠加竖向随唇浮动。原参考静止的牙齿保持原位；目标有小间隙时，下牙整组上移至首次接触，最多嘴宽的 30%，缺少独立上下牙则跳过。未校准的自定义或下颌动作保留有界随唇处理。接触可先收回校准动作中的前移，再按牙弓与嘴宽的较大值取 6.5% 额度整排后移，保留牙弓及上下行程；未校准动作仍采用 2.5% 共同后移及 4% 局部后移。检查局部修正是否引入新的三角面翻折；额度不足记录穿插，不向外推 Face，不缩放牙弓，不改变 Basis | 存在对应分区时执行 | recipe | procedural_constraints.close_dental_contact / procedural_contacts.oral_face |
| 11 | 口内接触 | 按唇缘相连拓扑选择 Face 接触面，包含斜面及内翻唇面；牙齿及口腔退回面部内侧，口腔唇缘固定。取消舌头随整排牙齿最前点后退；牙齿与舌头的接触只由实际三角面交叉触发。舌头上表面避开下口腔，Basis 同样检查；接触位移上限取舌长 12% 和口宽 8% 的较小值，同次修正反复检查共用额度；超出额度报告冲突 | 存在对应分区时执行 | recipe | procedural_contacts.finish / tongue_teeth / tongue_side |
| 12 | 写入 | 表情形态键、口腔联动和最终变形曲线一起保存 | 存在对应分区时执行 | recipe | procedural_generate.generate |
| 13 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.brows | procedural_atoms.merge |

数值定义：JSON 中 `expressions` 的同名项。

## 上

| 顺序 | 阶段 | 计算准则 | 条件 | 数值路径 | 实现 |
| --- | --- | --- | --- | --- | --- |
| 1 | 对称策略 | 允许强制左右对称；正侧完成约束后直接镜像最终坐标到负侧，不再两侧平均。独立眼眉在相关顶点可配对时只计算正侧，不要求三角面划分相同。跨中线口型保留整体求解；活动顶点无法配对则跳过。镜像后的翻折数量写入报告 | 生成时开启强制对称 | can_symmetrize / special / relation | procedural_symmetry |
| 2 | 输入 | 按当前标记读取；已删除必要曲线所依赖的表情跳过 | 存在对应分区时执行 | recipe | procedural_rig.checkpoint |
| 3 | 眉毛目标 | 以同侧眉毛共同中心和眼宽计算位置，并叠加当前校正 | 存在对应分区时执行 | recipe | procedural_atoms.solve |
| 4 | 皮肤求解 | 固定眼口控制点，沿 Face 邻接平滑传播 | 存在对应分区时执行 | recipe | procedural_skin.EyelidSkin.deform |
| 5 | 防破面 | 保持轮廓约束，限制局部修正，残余冲突写入报告 | 存在对应分区时执行 | recipe | procedural_constraints.finalize_skin |
| 6 | 风格设置 | 下眼睑参与量在可行闭合范围中选择接合位置，不改变下眼睑 30% 上移及笑眼弧顶额外 10% 的硬上限。笑眼弧度与形态保持调整曲线偏好，闭合、接触和厚度优先。组合、曲线写回沿用生成时保存的风格设置 | 存在对应分区时执行 | recipe | procedural_ui.generation_options / procedural_binding.styled_closure |
| 7 | 闭眼层次 | 下睫毛随实际下眼眶的连续位移和旋转运动。闭眼时将整条下睫毛的上下缘收在上睫毛投影内，再求解前后层次。Face 接触后复查并修正遮盖，最终悬空和覆盖不足单独报告 | 存在对应分区时执行 | recipe | procedural_lashes.follow_lower_rim / cover_lower_band / finish_closed_order |
| 8 | 计算设备 | Windows NVIDIA CUDA 可用时，以双精度 GPU 内核求解三角面投影接触。小任务、缺少运行库、显存或调用失败时使用 CPU。两种设备共用几何规则、容差和可移动条件，报告设备、调用数与回退原因 | 存在对应分区时执行 | recipe | procedural_gpu.try_depth |
| 9 | 口腔 | 口内边界固定到实际唇缘，内部连续变形；强制镜像后重新贴合 Face 与 Mouth，避免两次表面插值产生小接缝 | 存在对应分区时执行 | recipe | procedural_cavity.deform |
| 10 | 牙齿 | 内置口型按 Original 张口时牙片的一致运动校准上下排，再按嘴宽适配各自位移与旋转，不重复叠加竖向随唇浮动。原参考静止的牙齿保持原位；目标有小间隙时，下牙整组上移至首次接触，最多嘴宽的 30%，缺少独立上下牙则跳过。未校准的自定义或下颌动作保留有界随唇处理。接触可先收回校准动作中的前移，再按牙弓与嘴宽的较大值取 6.5% 额度整排后移，保留牙弓及上下行程；未校准动作仍采用 2.5% 共同后移及 4% 局部后移。检查局部修正是否引入新的三角面翻折；额度不足记录穿插，不向外推 Face，不缩放牙弓，不改变 Basis | 存在对应分区时执行 | recipe | procedural_constraints.close_dental_contact / procedural_contacts.oral_face |
| 11 | 口内接触 | 按唇缘相连拓扑选择 Face 接触面，包含斜面及内翻唇面；牙齿及口腔退回面部内侧，口腔唇缘固定。取消舌头随整排牙齿最前点后退；牙齿与舌头的接触只由实际三角面交叉触发。舌头上表面避开下口腔，Basis 同样检查；接触位移上限取舌长 12% 和口宽 8% 的较小值，同次修正反复检查共用额度；超出额度报告冲突 | 存在对应分区时执行 | recipe | procedural_contacts.finish / tongue_teeth / tongue_side |
| 12 | 写入 | 表情形态键、口腔联动和最终变形曲线一起保存 | 存在对应分区时执行 | recipe | procedural_generate.generate |
| 13 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.brows | procedural_atoms.merge |

数值定义：JSON 中 `expressions` 的同名项。

## 下

| 顺序 | 阶段 | 计算准则 | 条件 | 数值路径 | 实现 |
| --- | --- | --- | --- | --- | --- |
| 1 | 对称策略 | 允许强制左右对称；正侧完成约束后直接镜像最终坐标到负侧，不再两侧平均。独立眼眉在相关顶点可配对时只计算正侧，不要求三角面划分相同。跨中线口型保留整体求解；活动顶点无法配对则跳过。镜像后的翻折数量写入报告 | 生成时开启强制对称 | can_symmetrize / special / relation | procedural_symmetry |
| 2 | 输入 | 按当前标记读取；已删除必要曲线所依赖的表情跳过 | 存在对应分区时执行 | recipe | procedural_rig.checkpoint |
| 3 | 眉毛目标 | 以同侧眉毛共同中心和眼宽计算位置，并叠加当前校正 | 存在对应分区时执行 | recipe | procedural_atoms.solve |
| 4 | 皮肤求解 | 固定眼口控制点，沿 Face 邻接平滑传播 | 存在对应分区时执行 | recipe | procedural_skin.EyelidSkin.deform |
| 5 | 防破面 | 保持轮廓约束，限制局部修正，残余冲突写入报告 | 存在对应分区时执行 | recipe | procedural_constraints.finalize_skin |
| 6 | 风格设置 | 下眼睑参与量在可行闭合范围中选择接合位置，不改变下眼睑 30% 上移及笑眼弧顶额外 10% 的硬上限。笑眼弧度与形态保持调整曲线偏好，闭合、接触和厚度优先。组合、曲线写回沿用生成时保存的风格设置 | 存在对应分区时执行 | recipe | procedural_ui.generation_options / procedural_binding.styled_closure |
| 7 | 闭眼层次 | 下睫毛随实际下眼眶的连续位移和旋转运动。闭眼时将整条下睫毛的上下缘收在上睫毛投影内，再求解前后层次。Face 接触后复查并修正遮盖，最终悬空和覆盖不足单独报告 | 存在对应分区时执行 | recipe | procedural_lashes.follow_lower_rim / cover_lower_band / finish_closed_order |
| 8 | 计算设备 | Windows NVIDIA CUDA 可用时，以双精度 GPU 内核求解三角面投影接触。小任务、缺少运行库、显存或调用失败时使用 CPU。两种设备共用几何规则、容差和可移动条件，报告设备、调用数与回退原因 | 存在对应分区时执行 | recipe | procedural_gpu.try_depth |
| 9 | 口腔 | 口内边界固定到实际唇缘，内部连续变形；强制镜像后重新贴合 Face 与 Mouth，避免两次表面插值产生小接缝 | 存在对应分区时执行 | recipe | procedural_cavity.deform |
| 10 | 牙齿 | 内置口型按 Original 张口时牙片的一致运动校准上下排，再按嘴宽适配各自位移与旋转，不重复叠加竖向随唇浮动。原参考静止的牙齿保持原位；目标有小间隙时，下牙整组上移至首次接触，最多嘴宽的 30%，缺少独立上下牙则跳过。未校准的自定义或下颌动作保留有界随唇处理。接触可先收回校准动作中的前移，再按牙弓与嘴宽的较大值取 6.5% 额度整排后移，保留牙弓及上下行程；未校准动作仍采用 2.5% 共同后移及 4% 局部后移。检查局部修正是否引入新的三角面翻折；额度不足记录穿插，不向外推 Face，不缩放牙弓，不改变 Basis | 存在对应分区时执行 | recipe | procedural_constraints.close_dental_contact / procedural_contacts.oral_face |
| 11 | 口内接触 | 按唇缘相连拓扑选择 Face 接触面，包含斜面及内翻唇面；牙齿及口腔退回面部内侧，口腔唇缘固定。取消舌头随整排牙齿最前点后退；牙齿与舌头的接触只由实际三角面交叉触发。舌头上表面避开下口腔，Basis 同样检查；接触位移上限取舌长 12% 和口宽 8% 的较小值，同次修正反复检查共用额度；超出额度报告冲突 | 存在对应分区时执行 | recipe | procedural_contacts.finish / tongue_teeth / tongue_side |
| 12 | 写入 | 表情形态键、口腔联动和最终变形曲线一起保存 | 存在对应分区时执行 | recipe | procedural_generate.generate |
| 13 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.brows | procedural_atoms.merge |

数值定义：JSON 中 `expressions` 的同名项。

## 前

| 顺序 | 阶段 | 计算准则 | 条件 | 数值路径 | 实现 |
| --- | --- | --- | --- | --- | --- |
| 1 | 对称策略 | 允许强制左右对称；正侧完成约束后直接镜像最终坐标到负侧，不再两侧平均。独立眼眉在相关顶点可配对时只计算正侧，不要求三角面划分相同。跨中线口型保留整体求解；活动顶点无法配对则跳过。镜像后的翻折数量写入报告 | 生成时开启强制对称 | can_symmetrize / special / relation | procedural_symmetry |
| 2 | 输入 | 按当前标记读取；已删除必要曲线所依赖的表情跳过 | 存在对应分区时执行 | recipe | procedural_rig.checkpoint |
| 3 | 眉毛目标 | 以同侧眉毛共同中心和眼宽计算位置，并叠加当前校正 | 存在对应分区时执行 | recipe | procedural_atoms.solve |
| 4 | 皮肤求解 | 固定眼口控制点，沿 Face 邻接平滑传播 | 存在对应分区时执行 | recipe | procedural_skin.EyelidSkin.deform |
| 5 | 防破面 | 保持轮廓约束，限制局部修正，残余冲突写入报告 | 存在对应分区时执行 | recipe | procedural_constraints.finalize_skin |
| 6 | 风格设置 | 下眼睑参与量在可行闭合范围中选择接合位置，不改变下眼睑 30% 上移及笑眼弧顶额外 10% 的硬上限。笑眼弧度与形态保持调整曲线偏好，闭合、接触和厚度优先。组合、曲线写回沿用生成时保存的风格设置 | 存在对应分区时执行 | recipe | procedural_ui.generation_options / procedural_binding.styled_closure |
| 7 | 闭眼层次 | 下睫毛随实际下眼眶的连续位移和旋转运动。闭眼时将整条下睫毛的上下缘收在上睫毛投影内，再求解前后层次。Face 接触后复查并修正遮盖，最终悬空和覆盖不足单独报告 | 存在对应分区时执行 | recipe | procedural_lashes.follow_lower_rim / cover_lower_band / finish_closed_order |
| 8 | 计算设备 | Windows NVIDIA CUDA 可用时，以双精度 GPU 内核求解三角面投影接触。小任务、缺少运行库、显存或调用失败时使用 CPU。两种设备共用几何规则、容差和可移动条件，报告设备、调用数与回退原因 | 存在对应分区时执行 | recipe | procedural_gpu.try_depth |
| 9 | 口腔 | 口内边界固定到实际唇缘，内部连续变形；强制镜像后重新贴合 Face 与 Mouth，避免两次表面插值产生小接缝 | 存在对应分区时执行 | recipe | procedural_cavity.deform |
| 10 | 牙齿 | 内置口型按 Original 张口时牙片的一致运动校准上下排，再按嘴宽适配各自位移与旋转，不重复叠加竖向随唇浮动。原参考静止的牙齿保持原位；目标有小间隙时，下牙整组上移至首次接触，最多嘴宽的 30%，缺少独立上下牙则跳过。未校准的自定义或下颌动作保留有界随唇处理。接触可先收回校准动作中的前移，再按牙弓与嘴宽的较大值取 6.5% 额度整排后移，保留牙弓及上下行程；未校准动作仍采用 2.5% 共同后移及 4% 局部后移。检查局部修正是否引入新的三角面翻折；额度不足记录穿插，不向外推 Face，不缩放牙弓，不改变 Basis | 存在对应分区时执行 | recipe | procedural_constraints.close_dental_contact / procedural_contacts.oral_face |
| 11 | 口内接触 | 按唇缘相连拓扑选择 Face 接触面，包含斜面及内翻唇面；牙齿及口腔退回面部内侧，口腔唇缘固定。取消舌头随整排牙齿最前点后退；牙齿与舌头的接触只由实际三角面交叉触发。舌头上表面避开下口腔，Basis 同样检查；接触位移上限取舌长 12% 和口宽 8% 的较小值，同次修正反复检查共用额度；超出额度报告冲突 | 存在对应分区时执行 | recipe | procedural_contacts.finish / tongue_teeth / tongue_side |
| 12 | 写入 | 表情形态键、口腔联动和最终变形曲线一起保存 | 存在对应分区时执行 | recipe | procedural_generate.generate |
| 13 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.brows | procedural_atoms.merge |

数值定义：JSON 中 `expressions` 的同名项。

## 困る左

| 顺序 | 阶段 | 计算准则 | 条件 | 数值路径 | 实现 |
| --- | --- | --- | --- | --- | --- |
| 1 | 对称策略 | 不对该表情强制镜像；保留子表情、组合或特殊动作的定义 | 生成时开启强制对称 | can_symmetrize / special / relation | procedural_symmetry |
| 2 | 表情依赖 | 引用来源=困る；条件在模型归一化坐标及当前分区中计算，边界连续衰减；不参与强制对称 | 来源可生成且依赖无循环 | relation | expression_relations.Solver |
| 3 | 输入 | 按当前标记读取；已删除必要曲线所依赖的表情跳过 | 存在对应分区时执行 | recipe | procedural_rig.checkpoint |
| 4 | 眉毛目标 | 以同侧眉毛共同中心和眼宽计算位置，并叠加当前校正 | 存在对应分区时执行 | recipe | procedural_atoms.solve |
| 5 | 皮肤求解 | 固定眼口控制点，沿 Face 邻接平滑传播 | 存在对应分区时执行 | recipe | procedural_skin.EyelidSkin.deform |
| 6 | 防破面 | 保持轮廓约束，限制局部修正，残余冲突写入报告 | 存在对应分区时执行 | recipe | procedural_constraints.finalize_skin |
| 7 | 风格设置 | 下眼睑参与量在可行闭合范围中选择接合位置，不改变下眼睑 30% 上移及笑眼弧顶额外 10% 的硬上限。笑眼弧度与形态保持调整曲线偏好，闭合、接触和厚度优先。组合、曲线写回沿用生成时保存的风格设置 | 存在对应分区时执行 | recipe | procedural_ui.generation_options / procedural_binding.styled_closure |
| 8 | 闭眼层次 | 下睫毛随实际下眼眶的连续位移和旋转运动。闭眼时将整条下睫毛的上下缘收在上睫毛投影内，再求解前后层次。Face 接触后复查并修正遮盖，最终悬空和覆盖不足单独报告 | 存在对应分区时执行 | recipe | procedural_lashes.follow_lower_rim / cover_lower_band / finish_closed_order |
| 9 | 计算设备 | Windows NVIDIA CUDA 可用时，以双精度 GPU 内核求解三角面投影接触。小任务、缺少运行库、显存或调用失败时使用 CPU。两种设备共用几何规则、容差和可移动条件，报告设备、调用数与回退原因 | 存在对应分区时执行 | recipe | procedural_gpu.try_depth |
| 10 | 口腔 | 口内边界固定到实际唇缘，内部连续变形；强制镜像后重新贴合 Face 与 Mouth，避免两次表面插值产生小接缝 | 存在对应分区时执行 | recipe | procedural_cavity.deform |
| 11 | 牙齿 | 内置口型按 Original 张口时牙片的一致运动校准上下排，再按嘴宽适配各自位移与旋转，不重复叠加竖向随唇浮动。原参考静止的牙齿保持原位；目标有小间隙时，下牙整组上移至首次接触，最多嘴宽的 30%，缺少独立上下牙则跳过。未校准的自定义或下颌动作保留有界随唇处理。接触可先收回校准动作中的前移，再按牙弓与嘴宽的较大值取 6.5% 额度整排后移，保留牙弓及上下行程；未校准动作仍采用 2.5% 共同后移及 4% 局部后移。检查局部修正是否引入新的三角面翻折；额度不足记录穿插，不向外推 Face，不缩放牙弓，不改变 Basis | 存在对应分区时执行 | recipe | procedural_constraints.close_dental_contact / procedural_contacts.oral_face |
| 12 | 口内接触 | 按唇缘相连拓扑选择 Face 接触面，包含斜面及内翻唇面；牙齿及口腔退回面部内侧，口腔唇缘固定。取消舌头随整排牙齿最前点后退；牙齿与舌头的接触只由实际三角面交叉触发。舌头上表面避开下口腔，Basis 同样检查；接触位移上限取舌长 12% 和口宽 8% 的较小值，同次修正反复检查共用额度；超出额度报告冲突 | 存在对应分区时执行 | recipe | procedural_contacts.finish / tongue_teeth / tongue_side |
| 13 | 写入 | 表情形态键、口腔联动和最终变形曲线一起保存 | 存在对应分区时执行 | recipe | procedural_generate.generate |
| 14 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.brows | procedural_atoms.merge |

数值定义：JSON 中 `expressions` 的同名项。

## 困る右

| 顺序 | 阶段 | 计算准则 | 条件 | 数值路径 | 实现 |
| --- | --- | --- | --- | --- | --- |
| 1 | 对称策略 | 不对该表情强制镜像；保留子表情、组合或特殊动作的定义 | 生成时开启强制对称 | can_symmetrize / special / relation | procedural_symmetry |
| 2 | 表情依赖 | 引用来源=困る；条件在模型归一化坐标及当前分区中计算，边界连续衰减；不参与强制对称 | 来源可生成且依赖无循环 | relation | expression_relations.Solver |
| 3 | 输入 | 按当前标记读取；已删除必要曲线所依赖的表情跳过 | 存在对应分区时执行 | recipe | procedural_rig.checkpoint |
| 4 | 眉毛目标 | 以同侧眉毛共同中心和眼宽计算位置，并叠加当前校正 | 存在对应分区时执行 | recipe | procedural_atoms.solve |
| 5 | 皮肤求解 | 固定眼口控制点，沿 Face 邻接平滑传播 | 存在对应分区时执行 | recipe | procedural_skin.EyelidSkin.deform |
| 6 | 防破面 | 保持轮廓约束，限制局部修正，残余冲突写入报告 | 存在对应分区时执行 | recipe | procedural_constraints.finalize_skin |
| 7 | 风格设置 | 下眼睑参与量在可行闭合范围中选择接合位置，不改变下眼睑 30% 上移及笑眼弧顶额外 10% 的硬上限。笑眼弧度与形态保持调整曲线偏好，闭合、接触和厚度优先。组合、曲线写回沿用生成时保存的风格设置 | 存在对应分区时执行 | recipe | procedural_ui.generation_options / procedural_binding.styled_closure |
| 8 | 闭眼层次 | 下睫毛随实际下眼眶的连续位移和旋转运动。闭眼时将整条下睫毛的上下缘收在上睫毛投影内，再求解前后层次。Face 接触后复查并修正遮盖，最终悬空和覆盖不足单独报告 | 存在对应分区时执行 | recipe | procedural_lashes.follow_lower_rim / cover_lower_band / finish_closed_order |
| 9 | 计算设备 | Windows NVIDIA CUDA 可用时，以双精度 GPU 内核求解三角面投影接触。小任务、缺少运行库、显存或调用失败时使用 CPU。两种设备共用几何规则、容差和可移动条件，报告设备、调用数与回退原因 | 存在对应分区时执行 | recipe | procedural_gpu.try_depth |
| 10 | 口腔 | 口内边界固定到实际唇缘，内部连续变形；强制镜像后重新贴合 Face 与 Mouth，避免两次表面插值产生小接缝 | 存在对应分区时执行 | recipe | procedural_cavity.deform |
| 11 | 牙齿 | 内置口型按 Original 张口时牙片的一致运动校准上下排，再按嘴宽适配各自位移与旋转，不重复叠加竖向随唇浮动。原参考静止的牙齿保持原位；目标有小间隙时，下牙整组上移至首次接触，最多嘴宽的 30%，缺少独立上下牙则跳过。未校准的自定义或下颌动作保留有界随唇处理。接触可先收回校准动作中的前移，再按牙弓与嘴宽的较大值取 6.5% 额度整排后移，保留牙弓及上下行程；未校准动作仍采用 2.5% 共同后移及 4% 局部后移。检查局部修正是否引入新的三角面翻折；额度不足记录穿插，不向外推 Face，不缩放牙弓，不改变 Basis | 存在对应分区时执行 | recipe | procedural_constraints.close_dental_contact / procedural_contacts.oral_face |
| 12 | 口内接触 | 按唇缘相连拓扑选择 Face 接触面，包含斜面及内翻唇面；牙齿及口腔退回面部内侧，口腔唇缘固定。取消舌头随整排牙齿最前点后退；牙齿与舌头的接触只由实际三角面交叉触发。舌头上表面避开下口腔，Basis 同样检查；接触位移上限取舌长 12% 和口宽 8% 的较小值，同次修正反复检查共用额度；超出额度报告冲突 | 存在对应分区时执行 | recipe | procedural_contacts.finish / tongue_teeth / tongue_side |
| 13 | 写入 | 表情形态键、口腔联动和最终变形曲线一起保存 | 存在对应分区时执行 | recipe | procedural_generate.generate |
| 14 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.brows | procedural_atoms.merge |

数值定义：JSON 中 `expressions` 的同名项。

## にこり左

| 顺序 | 阶段 | 计算准则 | 条件 | 数值路径 | 实现 |
| --- | --- | --- | --- | --- | --- |
| 1 | 对称策略 | 不对该表情强制镜像；保留子表情、组合或特殊动作的定义 | 生成时开启强制对称 | can_symmetrize / special / relation | procedural_symmetry |
| 2 | 表情依赖 | 引用来源=にこり；条件在模型归一化坐标及当前分区中计算，边界连续衰减；不参与强制对称 | 来源可生成且依赖无循环 | relation | expression_relations.Solver |
| 3 | 输入 | 按当前标记读取；已删除必要曲线所依赖的表情跳过 | 存在对应分区时执行 | recipe | procedural_rig.checkpoint |
| 4 | 眉毛目标 | 以同侧眉毛共同中心和眼宽计算位置，并叠加当前校正 | 存在对应分区时执行 | recipe | procedural_atoms.solve |
| 5 | 皮肤求解 | 固定眼口控制点，沿 Face 邻接平滑传播 | 存在对应分区时执行 | recipe | procedural_skin.EyelidSkin.deform |
| 6 | 防破面 | 保持轮廓约束，限制局部修正，残余冲突写入报告 | 存在对应分区时执行 | recipe | procedural_constraints.finalize_skin |
| 7 | 风格设置 | 下眼睑参与量在可行闭合范围中选择接合位置，不改变下眼睑 30% 上移及笑眼弧顶额外 10% 的硬上限。笑眼弧度与形态保持调整曲线偏好，闭合、接触和厚度优先。组合、曲线写回沿用生成时保存的风格设置 | 存在对应分区时执行 | recipe | procedural_ui.generation_options / procedural_binding.styled_closure |
| 8 | 闭眼层次 | 下睫毛随实际下眼眶的连续位移和旋转运动。闭眼时将整条下睫毛的上下缘收在上睫毛投影内，再求解前后层次。Face 接触后复查并修正遮盖，最终悬空和覆盖不足单独报告 | 存在对应分区时执行 | recipe | procedural_lashes.follow_lower_rim / cover_lower_band / finish_closed_order |
| 9 | 计算设备 | Windows NVIDIA CUDA 可用时，以双精度 GPU 内核求解三角面投影接触。小任务、缺少运行库、显存或调用失败时使用 CPU。两种设备共用几何规则、容差和可移动条件，报告设备、调用数与回退原因 | 存在对应分区时执行 | recipe | procedural_gpu.try_depth |
| 10 | 口腔 | 口内边界固定到实际唇缘，内部连续变形；强制镜像后重新贴合 Face 与 Mouth，避免两次表面插值产生小接缝 | 存在对应分区时执行 | recipe | procedural_cavity.deform |
| 11 | 牙齿 | 内置口型按 Original 张口时牙片的一致运动校准上下排，再按嘴宽适配各自位移与旋转，不重复叠加竖向随唇浮动。原参考静止的牙齿保持原位；目标有小间隙时，下牙整组上移至首次接触，最多嘴宽的 30%，缺少独立上下牙则跳过。未校准的自定义或下颌动作保留有界随唇处理。接触可先收回校准动作中的前移，再按牙弓与嘴宽的较大值取 6.5% 额度整排后移，保留牙弓及上下行程；未校准动作仍采用 2.5% 共同后移及 4% 局部后移。检查局部修正是否引入新的三角面翻折；额度不足记录穿插，不向外推 Face，不缩放牙弓，不改变 Basis | 存在对应分区时执行 | recipe | procedural_constraints.close_dental_contact / procedural_contacts.oral_face |
| 12 | 口内接触 | 按唇缘相连拓扑选择 Face 接触面，包含斜面及内翻唇面；牙齿及口腔退回面部内侧，口腔唇缘固定。取消舌头随整排牙齿最前点后退；牙齿与舌头的接触只由实际三角面交叉触发。舌头上表面避开下口腔，Basis 同样检查；接触位移上限取舌长 12% 和口宽 8% 的较小值，同次修正反复检查共用额度；超出额度报告冲突 | 存在对应分区时执行 | recipe | procedural_contacts.finish / tongue_teeth / tongue_side |
| 13 | 写入 | 表情形态键、口腔联动和最终变形曲线一起保存 | 存在对应分区时执行 | recipe | procedural_generate.generate |
| 14 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.brows | procedural_atoms.merge |

数值定义：JSON 中 `expressions` 的同名项。

## にこり右

| 顺序 | 阶段 | 计算准则 | 条件 | 数值路径 | 实现 |
| --- | --- | --- | --- | --- | --- |
| 1 | 对称策略 | 不对该表情强制镜像；保留子表情、组合或特殊动作的定义 | 生成时开启强制对称 | can_symmetrize / special / relation | procedural_symmetry |
| 2 | 表情依赖 | 引用来源=にこり；条件在模型归一化坐标及当前分区中计算，边界连续衰减；不参与强制对称 | 来源可生成且依赖无循环 | relation | expression_relations.Solver |
| 3 | 输入 | 按当前标记读取；已删除必要曲线所依赖的表情跳过 | 存在对应分区时执行 | recipe | procedural_rig.checkpoint |
| 4 | 眉毛目标 | 以同侧眉毛共同中心和眼宽计算位置，并叠加当前校正 | 存在对应分区时执行 | recipe | procedural_atoms.solve |
| 5 | 皮肤求解 | 固定眼口控制点，沿 Face 邻接平滑传播 | 存在对应分区时执行 | recipe | procedural_skin.EyelidSkin.deform |
| 6 | 防破面 | 保持轮廓约束，限制局部修正，残余冲突写入报告 | 存在对应分区时执行 | recipe | procedural_constraints.finalize_skin |
| 7 | 风格设置 | 下眼睑参与量在可行闭合范围中选择接合位置，不改变下眼睑 30% 上移及笑眼弧顶额外 10% 的硬上限。笑眼弧度与形态保持调整曲线偏好，闭合、接触和厚度优先。组合、曲线写回沿用生成时保存的风格设置 | 存在对应分区时执行 | recipe | procedural_ui.generation_options / procedural_binding.styled_closure |
| 8 | 闭眼层次 | 下睫毛随实际下眼眶的连续位移和旋转运动。闭眼时将整条下睫毛的上下缘收在上睫毛投影内，再求解前后层次。Face 接触后复查并修正遮盖，最终悬空和覆盖不足单独报告 | 存在对应分区时执行 | recipe | procedural_lashes.follow_lower_rim / cover_lower_band / finish_closed_order |
| 9 | 计算设备 | Windows NVIDIA CUDA 可用时，以双精度 GPU 内核求解三角面投影接触。小任务、缺少运行库、显存或调用失败时使用 CPU。两种设备共用几何规则、容差和可移动条件，报告设备、调用数与回退原因 | 存在对应分区时执行 | recipe | procedural_gpu.try_depth |
| 10 | 口腔 | 口内边界固定到实际唇缘，内部连续变形；强制镜像后重新贴合 Face 与 Mouth，避免两次表面插值产生小接缝 | 存在对应分区时执行 | recipe | procedural_cavity.deform |
| 11 | 牙齿 | 内置口型按 Original 张口时牙片的一致运动校准上下排，再按嘴宽适配各自位移与旋转，不重复叠加竖向随唇浮动。原参考静止的牙齿保持原位；目标有小间隙时，下牙整组上移至首次接触，最多嘴宽的 30%，缺少独立上下牙则跳过。未校准的自定义或下颌动作保留有界随唇处理。接触可先收回校准动作中的前移，再按牙弓与嘴宽的较大值取 6.5% 额度整排后移，保留牙弓及上下行程；未校准动作仍采用 2.5% 共同后移及 4% 局部后移。检查局部修正是否引入新的三角面翻折；额度不足记录穿插，不向外推 Face，不缩放牙弓，不改变 Basis | 存在对应分区时执行 | recipe | procedural_constraints.close_dental_contact / procedural_contacts.oral_face |
| 12 | 口内接触 | 按唇缘相连拓扑选择 Face 接触面，包含斜面及内翻唇面；牙齿及口腔退回面部内侧，口腔唇缘固定。取消舌头随整排牙齿最前点后退；牙齿与舌头的接触只由实际三角面交叉触发。舌头上表面避开下口腔，Basis 同样检查；接触位移上限取舌长 12% 和口宽 8% 的较小值，同次修正反复检查共用额度；超出额度报告冲突 | 存在对应分区时执行 | recipe | procedural_contacts.finish / tongue_teeth / tongue_side |
| 13 | 写入 | 表情形态键、口腔联动和最终变形曲线一起保存 | 存在对应分区时执行 | recipe | procedural_generate.generate |
| 14 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.brows | procedural_atoms.merge |

数值定义：JSON 中 `expressions` 的同名项。

## 怒り左

| 顺序 | 阶段 | 计算准则 | 条件 | 数值路径 | 实现 |
| --- | --- | --- | --- | --- | --- |
| 1 | 对称策略 | 不对该表情强制镜像；保留子表情、组合或特殊动作的定义 | 生成时开启强制对称 | can_symmetrize / special / relation | procedural_symmetry |
| 2 | 表情依赖 | 引用来源=怒り；条件在模型归一化坐标及当前分区中计算，边界连续衰减；不参与强制对称 | 来源可生成且依赖无循环 | relation | expression_relations.Solver |
| 3 | 输入 | 按当前标记读取；已删除必要曲线所依赖的表情跳过 | 存在对应分区时执行 | recipe | procedural_rig.checkpoint |
| 4 | 眉毛目标 | 以同侧眉毛共同中心和眼宽计算位置，并叠加当前校正 | 存在对应分区时执行 | recipe | procedural_atoms.solve |
| 5 | 皮肤求解 | 固定眼口控制点，沿 Face 邻接平滑传播 | 存在对应分区时执行 | recipe | procedural_skin.EyelidSkin.deform |
| 6 | 防破面 | 保持轮廓约束，限制局部修正，残余冲突写入报告 | 存在对应分区时执行 | recipe | procedural_constraints.finalize_skin |
| 7 | 风格设置 | 下眼睑参与量在可行闭合范围中选择接合位置，不改变下眼睑 30% 上移及笑眼弧顶额外 10% 的硬上限。笑眼弧度与形态保持调整曲线偏好，闭合、接触和厚度优先。组合、曲线写回沿用生成时保存的风格设置 | 存在对应分区时执行 | recipe | procedural_ui.generation_options / procedural_binding.styled_closure |
| 8 | 闭眼层次 | 下睫毛随实际下眼眶的连续位移和旋转运动。闭眼时将整条下睫毛的上下缘收在上睫毛投影内，再求解前后层次。Face 接触后复查并修正遮盖，最终悬空和覆盖不足单独报告 | 存在对应分区时执行 | recipe | procedural_lashes.follow_lower_rim / cover_lower_band / finish_closed_order |
| 9 | 计算设备 | Windows NVIDIA CUDA 可用时，以双精度 GPU 内核求解三角面投影接触。小任务、缺少运行库、显存或调用失败时使用 CPU。两种设备共用几何规则、容差和可移动条件，报告设备、调用数与回退原因 | 存在对应分区时执行 | recipe | procedural_gpu.try_depth |
| 10 | 口腔 | 口内边界固定到实际唇缘，内部连续变形；强制镜像后重新贴合 Face 与 Mouth，避免两次表面插值产生小接缝 | 存在对应分区时执行 | recipe | procedural_cavity.deform |
| 11 | 牙齿 | 内置口型按 Original 张口时牙片的一致运动校准上下排，再按嘴宽适配各自位移与旋转，不重复叠加竖向随唇浮动。原参考静止的牙齿保持原位；目标有小间隙时，下牙整组上移至首次接触，最多嘴宽的 30%，缺少独立上下牙则跳过。未校准的自定义或下颌动作保留有界随唇处理。接触可先收回校准动作中的前移，再按牙弓与嘴宽的较大值取 6.5% 额度整排后移，保留牙弓及上下行程；未校准动作仍采用 2.5% 共同后移及 4% 局部后移。检查局部修正是否引入新的三角面翻折；额度不足记录穿插，不向外推 Face，不缩放牙弓，不改变 Basis | 存在对应分区时执行 | recipe | procedural_constraints.close_dental_contact / procedural_contacts.oral_face |
| 12 | 口内接触 | 按唇缘相连拓扑选择 Face 接触面，包含斜面及内翻唇面；牙齿及口腔退回面部内侧，口腔唇缘固定。取消舌头随整排牙齿最前点后退；牙齿与舌头的接触只由实际三角面交叉触发。舌头上表面避开下口腔，Basis 同样检查；接触位移上限取舌长 12% 和口宽 8% 的较小值，同次修正反复检查共用额度；超出额度报告冲突 | 存在对应分区时执行 | recipe | procedural_contacts.finish / tongue_teeth / tongue_side |
| 13 | 写入 | 表情形态键、口腔联动和最终变形曲线一起保存 | 存在对应分区时执行 | recipe | procedural_generate.generate |
| 14 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.brows | procedural_atoms.merge |

数值定义：JSON 中 `expressions` 的同名项。

## 怒り右

| 顺序 | 阶段 | 计算准则 | 条件 | 数值路径 | 实现 |
| --- | --- | --- | --- | --- | --- |
| 1 | 对称策略 | 不对该表情强制镜像；保留子表情、组合或特殊动作的定义 | 生成时开启强制对称 | can_symmetrize / special / relation | procedural_symmetry |
| 2 | 表情依赖 | 引用来源=怒り；条件在模型归一化坐标及当前分区中计算，边界连续衰减；不参与强制对称 | 来源可生成且依赖无循环 | relation | expression_relations.Solver |
| 3 | 输入 | 按当前标记读取；已删除必要曲线所依赖的表情跳过 | 存在对应分区时执行 | recipe | procedural_rig.checkpoint |
| 4 | 眉毛目标 | 以同侧眉毛共同中心和眼宽计算位置，并叠加当前校正 | 存在对应分区时执行 | recipe | procedural_atoms.solve |
| 5 | 皮肤求解 | 固定眼口控制点，沿 Face 邻接平滑传播 | 存在对应分区时执行 | recipe | procedural_skin.EyelidSkin.deform |
| 6 | 防破面 | 保持轮廓约束，限制局部修正，残余冲突写入报告 | 存在对应分区时执行 | recipe | procedural_constraints.finalize_skin |
| 7 | 风格设置 | 下眼睑参与量在可行闭合范围中选择接合位置，不改变下眼睑 30% 上移及笑眼弧顶额外 10% 的硬上限。笑眼弧度与形态保持调整曲线偏好，闭合、接触和厚度优先。组合、曲线写回沿用生成时保存的风格设置 | 存在对应分区时执行 | recipe | procedural_ui.generation_options / procedural_binding.styled_closure |
| 8 | 闭眼层次 | 下睫毛随实际下眼眶的连续位移和旋转运动。闭眼时将整条下睫毛的上下缘收在上睫毛投影内，再求解前后层次。Face 接触后复查并修正遮盖，最终悬空和覆盖不足单独报告 | 存在对应分区时执行 | recipe | procedural_lashes.follow_lower_rim / cover_lower_band / finish_closed_order |
| 9 | 计算设备 | Windows NVIDIA CUDA 可用时，以双精度 GPU 内核求解三角面投影接触。小任务、缺少运行库、显存或调用失败时使用 CPU。两种设备共用几何规则、容差和可移动条件，报告设备、调用数与回退原因 | 存在对应分区时执行 | recipe | procedural_gpu.try_depth |
| 10 | 口腔 | 口内边界固定到实际唇缘，内部连续变形；强制镜像后重新贴合 Face 与 Mouth，避免两次表面插值产生小接缝 | 存在对应分区时执行 | recipe | procedural_cavity.deform |
| 11 | 牙齿 | 内置口型按 Original 张口时牙片的一致运动校准上下排，再按嘴宽适配各自位移与旋转，不重复叠加竖向随唇浮动。原参考静止的牙齿保持原位；目标有小间隙时，下牙整组上移至首次接触，最多嘴宽的 30%，缺少独立上下牙则跳过。未校准的自定义或下颌动作保留有界随唇处理。接触可先收回校准动作中的前移，再按牙弓与嘴宽的较大值取 6.5% 额度整排后移，保留牙弓及上下行程；未校准动作仍采用 2.5% 共同后移及 4% 局部后移。检查局部修正是否引入新的三角面翻折；额度不足记录穿插，不向外推 Face，不缩放牙弓，不改变 Basis | 存在对应分区时执行 | recipe | procedural_constraints.close_dental_contact / procedural_contacts.oral_face |
| 12 | 口内接触 | 按唇缘相连拓扑选择 Face 接触面，包含斜面及内翻唇面；牙齿及口腔退回面部内侧，口腔唇缘固定。取消舌头随整排牙齿最前点后退；牙齿与舌头的接触只由实际三角面交叉触发。舌头上表面避开下口腔，Basis 同样检查；接触位移上限取舌长 12% 和口宽 8% 的较小值，同次修正反复检查共用额度；超出额度报告冲突 | 存在对应分区时执行 | recipe | procedural_contacts.finish / tongue_teeth / tongue_side |
| 13 | 写入 | 表情形态键、口腔联动和最终变形曲线一起保存 | 存在对应分区时执行 | recipe | procedural_generate.generate |
| 14 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.brows | procedural_atoms.merge |

数值定义：JSON 中 `expressions` 的同名项。

## 恥ずかしい左

| 顺序 | 阶段 | 计算准则 | 条件 | 数值路径 | 实现 |
| --- | --- | --- | --- | --- | --- |
| 1 | 对称策略 | 不对该表情强制镜像；保留子表情、组合或特殊动作的定义 | 生成时开启强制对称 | can_symmetrize / special / relation | procedural_symmetry |
| 2 | 表情依赖 | 引用来源=恥ずかしい；条件在模型归一化坐标及当前分区中计算，边界连续衰减；不参与强制对称 | 来源可生成且依赖无循环 | relation | expression_relations.Solver |
| 3 | 输入 | 按当前标记读取；已删除必要曲线所依赖的表情跳过 | 存在对应分区时执行 | recipe | procedural_rig.checkpoint |
| 4 | 眉毛目标 | 以同侧眉毛共同中心和眼宽计算位置，并叠加当前校正 | 存在对应分区时执行 | recipe | procedural_atoms.solve |
| 5 | 皮肤求解 | 固定眼口控制点，沿 Face 邻接平滑传播 | 存在对应分区时执行 | recipe | procedural_skin.EyelidSkin.deform |
| 6 | 防破面 | 保持轮廓约束，限制局部修正，残余冲突写入报告 | 存在对应分区时执行 | recipe | procedural_constraints.finalize_skin |
| 7 | 风格设置 | 下眼睑参与量在可行闭合范围中选择接合位置，不改变下眼睑 30% 上移及笑眼弧顶额外 10% 的硬上限。笑眼弧度与形态保持调整曲线偏好，闭合、接触和厚度优先。组合、曲线写回沿用生成时保存的风格设置 | 存在对应分区时执行 | recipe | procedural_ui.generation_options / procedural_binding.styled_closure |
| 8 | 闭眼层次 | 下睫毛随实际下眼眶的连续位移和旋转运动。闭眼时将整条下睫毛的上下缘收在上睫毛投影内，再求解前后层次。Face 接触后复查并修正遮盖，最终悬空和覆盖不足单独报告 | 存在对应分区时执行 | recipe | procedural_lashes.follow_lower_rim / cover_lower_band / finish_closed_order |
| 9 | 计算设备 | Windows NVIDIA CUDA 可用时，以双精度 GPU 内核求解三角面投影接触。小任务、缺少运行库、显存或调用失败时使用 CPU。两种设备共用几何规则、容差和可移动条件，报告设备、调用数与回退原因 | 存在对应分区时执行 | recipe | procedural_gpu.try_depth |
| 10 | 口腔 | 口内边界固定到实际唇缘，内部连续变形；强制镜像后重新贴合 Face 与 Mouth，避免两次表面插值产生小接缝 | 存在对应分区时执行 | recipe | procedural_cavity.deform |
| 11 | 牙齿 | 内置口型按 Original 张口时牙片的一致运动校准上下排，再按嘴宽适配各自位移与旋转，不重复叠加竖向随唇浮动。原参考静止的牙齿保持原位；目标有小间隙时，下牙整组上移至首次接触，最多嘴宽的 30%，缺少独立上下牙则跳过。未校准的自定义或下颌动作保留有界随唇处理。接触可先收回校准动作中的前移，再按牙弓与嘴宽的较大值取 6.5% 额度整排后移，保留牙弓及上下行程；未校准动作仍采用 2.5% 共同后移及 4% 局部后移。检查局部修正是否引入新的三角面翻折；额度不足记录穿插，不向外推 Face，不缩放牙弓，不改变 Basis | 存在对应分区时执行 | recipe | procedural_constraints.close_dental_contact / procedural_contacts.oral_face |
| 12 | 口内接触 | 按唇缘相连拓扑选择 Face 接触面，包含斜面及内翻唇面；牙齿及口腔退回面部内侧，口腔唇缘固定。取消舌头随整排牙齿最前点后退；牙齿与舌头的接触只由实际三角面交叉触发。舌头上表面避开下口腔，Basis 同样检查；接触位移上限取舌长 12% 和口宽 8% 的较小值，同次修正反复检查共用额度；超出额度报告冲突 | 存在对应分区时执行 | recipe | procedural_contacts.finish / tongue_teeth / tongue_side |
| 13 | 写入 | 表情形态键、口腔联动和最终变形曲线一起保存 | 存在对应分区时执行 | recipe | procedural_generate.generate |
| 14 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.brows | procedural_atoms.merge |

数值定义：JSON 中 `expressions` 的同名项。

## 恥ずかしい右

| 顺序 | 阶段 | 计算准则 | 条件 | 数值路径 | 实现 |
| --- | --- | --- | --- | --- | --- |
| 1 | 对称策略 | 不对该表情强制镜像；保留子表情、组合或特殊动作的定义 | 生成时开启强制对称 | can_symmetrize / special / relation | procedural_symmetry |
| 2 | 表情依赖 | 引用来源=恥ずかしい；条件在模型归一化坐标及当前分区中计算，边界连续衰减；不参与强制对称 | 来源可生成且依赖无循环 | relation | expression_relations.Solver |
| 3 | 输入 | 按当前标记读取；已删除必要曲线所依赖的表情跳过 | 存在对应分区时执行 | recipe | procedural_rig.checkpoint |
| 4 | 眉毛目标 | 以同侧眉毛共同中心和眼宽计算位置，并叠加当前校正 | 存在对应分区时执行 | recipe | procedural_atoms.solve |
| 5 | 皮肤求解 | 固定眼口控制点，沿 Face 邻接平滑传播 | 存在对应分区时执行 | recipe | procedural_skin.EyelidSkin.deform |
| 6 | 防破面 | 保持轮廓约束，限制局部修正，残余冲突写入报告 | 存在对应分区时执行 | recipe | procedural_constraints.finalize_skin |
| 7 | 风格设置 | 下眼睑参与量在可行闭合范围中选择接合位置，不改变下眼睑 30% 上移及笑眼弧顶额外 10% 的硬上限。笑眼弧度与形态保持调整曲线偏好，闭合、接触和厚度优先。组合、曲线写回沿用生成时保存的风格设置 | 存在对应分区时执行 | recipe | procedural_ui.generation_options / procedural_binding.styled_closure |
| 8 | 闭眼层次 | 下睫毛随实际下眼眶的连续位移和旋转运动。闭眼时将整条下睫毛的上下缘收在上睫毛投影内，再求解前后层次。Face 接触后复查并修正遮盖，最终悬空和覆盖不足单独报告 | 存在对应分区时执行 | recipe | procedural_lashes.follow_lower_rim / cover_lower_band / finish_closed_order |
| 9 | 计算设备 | Windows NVIDIA CUDA 可用时，以双精度 GPU 内核求解三角面投影接触。小任务、缺少运行库、显存或调用失败时使用 CPU。两种设备共用几何规则、容差和可移动条件，报告设备、调用数与回退原因 | 存在对应分区时执行 | recipe | procedural_gpu.try_depth |
| 10 | 口腔 | 口内边界固定到实际唇缘，内部连续变形；强制镜像后重新贴合 Face 与 Mouth，避免两次表面插值产生小接缝 | 存在对应分区时执行 | recipe | procedural_cavity.deform |
| 11 | 牙齿 | 内置口型按 Original 张口时牙片的一致运动校准上下排，再按嘴宽适配各自位移与旋转，不重复叠加竖向随唇浮动。原参考静止的牙齿保持原位；目标有小间隙时，下牙整组上移至首次接触，最多嘴宽的 30%，缺少独立上下牙则跳过。未校准的自定义或下颌动作保留有界随唇处理。接触可先收回校准动作中的前移，再按牙弓与嘴宽的较大值取 6.5% 额度整排后移，保留牙弓及上下行程；未校准动作仍采用 2.5% 共同后移及 4% 局部后移。检查局部修正是否引入新的三角面翻折；额度不足记录穿插，不向外推 Face，不缩放牙弓，不改变 Basis | 存在对应分区时执行 | recipe | procedural_constraints.close_dental_contact / procedural_contacts.oral_face |
| 12 | 口内接触 | 按唇缘相连拓扑选择 Face 接触面，包含斜面及内翻唇面；牙齿及口腔退回面部内侧，口腔唇缘固定。取消舌头随整排牙齿最前点后退；牙齿与舌头的接触只由实际三角面交叉触发。舌头上表面避开下口腔，Basis 同样检查；接触位移上限取舌长 12% 和口宽 8% 的较小值，同次修正反复检查共用额度；超出额度报告冲突 | 存在对应分区时执行 | recipe | procedural_contacts.finish / tongue_teeth / tongue_side |
| 13 | 写入 | 表情形态键、口腔联动和最终变形曲线一起保存 | 存在对应分区时执行 | recipe | procedural_generate.generate |
| 14 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.brows | procedural_atoms.merge |

数值定义：JSON 中 `expressions` 的同名项。

## 上左

| 顺序 | 阶段 | 计算准则 | 条件 | 数值路径 | 实现 |
| --- | --- | --- | --- | --- | --- |
| 1 | 对称策略 | 不对该表情强制镜像；保留子表情、组合或特殊动作的定义 | 生成时开启强制对称 | can_symmetrize / special / relation | procedural_symmetry |
| 2 | 表情依赖 | 引用来源=上；条件在模型归一化坐标及当前分区中计算，边界连续衰减；不参与强制对称 | 来源可生成且依赖无循环 | relation | expression_relations.Solver |
| 3 | 输入 | 按当前标记读取；已删除必要曲线所依赖的表情跳过 | 存在对应分区时执行 | recipe | procedural_rig.checkpoint |
| 4 | 眉毛目标 | 以同侧眉毛共同中心和眼宽计算位置，并叠加当前校正 | 存在对应分区时执行 | recipe | procedural_atoms.solve |
| 5 | 皮肤求解 | 固定眼口控制点，沿 Face 邻接平滑传播 | 存在对应分区时执行 | recipe | procedural_skin.EyelidSkin.deform |
| 6 | 防破面 | 保持轮廓约束，限制局部修正，残余冲突写入报告 | 存在对应分区时执行 | recipe | procedural_constraints.finalize_skin |
| 7 | 风格设置 | 下眼睑参与量在可行闭合范围中选择接合位置，不改变下眼睑 30% 上移及笑眼弧顶额外 10% 的硬上限。笑眼弧度与形态保持调整曲线偏好，闭合、接触和厚度优先。组合、曲线写回沿用生成时保存的风格设置 | 存在对应分区时执行 | recipe | procedural_ui.generation_options / procedural_binding.styled_closure |
| 8 | 闭眼层次 | 下睫毛随实际下眼眶的连续位移和旋转运动。闭眼时将整条下睫毛的上下缘收在上睫毛投影内，再求解前后层次。Face 接触后复查并修正遮盖，最终悬空和覆盖不足单独报告 | 存在对应分区时执行 | recipe | procedural_lashes.follow_lower_rim / cover_lower_band / finish_closed_order |
| 9 | 计算设备 | Windows NVIDIA CUDA 可用时，以双精度 GPU 内核求解三角面投影接触。小任务、缺少运行库、显存或调用失败时使用 CPU。两种设备共用几何规则、容差和可移动条件，报告设备、调用数与回退原因 | 存在对应分区时执行 | recipe | procedural_gpu.try_depth |
| 10 | 口腔 | 口内边界固定到实际唇缘，内部连续变形；强制镜像后重新贴合 Face 与 Mouth，避免两次表面插值产生小接缝 | 存在对应分区时执行 | recipe | procedural_cavity.deform |
| 11 | 牙齿 | 内置口型按 Original 张口时牙片的一致运动校准上下排，再按嘴宽适配各自位移与旋转，不重复叠加竖向随唇浮动。原参考静止的牙齿保持原位；目标有小间隙时，下牙整组上移至首次接触，最多嘴宽的 30%，缺少独立上下牙则跳过。未校准的自定义或下颌动作保留有界随唇处理。接触可先收回校准动作中的前移，再按牙弓与嘴宽的较大值取 6.5% 额度整排后移，保留牙弓及上下行程；未校准动作仍采用 2.5% 共同后移及 4% 局部后移。检查局部修正是否引入新的三角面翻折；额度不足记录穿插，不向外推 Face，不缩放牙弓，不改变 Basis | 存在对应分区时执行 | recipe | procedural_constraints.close_dental_contact / procedural_contacts.oral_face |
| 12 | 口内接触 | 按唇缘相连拓扑选择 Face 接触面，包含斜面及内翻唇面；牙齿及口腔退回面部内侧，口腔唇缘固定。取消舌头随整排牙齿最前点后退；牙齿与舌头的接触只由实际三角面交叉触发。舌头上表面避开下口腔，Basis 同样检查；接触位移上限取舌长 12% 和口宽 8% 的较小值，同次修正反复检查共用额度；超出额度报告冲突 | 存在对应分区时执行 | recipe | procedural_contacts.finish / tongue_teeth / tongue_side |
| 13 | 写入 | 表情形态键、口腔联动和最终变形曲线一起保存 | 存在对应分区时执行 | recipe | procedural_generate.generate |
| 14 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.brows | procedural_atoms.merge |

数值定义：JSON 中 `expressions` 的同名项。

## 上右

| 顺序 | 阶段 | 计算准则 | 条件 | 数值路径 | 实现 |
| --- | --- | --- | --- | --- | --- |
| 1 | 对称策略 | 不对该表情强制镜像；保留子表情、组合或特殊动作的定义 | 生成时开启强制对称 | can_symmetrize / special / relation | procedural_symmetry |
| 2 | 表情依赖 | 引用来源=上；条件在模型归一化坐标及当前分区中计算，边界连续衰减；不参与强制对称 | 来源可生成且依赖无循环 | relation | expression_relations.Solver |
| 3 | 输入 | 按当前标记读取；已删除必要曲线所依赖的表情跳过 | 存在对应分区时执行 | recipe | procedural_rig.checkpoint |
| 4 | 眉毛目标 | 以同侧眉毛共同中心和眼宽计算位置，并叠加当前校正 | 存在对应分区时执行 | recipe | procedural_atoms.solve |
| 5 | 皮肤求解 | 固定眼口控制点，沿 Face 邻接平滑传播 | 存在对应分区时执行 | recipe | procedural_skin.EyelidSkin.deform |
| 6 | 防破面 | 保持轮廓约束，限制局部修正，残余冲突写入报告 | 存在对应分区时执行 | recipe | procedural_constraints.finalize_skin |
| 7 | 风格设置 | 下眼睑参与量在可行闭合范围中选择接合位置，不改变下眼睑 30% 上移及笑眼弧顶额外 10% 的硬上限。笑眼弧度与形态保持调整曲线偏好，闭合、接触和厚度优先。组合、曲线写回沿用生成时保存的风格设置 | 存在对应分区时执行 | recipe | procedural_ui.generation_options / procedural_binding.styled_closure |
| 8 | 闭眼层次 | 下睫毛随实际下眼眶的连续位移和旋转运动。闭眼时将整条下睫毛的上下缘收在上睫毛投影内，再求解前后层次。Face 接触后复查并修正遮盖，最终悬空和覆盖不足单独报告 | 存在对应分区时执行 | recipe | procedural_lashes.follow_lower_rim / cover_lower_band / finish_closed_order |
| 9 | 计算设备 | Windows NVIDIA CUDA 可用时，以双精度 GPU 内核求解三角面投影接触。小任务、缺少运行库、显存或调用失败时使用 CPU。两种设备共用几何规则、容差和可移动条件，报告设备、调用数与回退原因 | 存在对应分区时执行 | recipe | procedural_gpu.try_depth |
| 10 | 口腔 | 口内边界固定到实际唇缘，内部连续变形；强制镜像后重新贴合 Face 与 Mouth，避免两次表面插值产生小接缝 | 存在对应分区时执行 | recipe | procedural_cavity.deform |
| 11 | 牙齿 | 内置口型按 Original 张口时牙片的一致运动校准上下排，再按嘴宽适配各自位移与旋转，不重复叠加竖向随唇浮动。原参考静止的牙齿保持原位；目标有小间隙时，下牙整组上移至首次接触，最多嘴宽的 30%，缺少独立上下牙则跳过。未校准的自定义或下颌动作保留有界随唇处理。接触可先收回校准动作中的前移，再按牙弓与嘴宽的较大值取 6.5% 额度整排后移，保留牙弓及上下行程；未校准动作仍采用 2.5% 共同后移及 4% 局部后移。检查局部修正是否引入新的三角面翻折；额度不足记录穿插，不向外推 Face，不缩放牙弓，不改变 Basis | 存在对应分区时执行 | recipe | procedural_constraints.close_dental_contact / procedural_contacts.oral_face |
| 12 | 口内接触 | 按唇缘相连拓扑选择 Face 接触面，包含斜面及内翻唇面；牙齿及口腔退回面部内侧，口腔唇缘固定。取消舌头随整排牙齿最前点后退；牙齿与舌头的接触只由实际三角面交叉触发。舌头上表面避开下口腔，Basis 同样检查；接触位移上限取舌长 12% 和口宽 8% 的较小值，同次修正反复检查共用额度；超出额度报告冲突 | 存在对应分区时执行 | recipe | procedural_contacts.finish / tongue_teeth / tongue_side |
| 13 | 写入 | 表情形态键、口腔联动和最终变形曲线一起保存 | 存在对应分区时执行 | recipe | procedural_generate.generate |
| 14 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.brows | procedural_atoms.merge |

数值定义：JSON 中 `expressions` 的同名项。

## 下左

| 顺序 | 阶段 | 计算准则 | 条件 | 数值路径 | 实现 |
| --- | --- | --- | --- | --- | --- |
| 1 | 对称策略 | 不对该表情强制镜像；保留子表情、组合或特殊动作的定义 | 生成时开启强制对称 | can_symmetrize / special / relation | procedural_symmetry |
| 2 | 表情依赖 | 引用来源=下；条件在模型归一化坐标及当前分区中计算，边界连续衰减；不参与强制对称 | 来源可生成且依赖无循环 | relation | expression_relations.Solver |
| 3 | 输入 | 按当前标记读取；已删除必要曲线所依赖的表情跳过 | 存在对应分区时执行 | recipe | procedural_rig.checkpoint |
| 4 | 眉毛目标 | 以同侧眉毛共同中心和眼宽计算位置，并叠加当前校正 | 存在对应分区时执行 | recipe | procedural_atoms.solve |
| 5 | 皮肤求解 | 固定眼口控制点，沿 Face 邻接平滑传播 | 存在对应分区时执行 | recipe | procedural_skin.EyelidSkin.deform |
| 6 | 防破面 | 保持轮廓约束，限制局部修正，残余冲突写入报告 | 存在对应分区时执行 | recipe | procedural_constraints.finalize_skin |
| 7 | 风格设置 | 下眼睑参与量在可行闭合范围中选择接合位置，不改变下眼睑 30% 上移及笑眼弧顶额外 10% 的硬上限。笑眼弧度与形态保持调整曲线偏好，闭合、接触和厚度优先。组合、曲线写回沿用生成时保存的风格设置 | 存在对应分区时执行 | recipe | procedural_ui.generation_options / procedural_binding.styled_closure |
| 8 | 闭眼层次 | 下睫毛随实际下眼眶的连续位移和旋转运动。闭眼时将整条下睫毛的上下缘收在上睫毛投影内，再求解前后层次。Face 接触后复查并修正遮盖，最终悬空和覆盖不足单独报告 | 存在对应分区时执行 | recipe | procedural_lashes.follow_lower_rim / cover_lower_band / finish_closed_order |
| 9 | 计算设备 | Windows NVIDIA CUDA 可用时，以双精度 GPU 内核求解三角面投影接触。小任务、缺少运行库、显存或调用失败时使用 CPU。两种设备共用几何规则、容差和可移动条件，报告设备、调用数与回退原因 | 存在对应分区时执行 | recipe | procedural_gpu.try_depth |
| 10 | 口腔 | 口内边界固定到实际唇缘，内部连续变形；强制镜像后重新贴合 Face 与 Mouth，避免两次表面插值产生小接缝 | 存在对应分区时执行 | recipe | procedural_cavity.deform |
| 11 | 牙齿 | 内置口型按 Original 张口时牙片的一致运动校准上下排，再按嘴宽适配各自位移与旋转，不重复叠加竖向随唇浮动。原参考静止的牙齿保持原位；目标有小间隙时，下牙整组上移至首次接触，最多嘴宽的 30%，缺少独立上下牙则跳过。未校准的自定义或下颌动作保留有界随唇处理。接触可先收回校准动作中的前移，再按牙弓与嘴宽的较大值取 6.5% 额度整排后移，保留牙弓及上下行程；未校准动作仍采用 2.5% 共同后移及 4% 局部后移。检查局部修正是否引入新的三角面翻折；额度不足记录穿插，不向外推 Face，不缩放牙弓，不改变 Basis | 存在对应分区时执行 | recipe | procedural_constraints.close_dental_contact / procedural_contacts.oral_face |
| 12 | 口内接触 | 按唇缘相连拓扑选择 Face 接触面，包含斜面及内翻唇面；牙齿及口腔退回面部内侧，口腔唇缘固定。取消舌头随整排牙齿最前点后退；牙齿与舌头的接触只由实际三角面交叉触发。舌头上表面避开下口腔，Basis 同样检查；接触位移上限取舌长 12% 和口宽 8% 的较小值，同次修正反复检查共用额度；超出额度报告冲突 | 存在对应分区时执行 | recipe | procedural_contacts.finish / tongue_teeth / tongue_side |
| 13 | 写入 | 表情形态键、口腔联动和最终变形曲线一起保存 | 存在对应分区时执行 | recipe | procedural_generate.generate |
| 14 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.brows | procedural_atoms.merge |

数值定义：JSON 中 `expressions` 的同名项。

## 下右

| 顺序 | 阶段 | 计算准则 | 条件 | 数值路径 | 实现 |
| --- | --- | --- | --- | --- | --- |
| 1 | 对称策略 | 不对该表情强制镜像；保留子表情、组合或特殊动作的定义 | 生成时开启强制对称 | can_symmetrize / special / relation | procedural_symmetry |
| 2 | 表情依赖 | 引用来源=下；条件在模型归一化坐标及当前分区中计算，边界连续衰减；不参与强制对称 | 来源可生成且依赖无循环 | relation | expression_relations.Solver |
| 3 | 输入 | 按当前标记读取；已删除必要曲线所依赖的表情跳过 | 存在对应分区时执行 | recipe | procedural_rig.checkpoint |
| 4 | 眉毛目标 | 以同侧眉毛共同中心和眼宽计算位置，并叠加当前校正 | 存在对应分区时执行 | recipe | procedural_atoms.solve |
| 5 | 皮肤求解 | 固定眼口控制点，沿 Face 邻接平滑传播 | 存在对应分区时执行 | recipe | procedural_skin.EyelidSkin.deform |
| 6 | 防破面 | 保持轮廓约束，限制局部修正，残余冲突写入报告 | 存在对应分区时执行 | recipe | procedural_constraints.finalize_skin |
| 7 | 风格设置 | 下眼睑参与量在可行闭合范围中选择接合位置，不改变下眼睑 30% 上移及笑眼弧顶额外 10% 的硬上限。笑眼弧度与形态保持调整曲线偏好，闭合、接触和厚度优先。组合、曲线写回沿用生成时保存的风格设置 | 存在对应分区时执行 | recipe | procedural_ui.generation_options / procedural_binding.styled_closure |
| 8 | 闭眼层次 | 下睫毛随实际下眼眶的连续位移和旋转运动。闭眼时将整条下睫毛的上下缘收在上睫毛投影内，再求解前后层次。Face 接触后复查并修正遮盖，最终悬空和覆盖不足单独报告 | 存在对应分区时执行 | recipe | procedural_lashes.follow_lower_rim / cover_lower_band / finish_closed_order |
| 9 | 计算设备 | Windows NVIDIA CUDA 可用时，以双精度 GPU 内核求解三角面投影接触。小任务、缺少运行库、显存或调用失败时使用 CPU。两种设备共用几何规则、容差和可移动条件，报告设备、调用数与回退原因 | 存在对应分区时执行 | recipe | procedural_gpu.try_depth |
| 10 | 口腔 | 口内边界固定到实际唇缘，内部连续变形；强制镜像后重新贴合 Face 与 Mouth，避免两次表面插值产生小接缝 | 存在对应分区时执行 | recipe | procedural_cavity.deform |
| 11 | 牙齿 | 内置口型按 Original 张口时牙片的一致运动校准上下排，再按嘴宽适配各自位移与旋转，不重复叠加竖向随唇浮动。原参考静止的牙齿保持原位；目标有小间隙时，下牙整组上移至首次接触，最多嘴宽的 30%，缺少独立上下牙则跳过。未校准的自定义或下颌动作保留有界随唇处理。接触可先收回校准动作中的前移，再按牙弓与嘴宽的较大值取 6.5% 额度整排后移，保留牙弓及上下行程；未校准动作仍采用 2.5% 共同后移及 4% 局部后移。检查局部修正是否引入新的三角面翻折；额度不足记录穿插，不向外推 Face，不缩放牙弓，不改变 Basis | 存在对应分区时执行 | recipe | procedural_constraints.close_dental_contact / procedural_contacts.oral_face |
| 12 | 口内接触 | 按唇缘相连拓扑选择 Face 接触面，包含斜面及内翻唇面；牙齿及口腔退回面部内侧，口腔唇缘固定。取消舌头随整排牙齿最前点后退；牙齿与舌头的接触只由实际三角面交叉触发。舌头上表面避开下口腔，Basis 同样检查；接触位移上限取舌长 12% 和口宽 8% 的较小值，同次修正反复检查共用额度；超出额度报告冲突 | 存在对应分区时执行 | recipe | procedural_contacts.finish / tongue_teeth / tongue_side |
| 13 | 写入 | 表情形态键、口腔联动和最终变形曲线一起保存 | 存在对应分区时执行 | recipe | procedural_generate.generate |
| 14 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.brows | procedural_atoms.merge |

数值定义：JSON 中 `expressions` 的同名项。

## 前左

| 顺序 | 阶段 | 计算准则 | 条件 | 数值路径 | 实现 |
| --- | --- | --- | --- | --- | --- |
| 1 | 对称策略 | 不对该表情强制镜像；保留子表情、组合或特殊动作的定义 | 生成时开启强制对称 | can_symmetrize / special / relation | procedural_symmetry |
| 2 | 表情依赖 | 引用来源=前；条件在模型归一化坐标及当前分区中计算，边界连续衰减；不参与强制对称 | 来源可生成且依赖无循环 | relation | expression_relations.Solver |
| 3 | 输入 | 按当前标记读取；已删除必要曲线所依赖的表情跳过 | 存在对应分区时执行 | recipe | procedural_rig.checkpoint |
| 4 | 眉毛目标 | 以同侧眉毛共同中心和眼宽计算位置，并叠加当前校正 | 存在对应分区时执行 | recipe | procedural_atoms.solve |
| 5 | 皮肤求解 | 固定眼口控制点，沿 Face 邻接平滑传播 | 存在对应分区时执行 | recipe | procedural_skin.EyelidSkin.deform |
| 6 | 防破面 | 保持轮廓约束，限制局部修正，残余冲突写入报告 | 存在对应分区时执行 | recipe | procedural_constraints.finalize_skin |
| 7 | 风格设置 | 下眼睑参与量在可行闭合范围中选择接合位置，不改变下眼睑 30% 上移及笑眼弧顶额外 10% 的硬上限。笑眼弧度与形态保持调整曲线偏好，闭合、接触和厚度优先。组合、曲线写回沿用生成时保存的风格设置 | 存在对应分区时执行 | recipe | procedural_ui.generation_options / procedural_binding.styled_closure |
| 8 | 闭眼层次 | 下睫毛随实际下眼眶的连续位移和旋转运动。闭眼时将整条下睫毛的上下缘收在上睫毛投影内，再求解前后层次。Face 接触后复查并修正遮盖，最终悬空和覆盖不足单独报告 | 存在对应分区时执行 | recipe | procedural_lashes.follow_lower_rim / cover_lower_band / finish_closed_order |
| 9 | 计算设备 | Windows NVIDIA CUDA 可用时，以双精度 GPU 内核求解三角面投影接触。小任务、缺少运行库、显存或调用失败时使用 CPU。两种设备共用几何规则、容差和可移动条件，报告设备、调用数与回退原因 | 存在对应分区时执行 | recipe | procedural_gpu.try_depth |
| 10 | 口腔 | 口内边界固定到实际唇缘，内部连续变形；强制镜像后重新贴合 Face 与 Mouth，避免两次表面插值产生小接缝 | 存在对应分区时执行 | recipe | procedural_cavity.deform |
| 11 | 牙齿 | 内置口型按 Original 张口时牙片的一致运动校准上下排，再按嘴宽适配各自位移与旋转，不重复叠加竖向随唇浮动。原参考静止的牙齿保持原位；目标有小间隙时，下牙整组上移至首次接触，最多嘴宽的 30%，缺少独立上下牙则跳过。未校准的自定义或下颌动作保留有界随唇处理。接触可先收回校准动作中的前移，再按牙弓与嘴宽的较大值取 6.5% 额度整排后移，保留牙弓及上下行程；未校准动作仍采用 2.5% 共同后移及 4% 局部后移。检查局部修正是否引入新的三角面翻折；额度不足记录穿插，不向外推 Face，不缩放牙弓，不改变 Basis | 存在对应分区时执行 | recipe | procedural_constraints.close_dental_contact / procedural_contacts.oral_face |
| 12 | 口内接触 | 按唇缘相连拓扑选择 Face 接触面，包含斜面及内翻唇面；牙齿及口腔退回面部内侧，口腔唇缘固定。取消舌头随整排牙齿最前点后退；牙齿与舌头的接触只由实际三角面交叉触发。舌头上表面避开下口腔，Basis 同样检查；接触位移上限取舌长 12% 和口宽 8% 的较小值，同次修正反复检查共用额度；超出额度报告冲突 | 存在对应分区时执行 | recipe | procedural_contacts.finish / tongue_teeth / tongue_side |
| 13 | 写入 | 表情形态键、口腔联动和最终变形曲线一起保存 | 存在对应分区时执行 | recipe | procedural_generate.generate |
| 14 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.brows | procedural_atoms.merge |

数值定义：JSON 中 `expressions` 的同名项。

## 前右

| 顺序 | 阶段 | 计算准则 | 条件 | 数值路径 | 实现 |
| --- | --- | --- | --- | --- | --- |
| 1 | 对称策略 | 不对该表情强制镜像；保留子表情、组合或特殊动作的定义 | 生成时开启强制对称 | can_symmetrize / special / relation | procedural_symmetry |
| 2 | 表情依赖 | 引用来源=前；条件在模型归一化坐标及当前分区中计算，边界连续衰减；不参与强制对称 | 来源可生成且依赖无循环 | relation | expression_relations.Solver |
| 3 | 输入 | 按当前标记读取；已删除必要曲线所依赖的表情跳过 | 存在对应分区时执行 | recipe | procedural_rig.checkpoint |
| 4 | 眉毛目标 | 以同侧眉毛共同中心和眼宽计算位置，并叠加当前校正 | 存在对应分区时执行 | recipe | procedural_atoms.solve |
| 5 | 皮肤求解 | 固定眼口控制点，沿 Face 邻接平滑传播 | 存在对应分区时执行 | recipe | procedural_skin.EyelidSkin.deform |
| 6 | 防破面 | 保持轮廓约束，限制局部修正，残余冲突写入报告 | 存在对应分区时执行 | recipe | procedural_constraints.finalize_skin |
| 7 | 风格设置 | 下眼睑参与量在可行闭合范围中选择接合位置，不改变下眼睑 30% 上移及笑眼弧顶额外 10% 的硬上限。笑眼弧度与形态保持调整曲线偏好，闭合、接触和厚度优先。组合、曲线写回沿用生成时保存的风格设置 | 存在对应分区时执行 | recipe | procedural_ui.generation_options / procedural_binding.styled_closure |
| 8 | 闭眼层次 | 下睫毛随实际下眼眶的连续位移和旋转运动。闭眼时将整条下睫毛的上下缘收在上睫毛投影内，再求解前后层次。Face 接触后复查并修正遮盖，最终悬空和覆盖不足单独报告 | 存在对应分区时执行 | recipe | procedural_lashes.follow_lower_rim / cover_lower_band / finish_closed_order |
| 9 | 计算设备 | Windows NVIDIA CUDA 可用时，以双精度 GPU 内核求解三角面投影接触。小任务、缺少运行库、显存或调用失败时使用 CPU。两种设备共用几何规则、容差和可移动条件，报告设备、调用数与回退原因 | 存在对应分区时执行 | recipe | procedural_gpu.try_depth |
| 10 | 口腔 | 口内边界固定到实际唇缘，内部连续变形；强制镜像后重新贴合 Face 与 Mouth，避免两次表面插值产生小接缝 | 存在对应分区时执行 | recipe | procedural_cavity.deform |
| 11 | 牙齿 | 内置口型按 Original 张口时牙片的一致运动校准上下排，再按嘴宽适配各自位移与旋转，不重复叠加竖向随唇浮动。原参考静止的牙齿保持原位；目标有小间隙时，下牙整组上移至首次接触，最多嘴宽的 30%，缺少独立上下牙则跳过。未校准的自定义或下颌动作保留有界随唇处理。接触可先收回校准动作中的前移，再按牙弓与嘴宽的较大值取 6.5% 额度整排后移，保留牙弓及上下行程；未校准动作仍采用 2.5% 共同后移及 4% 局部后移。检查局部修正是否引入新的三角面翻折；额度不足记录穿插，不向外推 Face，不缩放牙弓，不改变 Basis | 存在对应分区时执行 | recipe | procedural_constraints.close_dental_contact / procedural_contacts.oral_face |
| 12 | 口内接触 | 按唇缘相连拓扑选择 Face 接触面，包含斜面及内翻唇面；牙齿及口腔退回面部内侧，口腔唇缘固定。取消舌头随整排牙齿最前点后退；牙齿与舌头的接触只由实际三角面交叉触发。舌头上表面避开下口腔，Basis 同样检查；接触位移上限取舌长 12% 和口宽 8% 的较小值，同次修正反复检查共用额度；超出额度报告冲突 | 存在对应分区时执行 | recipe | procedural_contacts.finish / tongue_teeth / tongue_side |
| 13 | 写入 | 表情形态键、口腔联动和最终变形曲线一起保存 | 存在对应分区时执行 | recipe | procedural_generate.generate |
| 14 | 数值配方 | 使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束 | 按当前曲线与分区计算 | recipe.brows | procedural_atoms.merge |

数值定义：JSON 中 `expressions` 的同名项。
