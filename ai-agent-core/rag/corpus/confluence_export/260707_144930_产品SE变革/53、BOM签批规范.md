---
l1: 科技
l2: AI
l3: 研发体系
title: 53、BOM签批规范
fetched_at: '2026-07-07T14:52:31.536140'
categories:
- l1: 科技
  l2: AI
  l3: 研发体系
- l1: 科技
  l2: 终端
  l3: 形态
- l1: 职场
  l2: IP
  l3: 思考
---

# 53、BOM签批规范

> pageId: 243464237 | 导出时间: 2026-07-07T14:52:31.536315

角色R更新时间
 
沟通对象BOM工程师、整机产品开发经理具体内容研发BOM、订单BOM签批。操作方法
BOM指的是物料清单，分为研发BOM跟订单BOM。

1. 项目立项后，**项目经理**会要求**硬件工程师**发起BOM制作流程，要求各专业工程师上传ISN号。软件Leader需要上传软件ISN号（包括Project ID/Software Version/Localdimming Version等信息）。
2. **BOM工程师**根据各专业确认上传的物料信息制作研发BOM并在PDM系统上发起签批流程。软件Leader需要确认BOM中软件物料信息正确性（包括V6/V8信息），若发现软件物料信息有误，需要邮件通知**BOM工程师**修正。
3. 若确认研发BOM中软件物料信息正确，软件Leader需要继续发起MID流程，将机芯平台需要的MAC/DeviceID/HDCP_Key/HDCP2.2_Key/Widevine_Key/MGK_Key等上载到MID（**跟机芯平台及出货地区有关**）；需要重点确认机芯平台是否需要“**导入机器名称**”，此项直接影响到产线生产是否抄写Model Name。
4. MID流程提交**整机产品开发经理**签批后，软件Leader直接签批研发BOM流程即可。
5. 研发BOM签批后，**ODF工程师**会跟进订单转正，软件Leader后续需要处理订单BOM签批流程。在确认订单BOM中软件物料信息正确后，由于订单BOM相关MID信息会直接继承研发BOM，软件Leader不需要重新上载MID信息，但仍要审核MID信息项的正确性并发起MID流程。待整机产品开发经理签批后，软件Leader直接签批订单BOM流程即可。
标准与原则
适用项目阶段
LR、TR、PR、IP、MP
适用项目范围S、A、B、C、D交付件
备注
[返回目录](https://confluence.tclking.com/pages/viewpage.action?pageId=9052451)
