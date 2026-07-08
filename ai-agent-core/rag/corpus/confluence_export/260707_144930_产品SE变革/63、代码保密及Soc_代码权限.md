---
l1: 科技
l2: AI
l3: 研发体系
title: 63、代码保密及Soc 代码权限
fetched_at: '2026-07-07T14:52:43.075379'
categories:
- l1: 科技
  l2: AI
  l3: 研发体系
- l1: 关系
  l2: 沟通
  l3: 情绪
---

# 63、代码保密及Soc 代码权限

> pageId: 243464250 | 导出时间: 2026-07-07T14:52:43.075477

| 标题 | 63、代码保密及Soc 代码权限 |
| --- | --- |
| 状态 | 待评审 |
| 角色 | A |
| 更新时间 |   |
| 沟通对象 | 平台软件leader，区域软件leader，Soc  |
| 具体内容 | 源文件传递、源代码Soc 权限 |
| 操作方法 | 1、软件leader 跟 Soc 联合调试问题的过程中，严禁通过微信、邮件等方式传输代码源文件  1，tclconfig 目前所有文件， 2，产品代码根目录下 make_image_XXX 及其他跟编译相关文件脚本，app_updataXXX 应用下载脚本； 3，Device 目录跟应用打包编译 相关的配置 及 分区包  编译相关的配置 4，vendor/tcl tvmanager、tvos 相关目录 |
| 标准与原则 | 软件leader 修改的代码范围只产品配置相关，严禁修改其他模块和目录 |
| 适用项目阶段 | kick off |
| 适用项目范围 | S、A、B、C、D |
| 交付件 |  |
| 备注 |  |
| [返回目录](https://confluence.tclking.com/pages/viewpage.action?pageId=9052451) |  |
