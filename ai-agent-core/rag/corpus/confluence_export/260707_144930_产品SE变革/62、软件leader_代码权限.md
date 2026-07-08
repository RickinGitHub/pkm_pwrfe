---
l1: 科技
l2: AI
l3: 研发体系
title: 62、软件leader 代码权限
fetched_at: '2026-07-07T14:52:42.574522'
categories:
- l1: 科技
  l2: AI
  l3: 研发体系
- l1: 认知
  l2: 方法论
  l3: 建模
- l1: 关系
  l2: 沟通
  l3: 情绪
---

# 62、软件leader 代码权限

> pageId: 243464249 | 导出时间: 2026-07-07T14:52:42.574731

| 标题 | 62、软件leader 代码权限 |
| --- | --- |
| 状态 | 待评审 |
| 角色 | A |
| 更新时间 |   |
| 沟通对象 | 产品SE/系统SE，平台软件leader，区域软件leader， |
| 具体内容 | 软件leader 不能有+2 入库权限 |
| 操作方法 | 软件leader 能修改的代码范围： 1，tclconfig 目前所有文件， 2，产品代码根目录下 make_image_XXX 及其他跟编译相关文件脚本，app_updataXXX 应用下载脚本； 3，Device 目录跟应用打包编译 相关的配置 及 分区包  编译相关的配置 4，vendor/tcl tvmanager、tvos 相关目录     软件leader 入库权限：  1、除了删除 软件leader 能修改的代码范围有+2 入库权限外，其他目录软件leader 不能有入库权限  2、其他目录或者模块的入库权限需要找功能owner 或者 SE 来入库 |
| 标准与原则 | 软件leader 修改的代码范围只产品配置相关，严禁修改其他模块和目录 |
| 适用项目阶段 | kick off |
| 适用项目范围 | S、A、B、C、D |
| 交付件 |  |
| 备注 |  |
| [返回目录](https://confluence.tclking.com/pages/viewpage.action?pageId=9052451) |  |
