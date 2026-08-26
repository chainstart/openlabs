# Physics Lab 开源复用审计

审计日期：2026-08-26。目标不是把所有“AI scientist”项目叠加在一起，而是选择许可清晰、
可固定版本、不会抢走 OpenLabs 控制面的物理计算组件与领域说明。

## 已纳入

- [K-Dense Scientific Agent Skills](https://github.com/K-Dense-AI/scientific-agent-skills)：仓库支持
  Codex/Open Agent Skills，整体 MIT；本次固定 `v2.52.0`/commit
  `9c12fcc25efb2042ec41d5d9c331a76f8e2020b5`，只复制纯 Markdown 的 Astropy 与 QuTiP
  Skill。两个 Skill 自身元数据均声明 BSD-3-Clause。
- [QuTiP](https://github.com/qutip/qutip)：BSD-3-Clause，用于闭系与开放量子系统动力学；作为
  可选依赖，不把量子线路或真实硬件执行混为同一能力。
- [Astropy](https://www.astropy.org/)：BSD-3-Clause，用于单位、坐标、时间、FITS、WCS 与
  宇宙学；对远程名称解析、IERS 更新和远程 FITS 仍要求网络与来源记录。
- [Scikit-HEP](https://scikit-hep.org/) 的 Uproot/Awkward/Vector/Hist/iminuit/pyhf：用于纯
  Python ROOT I/O、不规则事件数据、运动学与 HistFactory 统计推断。
- SymPy/mpmath/python-flint、CVXPY/Clarabel/SCS、HDF5/xarray：分别承担符号/高精度、
  凸优化和结构化数组存储；它们是计算库，不是科研调度器。

## 只吸收方法、不复制

- [Hugging Face PhysicsIntern](https://github.com/huggingface/physics-intern-skills) 对理论物理的
  文件化状态、fresh-context 推导/计算复核很有价值。但审计 commit
  `41d75f998710948e90b9254fba1cc501fe09fc84` 未发现 LICENSE/COPYING，且其主调度器与
  OpenLabs 重叠，因此没有复制代码或 prompt，只在原创 Skill 中实现独立证据组原则。

## 暂缓

- [ColliderAgent](https://github.com/HET-AGI/ColliderAgent) 为 MIT，但完整路线涉及
  MadGraph/Pythia/Delphes/MadAnalysis、云或容器执行，并可选依赖 Wolfram 许可。它适合未来
  单独的 collider profile，不适合成为默认环境。
- 真实仪器控制、实验室自动化、量子硬件提交和任何有物理副作用的接口均不纳入。本实验室只
  处理解析/数值研究与许可清晰的既有公共实验或观测数据。

具体固定版本见 `labs/physics/pyproject.toml`/`uv.lock`，第三方 Skill 来源见
`labs/physics/skills/vendor/scientific-agent-skills.lock.json`，数据源准入见
`labs/physics/registries/data_sources.json`。
