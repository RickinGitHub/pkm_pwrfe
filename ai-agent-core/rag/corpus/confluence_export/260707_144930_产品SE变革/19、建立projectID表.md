---
l1: 科技
l2: 终端
l3: 形态
title: 19、建立projectID表
fetched_at: '2026-07-07T14:51:43.898218'
categories:
- l1: 科技
  l2: 终端
  l3: 形态
- l1: 关系
  l2: 沟通
  l3: 情绪
---

# 19、建立projectID表

> pageId: 243464187 | 导出时间: 2026-07-07T14:51:43.898149

角色A更新时间
 
沟通对象软件项目经理、硬件工程师、SQA测试Leader具体内容确定项目相关功能及硬件配置信息，完善projectID表操作方法
1、在confluence的项目空间创建projectID表页面（若projectID表数据较大，在线编辑效率较低，建议按照数量进行分页），并为硬件工程师开通读写权限；

2、当项目kick off时，由软件项目经理创建对应的配屏需求和任务，并分配给软件Leader，对应的story由SQA测试Leader关联配屏对应的测试用例；

3、软件Leader在接收到任务后，在projectID表中增加为项目分配的projectID，将项目对应的projectID表路径关联到Jira项目对应的配屏任务上；

4、软件Leader将问题流转至硬件工程师，由硬件工程师将项目硬件配置信息填写至对应的projectID表，完成后再将任务流转至软件Leader进行配屏相关的工作，并将BOM相关信息同步到对应的projectID表中；

5、硬件测试的用例由硬件工程师同步关联到对应的jira项目任务上，硬件测试后出现的问题可以直接提交bug至jira，并由软件项目经理和软件Leader跟进解决；
标准与原则缺 projectID标准表格适用项目阶段Kick off，LR适用项目范围S、A、B、C、D交付件
备注
[返回目录](https://confluence.tclking.com/pages/viewpage.action?pageId=9052451)
