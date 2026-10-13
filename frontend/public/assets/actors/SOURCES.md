# 演练人物与巡检机器人资源

这些文件随项目本地部署，运行时不访问模型网站，不需要模型平台账号。

## 人物与护送员

- 原作者：Quaternius，Ultimate Modular Men Pack。
- 官方说明：https://quaternius.com/packs/ultimatemodularcharacters.html
- 许可：CC0-1.0，全文见同目录 `CC0-LICENSE.txt`。
- 获取镜像：https://github.com/euuuuuuan/fatal-funnel-public/tree/main/packages/renderer/assets/models/quaternius-men
- 镜像许可记录：https://github.com/euuuuuuan/fatal-funnel-public/blob/main/CREDITS.md
- 原文件 `casual-character.glb` SHA-256：`fea7e71271203e7073f1a073fa1208de7402df276f87f80e149bf7589b5d46b4`。
- 原文件 `worker.glb` SHA-256：`9c28614f465b7dc105f908c20c22fc045f4b07caf8c5ef0e9f8049eceb6dd38d`。
- 本地派生文件：`resident-casual.glb`、`helper-worker.glb`。保留 Idle、Idle_Neutral、Walk、Run、Wave、Interact 六段动画，剔除战斗动画；不含外部贴图依赖。
- 运行时：62 骨骼独立实例、服装配色与身高差异、重点人员灰发、工作服护送员、待机/行走混合；步频由实际位移驱动，暂停时冻结。其余保留动作尚未绑定业务行为，不能视为已经实现挥手救援等功能。

## 巡检机器人

- 原作者：Clearpath Robotics Inc.，Husky 开源机器人描述网格。
- 来源：https://github.com/husky/husky/tree/noetic-devel/husky_description/meshes
- 许可：BSD-3-Clause，版权与免责声明见同目录 `HUSKY-LICENSE.txt`，分发时必须保留。
- 使用 `base_link.dae`、`wheel.dae`、`top_chassis.dae`、`top_plate.dae`、`bumper.dae`，整理为 `husky-parts.glb`。
- 采用源 URDF 的轴距 0.512 m、轮距 0.555 m、轮半径 0.1651 m；ROS 坐标统一转换为 Three.js Y-up、-Z 前向。
- 摄像头、雷达、通讯天线、状态灯、扬声器与电子设备箱由本项目补充。此为消防演练中的巡检机器人视觉组合，不表示原厂家支持消防功能或为本项目背书。
- 轮胎转动由实际位移驱动；扫描类状态才驱动雷达和云台；阻塞状态灯变为琥珀色。未接入真实机器人硬件。

## 复现与边界

- 原始文件位于 `frontend/tools/actor-sources/`，不会复制到生产静态目录。
- 启动前端后运行 `frontend/tools/prepare-actors.mjs`，设置 `PLAYWRIGHT_MODULE`（如不在 node_modules）及可选 `QA_BROWSER_PATH`。工具使用本地 Three.js 导出 GLB，不执行下载包中的代码。
- 开发预览：`/tools/actors-preview.html`；它与导演台复用 `ActorAssets`，不是业务入口，生产构建不包含该预览页。
- 加载失败保留现有轻量模型；超时 30 秒；退出演练中止请求并释放本场景骨骼、材质及几何体。
- 近景使用完整模型，中景使用关节简模，远景进一步降级；三档画质调整切换距离。所有疏散位置仍以原仿真数据为准。
- 这是细节增强的实时低多边形建模，不是照片级人物扫描。当前居民以一套成人基础体型派生，尚未增加女性、儿童、轮椅模型或足部 IK；不将外观差异等同于新增人群行为规则。
- `threejs-loaders`、`threejs-animation` 技能来自 https://github.com/CloudAI-X/threejs-skills ，用于指导资源管理、骨骼克隆、动作混合及暂停处理，不是项目运行依赖。
